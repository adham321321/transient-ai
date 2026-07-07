"""XMEML export: generate Premiere-compatible XML with frame accuracy (Section 4.5)."""

from typing import List, Dict, Optional, Tuple
from lxml import etree
from datetime import datetime
import subprocess
import json
from engine.multicam_edit import Cut


class XMEMLExporter:
    """
    Generate XMEML (Premiere) sequences with full schema completeness.
    Section 4.5: frame-accurate, real pathurls, correct samplecharacteristics.
    """

    def __init__(self, project_state, clip_mapper):
        """
        Initialize with:
          - project_state: ProjectState
          - clip_mapper: ClipMapper for coverage verification
        """
        self.project = project_state
        self.mapper = clip_mapper

    def export_cuts_to_xmeml(
        self,
        cuts: List[Cut],
        output_path: str,
        sequence_name: str = "Generated Multicam Cut",
    ) -> bool:
        """
        Export a list of cuts as an XMEML sequence.
        
        Returns True on success, False on error.
        Never raise; always return status.
        """
        try:
            root = self._build_xmeml_root(cuts, sequence_name)
            tree = etree.ElementTree(root)
            tree.write(output_path, xml_declaration=True, encoding="UTF-8", pretty_print=True)
            print(f"[XMEMLExporter] Exported to {output_path}")
            return True
        except Exception as e:
            print(f"[XMEMLExporter] Export failed: {e}")
            return False

    def _build_xmeml_root(self, cuts: List[Cut], sequence_name: str) -> etree._Element:
        """Build the root <xmeml> element with sequence and tracks."""
        xmeml = etree.Element("xmeml")
        xmeml.set("version", "2")
        
        # Project metadata
        project = etree.SubElement(xmeml, "project")
        name_elem = etree.SubElement(project, "name")
        name_elem.text = self.project.settings.project_name
        
        # Sequence
        sequence = self._build_sequence(cuts, sequence_name)
        project.append(sequence)
        
        return xmeml

    def _build_sequence(self, cuts: List[Cut], sequence_name: str) -> etree._Element:
        """Build the <sequence> element with format and tracks."""
        sequence = etree.Element("sequence")
        sequence.set("id", f"sequence_{int(datetime.now().timestamp())}")
        
        # Sequence metadata
        name_elem = etree.SubElement(sequence, "name")
        name_elem.text = sequence_name
        
        duration_elem = etree.SubElement(sequence, "duration")
        total_duration = cuts[-1].end if cuts else 0
        duration_elem.text = str(self._seconds_to_frames(total_duration))
        
        # Format (Section 4.5: full schema completeness)
        self._add_format_element(sequence)
        
        # Media: video and audio tracks
        media = etree.SubElement(sequence, "media")
        
        # Video track
        self._add_video_track(media, cuts)
        
        # Audio track (with mixdown audio)
        self._add_audio_track(media, cuts)
        
        return sequence

    def _add_format_element(self, parent: etree._Element):
        """Add <format> element with full samplecharacteristics."""
        fmt = etree.SubElement(parent, "format")
        
        # Video format
        timebase = etree.SubElement(fmt, "timebase")
        timebase.text = str(int(self.project.settings.frame_rate))
        
        # Sample characteristics (Section 4.5: critical for NLE import)
        samplecharacteristics = etree.SubElement(fmt, "samplecharacteristics")
        
        width_elem = etree.SubElement(samplecharacteristics, "width")
        width_elem.text = str(self.project.settings.native_resolution[0])
        
        height_elem = etree.SubElement(samplecharacteristics, "height")
        height_elem.text = str(self.project.settings.native_resolution[1])
        
        pixelaspectratio = etree.SubElement(samplecharacteristics, "pixelaspectratio")
        pixelaspectratio.text = "1"
        
        # Audio sample rate
        samplerate = etree.SubElement(samplecharacteristics, "samplerate")
        samplerate.text = "48000"
        
        # Field order
        fieldtype = etree.SubElement(samplecharacteristics, "fieldtype")
        fieldtype.text = "progressive"

    def _add_video_track(self, media: etree._Element, cuts: List[Cut]):
        """Add video track with cut clipitems."""
        video = etree.SubElement(media, "video")
        track = etree.SubElement(video, "track")
        track.set("currentExplicitMatteCount", "0")
        track.set("premiereTrackType", "Premiere")
        
        for cut_idx, cut in enumerate(cuts):
            self._add_video_clipitem(track, cut, cut_idx)

    def _add_video_clipitem(self, track: etree._Element, cut: Cut, idx: int):
        """
        Add a video <clipitem> for a single cut.
        Section 4.5: per-clip duration/rate, correct in/out points.
        """
        clipitem = etree.SubElement(track, "clipitem")
        clipitem.set("id", f"cut_{idx}")
        clipitem.set("premiereChannelType", "Composite Video")
        
        # Timing (in timeline frames)
        start = etree.SubElement(clipitem, "start")
        start.text = str(self._seconds_to_frames(cut.start))
        
        end = etree.SubElement(clipitem, "end")
        end.text = str(self._seconds_to_frames(cut.end))
        
        # Get the actual clip from the camera
        clip_placement = self.mapper.get_clip_at(cut.camera, cut.start)
        if clip_placement is None:
            # Fallback; shouldn't happen if cut generation was correct
            print(f"[XMEMLExporter] Warning: no clip found for {cut.camera} at {cut.start}")
            return
        
        # Source in/out
        in_elem = etree.SubElement(clipitem, "in")
        in_elem.text = str(self._seconds_to_frames(clip_placement.source_in))
        
        out_elem = etree.SubElement(clipitem, "out")
        out_elem.text = str(self._seconds_to_frames(clip_placement.source_out))
        
        # Name
        name = etree.SubElement(clipitem, "name")
        name.text = f"{cut.camera} - Cut {idx}"
        
        # Duration
        duration = etree.SubElement(clipitem, "duration")
        duration.text = str(self._seconds_to_frames(cut.duration))
        
        # Rate
        rate = etree.SubElement(clipitem, "rate")
        timebase = etree.SubElement(rate, "timebase")
        timebase.text = str(int(self.project.settings.frame_rate))
        
        # File reference (Section 4.5: percent-encoded, real file:// URL)
        file_elem = etree.SubElement(clipitem, "file")
        file_elem.set("id", f"file_{idx}")
        pathurl = etree.SubElement(file_elem, "pathurl")
        pathurl.text = self._encode_pathurl(clip_placement.file_path)
        
        # Media reference with samplecharacteristics
        media = etree.SubElement(clipitem, "media")
        video_media = etree.SubElement(media, "video")
        
        # Get actual file dimensions (Section 4.5: auto-detect from clip)
        dimensions = self._get_clip_dimensions(clip_placement.file_path)
        if dimensions:
            samplechar = etree.SubElement(video_media, "samplecharacteristics")
            w, h = dimensions
            width_elem = etree.SubElement(samplechar, "width")
            width_elem.text = str(w)
            height_elem = etree.SubElement(samplechar, "height")
            height_elem.text = str(h)

    def _add_audio_track(self, media: etree._Element, cuts: List[Cut]):
        """
        Add audio track with mixdown audio.
        Section 4.5: "Include the actual mix-down audio as a real track
        at its correct, real timeline position."
        """
        audio = etree.SubElement(media, "audio")
        
        # Check if we have audio sources
        if not self.project.audio_sources:
            return
        
        # Use the first clean audio source (or first available)
        sync_audio = None
        for src in self.project.audio_sources:
            if src.audio_type.value == "clean":
                sync_audio = src
                break
        
        if not sync_audio:
            sync_audio = self.project.audio_sources[0]
        
        # Create audio track
        track = etree.SubElement(audio, "track")
        track.set("currentExplicitMatteCount", "0")
        track.set("premiereTrackType", "Premiere")
        
        # Single audio clipitem spanning the full mixdown
        clipitem = etree.SubElement(track, "clipitem")
        clipitem.set("id", "audio_mixdown")
        clipitem.set("premiereChannelType", "Stereo")
        
        # Timeline position (at the real audio offset)
        audio_offset = sync_audio.in_point
        
        start = etree.SubElement(clipitem, "start")
        start.text = str(self._seconds_to_frames(audio_offset))
        
        end = etree.SubElement(clipitem, "end")
        total_audio_duration = sync_audio.get_duration()
        end.text = str(self._seconds_to_frames(audio_offset + total_audio_duration))
        
        # In/out from file
        in_elem = etree.SubElement(clipitem, "in")
        in_elem.text = str(self._seconds_to_frames(sync_audio.in_point))
        
        out_elem = etree.SubElement(clipitem, "out")
        out_elem.text = str(self._seconds_to_frames(sync_audio.out_point or sync_audio.duration))
        
        # Name
        name = etree.SubElement(clipitem, "name")
        name.text = sync_audio.name
        
        # Duration
        duration = etree.SubElement(clipitem, "duration")
        duration.text = str(self._seconds_to_frames(total_audio_duration))
        
        # Rate (audio is frame-based in XMEML, but sample rate matters)
        rate = etree.SubElement(clipitem, "rate")
        timebase = etree.SubElement(rate, "timebase")
        timebase.text = "1"  # Audio uses sample rate
        
        # File reference
        file_elem = etree.SubElement(clipitem, "file")
        file_elem.set("id", "audio_file")
        pathurl = etree.SubElement(file_elem, "pathurl")
        pathurl.text = self._encode_pathurl(sync_audio.file_path)
        
        # Audio media info
        media_elem = etree.SubElement(clipitem, "media")
        audio_media = etree.SubElement(media_elem, "audio")
        samplechar = etree.SubElement(audio_media, "samplecharacteristics")
        
        samplerate = etree.SubElement(samplechar, "samplerate")
        samplerate.text = str(sync_audio.sample_rate)
        
        channelcount = etree.SubElement(samplechar, "channelcount")
        channelcount.text = "2" if sync_audio.channel_format.value == "stereo" else "1"

    def _seconds_to_frames(self, seconds: float) -> int:
        """Convert seconds to frame count."""
        return int(round(seconds * self.project.settings.frame_rate))

    def _frames_to_seconds(self, frames: int) -> float:
        """Convert frame count to seconds."""
        return frames / self.project.settings.frame_rate

    def _encode_pathurl(self, file_path: str) -> str:
        """
        Encode file path as file:// URL with percent-encoding.
        Section 4.5: handle spaces, special chars, accents.
        """
        import urllib.parse
        import pathlib
        
        # Convert to Path
        path = pathlib.Path(file_path)
        
        # Convert to file:// URL
        file_url = path.as_uri()
        
        return file_url

    def _get_clip_dimensions(self, file_path: str) -> Optional[Tuple[int, int]]:
        """
        Auto-detect video dimensions using ffprobe.
        Section 4.5: "Auto-detect real frame dimensions from an actual source clip."
        """
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=width,height",
                    "-of", "json",
                    file_path,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                if data.get("streams"):
                    stream = data["streams"][0]
                    width = stream.get("width")
                    height = stream.get("height")
                    if width and height:
                        return (width, height)
        except Exception as e:
            print(f"[XMEMLExporter] Warning: could not probe {file_path}: {e}")
        
        # Fallback to project resolution
        return self.project.settings.native_resolution


class AspectRatioReframer:
    """Generate alternate aspect ratio versions of a cut sequence."""

    RATIOS = {
        "16:9": (16, 9),   # Landscape
        "4:5": (4, 5),     # Instagram feed
        "9:16": (9, 16),   # Reels/Stories
    }

    def __init__(self, project_state):
        self.project = project_state

    def reframe_sequence(
        self,
        cuts: List[Cut],
        target_ratio: str,
        use_4k_master: bool = True,
    ) -> List[Cut]:
        """
        Reframe a cut sequence to a different aspect ratio.
        Section 3.6: "Vertical reframes (4:5 / 9:16) auto-use a 4K master so they stay sharp."
        
        For now, just return the same cuts; in production, this would adjust
        pan/zoom, crop coordinates, or resolution.
        """
        if target_ratio not in self.RATIOS:
            print(f"[AspectRatioReframer] Unknown ratio: {target_ratio}")
            return cuts
        
        # Placeholder: in production, apply pan/zoom based on ratio
        # For now, assume the same cut logic applies to all ratios
        return cuts

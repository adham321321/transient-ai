"""Sync management: parse XMEML, compute offsets, track clip placement (Section 4.3)."""

from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from lxml import etree
import re


@dataclass
class ClipPlacement:
    """A clip placed on a timeline track at a specific position."""
    camera_name: str
    file_path: str
    timeline_start: float  # seconds, absolute position on sequence
    timeline_end: float
    source_in: float  # seconds, where in the file to start reading
    source_out: float  # seconds, where in the file to stop reading
    duration: float  # timeline duration (seconds)
    frame_rate: float


@dataclass
class AudioClipPlacement:
    """An audio clip placement with frame-accurate offset tracking."""
    name: str
    file_path: str
    timeline_start: float  # seconds
    timeline_end: float
    source_in: float  # where in the audio file to start
    source_out: float  # where in the audio file to stop
    duration: float
    sample_rate: int
    
    def get_audio_offset(self) -> float:
        """
        Return the real offset between timeline 0 and audio file 0.
        Section 4.3: audio_clip.timeline_start - audio_clip.source_in
        This is CRITICAL for sync — without it, cuts drift out of sync.
        """
        return self.timeline_start - self.source_in


class SyncXMLParser:
    """Parse XMEML (Premiere/PluralEyes) export with strict frame-accuracy."""

    def __init__(self):
        self.ns = {"": "http://www.adobe.com/premierepro/12"}  # Default namespace
        self.video_clips: List[ClipPlacement] = []
        self.audio_clips: List[AudioClipPlacement] = []
        self.frame_rate: float = 25.0
        self.sample_rate: int = 48000

    def parse_file(self, xml_path: str) -> bool:
        """
        Parse XMEML file. Return True on success, False on error.
        Never raise; always return status (Section 4.1 defensive).
        """
        try:
            tree = etree.parse(xml_path)
            root = tree.getroot()
            
            # Extract frame rate from sequence format
            self._extract_sequence_format(root)
            
            # Parse all video tracks
            self._parse_video_tracks(root)
            
            # Parse all audio tracks
            self._parse_audio_tracks(root)
            
            return True
        except Exception as e:
            print(f"[SyncXMLParser] Error parsing {xml_path}: {e}")
            return False

    def _extract_sequence_format(self, root):
        """Extract frame rate and other sequence-level metadata."""
        try:
            # Find sequence format
            timebase = root.find(".//timebase")
            if timebase is not None:
                self.frame_rate = float(timebase.text or 25.0)
            
            samplecharacteristics = root.find(".//samplecharacteristics")
            if samplecharacteristics is not None:
                sr_elem = samplecharacteristics.find("samplerate")
                if sr_elem is not None:
                    self.sample_rate = int(sr_elem.text or 48000)
        except Exception as e:
            print(f"[SyncXMLParser] Warning: could not extract format: {e}")

    def _parse_video_tracks(self, root):
        """Parse all video tracks (each track = one camera)."""
        video_tracks = root.findall(".//videomedia")
        
        for track_idx, video_track in enumerate(video_tracks):
            clips = video_track.findall(".//clipitem")
            
            for clip in clips:
                placement = self._parse_clipitem(clip, track_idx, is_audio=False)
                if placement:
                    self.video_clips.append(placement)

    def _parse_audio_tracks(self, root):
        """Parse all audio tracks (for sync reference)."""
        audio_tracks = root.findall(".//audiomedia")
        
        for track_idx, audio_track in enumerate(audio_tracks):
            clips = audio_track.findall(".//clipitem")
            
            for clip in clips:
                placement = self._parse_audio_clipitem(clip, track_idx)
                if placement:
                    self.audio_clips.append(placement)

    def _parse_clipitem(self, clipitem_elem, track_idx: int, is_audio: bool) -> Optional[ClipPlacement]:
        """
        Parse a single <clipitem> with frame-accurate in/out points.
        Section 4.3: Parse start, end, in, out literally, no rounding.
        """
        try:
            # Get timing info
            start_elem = clipitem_elem.find("start")
            end_elem = clipitem_elem.find("end")
            in_elem = clipitem_elem.find("in")
            out_elem = clipitem_elem.find("out")
            
            if None in [start_elem, end_elem, in_elem, out_elem]:
                return None
            
            start = self._timecode_to_seconds(start_elem.text, self.frame_rate)
            end = self._timecode_to_seconds(end_elem.text, self.frame_rate)
            source_in = self._timecode_to_seconds(in_elem.text, self.frame_rate)
            source_out = self._timecode_to_seconds(out_elem.text, self.frame_rate)
            
            # Get file path
            file_elem = clipitem_elem.find(".//file/pathurl")
            if file_elem is None or not file_elem.text:
                return None
            file_path = self._decode_pathurl(file_elem.text)
            
            # Compute duration (timeline duration, not source)
            duration = end - start
            
            # Camera name: use clipitem name or generate from track
            name_elem = clipitem_elem.find("name")
            camera_name = name_elem.text if name_elem is not None else f"Camera_{track_idx}"
            
            return ClipPlacement(
                camera_name=camera_name,
                file_path=file_path,
                timeline_start=start,
                timeline_end=end,
                source_in=source_in,
                source_out=source_out,
                duration=duration,
                frame_rate=self.frame_rate,
            )
        except Exception as e:
            print(f"[SyncXMLParser] Error parsing clipitem: {e}")
            return None

    def _parse_audio_clipitem(self, clipitem_elem, track_idx: int) -> Optional[AudioClipPlacement]:
        """Parse audio clipitem with sample-rate awareness."""
        try:
            start_elem = clipitem_elem.find("start")
            end_elem = clipitem_elem.find("end")
            in_elem = clipitem_elem.find("in")
            out_elem = clipitem_elem.find("out")
            
            if None in [start_elem, end_elem, in_elem, out_elem]:
                return None
            
            # For audio, convert timecode to seconds using frame rate
            # (XMEML stores everything in frames, even audio)
            start = self._timecode_to_seconds(start_elem.text, self.frame_rate)
            end = self._timecode_to_seconds(end_elem.text, self.frame_rate)
            source_in = self._timecode_to_seconds(in_elem.text, self.frame_rate)
            source_out = self._timecode_to_seconds(out_elem.text, self.frame_rate)
            
            file_elem = clipitem_elem.find(".//file/pathurl")
            if file_elem is None or not file_elem.text:
                return None
            file_path = self._decode_pathurl(file_elem.text)
            
            name_elem = clipitem_elem.find("name")
            name = name_elem.text if name_elem is not None else f"Audio_{track_idx}"
            
            duration = end - start
            
            return AudioClipPlacement(
                name=name,
                file_path=file_path,
                timeline_start=start,
                timeline_end=end,
                source_in=source_in,
                source_out=source_out,
                duration=duration,
                sample_rate=self.sample_rate,
            )
        except Exception as e:
            print(f"[SyncXMLParser] Error parsing audio clipitem: {e}")
            return None

    def _timecode_to_seconds(self, timecode_str: str, frame_rate: float) -> float:
        """
        Convert timecode (HH:MM:SS:FF) to seconds.
        Frame-accurate: no rounding (Section 4.3).
        """
        try:
            parts = timecode_str.split(":")
            if len(parts) == 4:
                hours, minutes, seconds, frames = map(int, parts)
                total_seconds = hours * 3600 + minutes * 60 + seconds + frames / frame_rate
                return total_seconds
            else:
                return 0.0
        except Exception:
            return 0.0

    def _decode_pathurl(self, pathurl: str) -> str:
        """
        Decode file:// URL to local path.
        Section 4.5: handle percent-encoding, spaces, special chars.
        """
        try:
            # Remove file:// prefix
            if pathurl.startswith("file://"):
                pathurl = pathurl[7:]
            
            # Percent-decode
            pathurl = self._percent_decode(pathurl)
            
            return pathurl
        except Exception as e:
            print(f"[SyncXMLParser] Error decoding pathurl: {e}")
            return pathurl

    @staticmethod
    def _percent_decode(s: str) -> str:
        """Decode percent-encoded URL."""
        import urllib.parse
        return urllib.parse.unquote(s)


class SyncOffsetComputer:
    """
    Compute sync offsets between cameras based on sync reference audio.
    Section 4.2/4.3: Camera-by-camera offset tracking.
    """

    def __init__(self, parser: SyncXMLParser):
        self.parser = parser
        self.sync_audio: Optional[AudioClipPlacement] = None
        self.camera_offsets: Dict[str, float] = {}

    def set_sync_audio(self, audio_name: str) -> bool:
        """
        Set which audio clip is the sync reference.
        Return True if found, False otherwise.
        """
        for audio in self.parser.audio_clips:
            if audio.name == audio_name:
                self.sync_audio = audio
                return True
        return False

    def compute_offsets(self) -> Dict[str, float]:
        """
        Compute offset for each camera relative to sync audio.
        Section 4.3: The real offset is audio_clip.timeline_start - audio_clip.source_in
        
        Returns dict: camera_name -> offset_in_seconds
        """
        if self.sync_audio is None:
            return {}
        
        self.camera_offsets = {}
        sync_offset = self.sync_audio.get_audio_offset()
        
        # Group video clips by camera
        cameras: Dict[str, List[ClipPlacement]] = {}
        for clip in self.parser.video_clips:
            if clip.camera_name not in cameras:
                cameras[clip.camera_name] = []
            cameras[clip.camera_name].append(clip)
        
        # For each camera, compute offset from first clip's timeline position
        for camera_name, clips in cameras.items():
            if clips:
                first_clip = clips[0]
                # Offset: where this camera starts on timeline relative to sync audio's offset
                camera_offset = first_clip.timeline_start - sync_offset
                self.camera_offsets[camera_name] = camera_offset
        
        return self.camera_offsets

    def get_offset(self, camera_name: str) -> float:
        """Get the offset for a specific camera (seconds)."""
        return self.camera_offsets.get(camera_name, 0.0)


class ClipMapper:
    """
    Query camera coverage without fabrication (Section 4.2/4.3).
    "Does this camera have footage at time T?" → True only if an actual clip covers it.
    """

    def __init__(self, parser: SyncXMLParser, offsets: Dict[str, float]):
        self.parser = parser
        self.offsets = offsets  # camera_name -> offset_seconds

    def has_coverage_at(self, camera_name: str, timeline_seconds: float) -> bool:
        """
        Check if a camera has real footage at a timeline position.
        Never fabricate; return False for gaps.
        """
        offset = self.offsets.get(camera_name, 0.0)
        
        for clip in self.parser.video_clips:
            if clip.camera_name != camera_name:
                continue
            
            # Adjust for offset
            clip_start = clip.timeline_start - offset
            clip_end = clip.timeline_end - offset
            
            if clip_start <= timeline_seconds < clip_end:
                return True
        
        return False

    def get_clip_at(self, camera_name: str, timeline_seconds: float) -> Optional[ClipPlacement]:
        """
        Get the exact clip covering a timeline position.
        Return None if no coverage (gap or camera doesn't exist).
        """
        offset = self.offsets.get(camera_name, 0.0)
        
        for clip in self.parser.video_clips:
            if clip.camera_name != camera_name:
                continue
            
            clip_start = clip.timeline_start - offset
            clip_end = clip.timeline_end - offset
            
            if clip_start <= timeline_seconds < clip_end:
                return clip
        
        return None

    def get_total_coverage(self, camera_name: str) -> float:
        """
        Get total coverage duration for a camera (accounting for gaps).
        Returns the span from first clip start to last clip end.
        """
        offset = self.offsets.get(camera_name, 0.0)
        clips = [c for c in self.parser.video_clips if c.camera_name == camera_name]
        
        if not clips:
            return 0.0
        
        starts = [c.timeline_start - offset for c in clips]
        ends = [c.timeline_end - offset for c in clips]
        
        return max(ends) - min(starts)

    def list_gaps(self, camera_name: str) -> List[Tuple[float, float]]:
        """
        List all gaps (start, end) in timeline coverage for a camera.
        """
        offset = self.offsets.get(camera_name, 0.0)
        clips = sorted(
            [c for c in self.parser.video_clips if c.camera_name == camera_name],
            key=lambda c: c.timeline_start
        )
        
        if len(clips) < 2:
            return []
        
        gaps = []
        for i in range(len(clips) - 1):
            gap_start = clips[i].timeline_end - offset
            gap_end = clips[i + 1].timeline_start - offset
            if gap_end > gap_start:
                gaps.append((gap_start, gap_end))
        
        return gaps

"""Sync Tab: Import XMEML or manually sync cameras to audio (Section 6.2)."""

from typing import List, Optional, Dict, Tuple
from enum import Enum
import os

from models.project import ProjectState, Camera, AudioSource
from engine.sync_manager import (
    SyncXMLParser,
    SyncOffsetComputer,
    ClipMapper,
    ClipPlacement,
)


class SyncMode(Enum):
    """Sync strategies."""
    XMEML_IMPORT = "xmeml_import"
    MANUAL_OFFSET = "manual_offset"
    TIMECODE_MATCH = "timecode_match"
    AUTO_SYNC = "auto_sync"


class SyncTab:
    """
    Sync Tab: Establish camera-to-audio synchronization.
    
    Workflow:
    1. Choose sync mode (import XMEML, manual offset, timecode match, or auto)
    2. For XMEML: parse file, extract clips and audio, verify coverage
    3. For manual: set per-camera offset (in seconds)
    4. For timecode: align on matching embedded timecodes
    5. For auto: detect sync points automatically
    6. Preview coverage: timeline view showing where each camera is available
    7. Confirm and proceed to Audio tab
    
    Section 6.2: "XMEML import should be painless. Validate before committing.
    Show coverage gaps. Auto-detect offsets if possible."
    """

    def __init__(self, project: ProjectState):
        self.project = project
        self.parser: Optional[SyncXMLParser] = None
        self.offsets: Dict[str, float] = {}
        self.mapper: Optional[ClipMapper] = None
        self.sync_audio_name: Optional[str] = None

    # =========================================================================
    # XMEML Import
    # =========================================================================

    def import_xmeml(self, xmeml_path: str) -> Tuple[bool, str]:
        """
        Import XMEML file and extract clips and audio tracks.
        
        Returns:
          (success, message)
        
        Validates:
        - File exists and is readable
        - XML is well-formed
        - Contains video and audio tracks
        - Frame rate matches project (or warn)
        """
        try:
            if not os.path.exists(xmeml_path):
                return False, f"File not found: {xmeml_path}"
            
            self.parser = SyncXMLParser()
            success = self.parser.parse_file(xmeml_path)
            
            if not success:
                return False, "Failed to parse XMEML file"
            
            # Validate
            if not self.parser.video_clips:
                return False, "No video clips found in XMEML"
            
            if not self.parser.audio_clips:
                return False, "No audio clips found in XMEML"
            
            # Check frame rate
            if self.parser.frame_rate != self.project.settings.frame_rate:
                msg = (
                    f"Warning: XMEML frame rate ({self.parser.frame_rate}) "
                    f"differs from project ({self.project.settings.frame_rate}). "
                    f"Clips will be reinterpreted."
                )
                print(f"[SyncTab] {msg}")
            
            # Create initial offsets (all zero until computed)
            camera_names = set(clip.camera_name for clip in self.parser.video_clips)
            self.offsets = {cam: 0.0 for cam in camera_names}
            
            msg = (
                f"Imported {len(self.parser.video_clips)} video clips "
                f"({len(camera_names)} cameras) "
                f"and {len(self.parser.audio_clips)} audio clips"
            )
            return True, msg
        
        except Exception as e:
            return False, f"XMEML import error: {e}"

    def get_xmeml_summary(self) -> Optional[Dict]:
        """Get summary of imported XMEML (for UI preview)."""
        if not self.parser:
            return None
        
        try:
            cameras = {}
            for clip in self.parser.video_clips:
                if clip.camera_name not in cameras:
                    cameras[clip.camera_name] = {
                        "clip_count": 0,
                        "total_duration": 0.0,
                        "timeline_coverage": [],
                    }
                cameras[clip.camera_name]["clip_count"] += 1
                cameras[clip.camera_name]["total_duration"] += clip.duration
                cameras[clip.camera_name]["timeline_coverage"].append({
                    "start": clip.timeline_start,
                    "end": clip.timeline_end,
                })
            
            audio = []
            for clip in self.parser.audio_clips:
                audio.append({
                    "name": clip.name,
                    "timeline_start": clip.timeline_start,
                    "timeline_end": clip.timeline_end,
                    "duration": clip.duration,
                    "file": clip.file_path,
                })
            
            return {
                "frame_rate": self.parser.frame_rate,
                "cameras": cameras,
                "audio_tracks": audio,
            }
        
        except Exception as e:
            print(f"[SyncTab] Failed to get summary: {e}")
            return None

    # =========================================================================
    # Manual Offset Sync
    # =========================================================================

    def set_camera_offset(self, camera_name: str, offset_seconds: float) -> bool:
        """
        Manually set offset for a camera (in seconds).
        Positive = camera starts later; negative = camera starts earlier.
        """
        try:
            self.offsets[camera_name] = offset_seconds
            print(f"[SyncTab] Set offset for {camera_name}: {offset_seconds}s")
            return True
        except Exception as e:
            print(f"[SyncTab] Failed to set offset: {e}")
            return False

    def set_all_offsets(self, offsets: Dict[str, float]) -> bool:
        """Set all camera offsets at once."""
        try:
            self.offsets.update(offsets)
            print(f"[SyncTab] Updated offsets for {len(offsets)} cameras")
            return True
        except Exception as e:
            print(f"[SyncTab] Failed to set offsets: {e}")
            return False

    # =========================================================================
    # Auto-Sync
    # =========================================================================

    def auto_compute_offsets(self) -> Tuple[bool, Dict[str, float]]:
        """
        Auto-detect camera offsets using audio analysis.
        
        Strategy:
        1. Use first audio track as reference (sync audio)
        2. For each camera, find where its audio (if embedded) matches
        3. Or use visual markers (scene cuts, lighting changes) for rough sync
        
        Returns:
          (success, computed_offsets)
        
        Section 6.2: "Auto-detect offsets if possible."
        """
        if not self.parser:
            return False, {}
        
        try:
            computer = SyncOffsetComputer(self.parser)
            
            # Use first audio as sync reference
            if self.parser.audio_clips:
                sync_audio = self.parser.audio_clips[0]
                computer.set_sync_audio(sync_audio.name)
                self.sync_audio_name = sync_audio.name
            
            offsets = computer.compute_offsets()
            self.offsets = offsets
            
            print(f"[SyncTab] Auto-computed offsets: {offsets}")
            return True, offsets
        
        except Exception as e:
            print(f"[SyncTab] Auto-sync failed: {e}")
            return False, {}

    # =========================================================================
    # Coverage Preview
    # =========================================================================

    def build_clip_mapper(self) -> Tuple[bool, str]:
        """
        Build the ClipMapper for coverage analysis.
        Call this after sync is finalized.
        """
        try:
            if not self.parser:
                return False, "No XMEML loaded"
            
            if not self.offsets:
                return False, "No offsets set"
            
            self.mapper = ClipMapper(self.parser, self.offsets)
            
            msg = f"ClipMapper ready with {len(self.offsets)} cameras"
            return True, msg
        
        except Exception as e:
            return False, f"Failed to build mapper: {e}"

    def get_coverage_report(self, camera_name: str) -> Optional[Dict]:
        """
        Get coverage details for a camera.
        
        Returns:
          {
            "camera": str,
            "total_coverage": float (seconds),
            "gaps": List[(start, end), ...],
            "coverage_percent": float,
            "full_duration": float,
          }
        """
        if not self.mapper:
            return None
        
        try:
            total_coverage = self.mapper.get_total_coverage(camera_name)
            gaps = self.mapper.list_gaps(camera_name)
            
            # Find the overall duration (from parser)
            max_end = 0.0
            for clip in self.parser.video_clips:
                if clip.camera_name == camera_name:
                    max_end = max(max_end, clip.timeline_end)
            
            # Find max duration overall (from all cameras)
            full_duration = 0.0
            for clip in self.parser.video_clips:
                full_duration = max(full_duration, clip.timeline_end)
            
            coverage_percent = (total_coverage / full_duration * 100) if full_duration > 0 else 0.0
            
            return {
                "camera": camera_name,
                "total_coverage": total_coverage,
                "gaps": gaps,
                "coverage_percent": coverage_percent,
                "full_duration": full_duration,
            }
        
        except Exception as e:
            print(f"[SyncTab] Coverage report failed: {e}")
            return None

    def get_full_coverage_timeline(self) -> Optional[Dict]:
        """
        Get a timeline view of all cameras' coverage.
        Useful for UI preview: shows which cameras are available at each time.
        """
        if not self.mapper:
            return None
        
        try:
            # Get total duration
            max_end = 0.0
            for clip in self.parser.video_clips:
                max_end = max(max_end, clip.timeline_end)
            
            # Sample at 1-second intervals
            timeline = {}
            step = 1.0
            t = 0.0
            
            while t <= max_end:
                available = []
                for camera in self.offsets.keys():
                    if self.mapper.has_coverage_at(camera, t):
                        available.append(camera)
                
                if available:
                    timeline[t] = available
                
                t += step
            
            return {
                "total_duration": max_end,
                "timeline": timeline,
                "sample_interval": step,
            }
        
        except Exception as e:
            print(f"[SyncTab] Timeline failed: {e}")
            return None

    # =========================================================================
    # Audio Selection
    # =========================================================================

    def set_sync_audio_track(self, audio_name: str) -> bool:
        """Set which audio track to use as sync reference."""
        try:
            if not self.parser:
                return False
            
            # Verify it exists
            if not any(a.name == audio_name for a in self.parser.audio_clips):
                print(f"[SyncTab] Audio track not found: {audio_name}")
                return False
            
            self.sync_audio_name = audio_name
            print(f"[SyncTab] Sync audio set to: {audio_name}")
            return True
        
        except Exception as e:
            print(f"[SyncTab] Failed to set sync audio: {e}")
            return False

    def get_available_audio_tracks(self) -> List[str]:
        """List all audio tracks in the imported XMEML."""
        if not self.parser:
            return []
        
        return [clip.name for clip in self.parser.audio_clips]

    # =========================================================================
    # Validation & Confirmation
    # =========================================================================

    def validate_sync(self) -> Tuple[bool, List[str]]:
        """
        Validate sync before proceeding to Audio tab.
        
        Checks:
        - All cameras have offsets
        - No excessive offsets (> 1 hour)
        - Coverage doesn't have extreme gaps (warns if gap > 10 min)
        - Audio is set
        
        Returns:
          (valid, warnings)
        """
        warnings = []
        
        if not self.mapper:
            return False, ["ClipMapper not built. Run auto_compute_offsets() or set manual offsets."]
        
        # Check offsets
        for cam, offset in self.offsets.items():
            if abs(offset) > 3600:
                warnings.append(f"{cam}: offset is {offset}s (> 1 hour) — verify this is correct")
        
        # Check coverage gaps
        for cam in self.offsets.keys():
            gaps = self.mapper.list_gaps(cam)
            for gap_start, gap_end in gaps:
                gap_duration = gap_end - gap_start
                if gap_duration > 600:  # 10 minutes
                    warnings.append(
                        f"{cam}: gap of {gap_duration:.0f}s ({gap_duration/60:.1f} min) "
                        f"at {gap_start:.0f}s — check if intentional"
                    )
        
        # Check audio
        if not self.sync_audio_name:
            warnings.append("No sync audio track selected")
        
        valid = len(warnings) == 0
        return valid, warnings

    def confirm_sync(self) -> Tuple[bool, str]:
        """
        Finalize sync and prepare to move to Audio tab.
        
        This commits the mapper and offsets to the project state.
        """
        try:
            valid, warnings = self.validate_sync()
            
            if not valid and not all(w.startswith("No sync audio") for w in warnings):
                # Allow proceeding with warnings, but not if core structure is missing
                pass
            
            if not self.mapper:
                return False, "ClipMapper not initialized"
            
            # Store mapper in project for use by later tabs
            self.project.clip_mapper = self.mapper
            self.project.sync_offsets = self.offsets
            self.project.sync_audio_name = self.sync_audio_name
            
            msg = f"Sync confirmed: {len(self.offsets)} cameras, audio: {self.sync_audio_name}"
            return True, msg
        
        except Exception as e:
            return False, f"Sync confirmation failed: {e}"

    # =========================================================================
    # Diagnostics
    # =========================================================================

    def export_sync_report(self, output_path: str) -> bool:
        """Export sync report as JSON for debugging."""
        import json
        
        try:
            report = {
                "offsets": self.offsets,
                "sync_audio": self.sync_audio_name,
                "xmeml_parsed": self.parser is not None,
            }
            
            if self.mapper:
                report["coverage"] = {}
                for cam in self.offsets.keys():
                    coverage = self.get_coverage_report(cam)
                    if coverage:
                        report["coverage"][cam] = coverage
            
            with open(output_path, "w") as f:
                json.dump(report, f, indent=2)
            
            print(f"[SyncTab] Sync report exported to {output_path}")
            return True
        
        except Exception as e:
            print(f"[SyncTab] Export failed: {e}")
            return False

    def get_diagnostics(self) -> Dict:
        """Return diagnostics for troubleshooting."""
        return {
            "parser_loaded": self.parser is not None,
            "video_clips_count": len(self.parser.video_clips) if self.parser else 0,
            "audio_clips_count": len(self.parser.audio_clips) if self.parser else 0,
            "offsets": self.offsets,
            "mapper_built": self.mapper is not None,
            "sync_audio": self.sync_audio_name,
        }

"""Intake Tab: Load cameras, audio, and project settings (Section 6.1)."""

import os
from typing import List, Optional, Callable
from pathlib import Path
from dataclasses import dataclass
from enum import Enum
import json

from models.project import (
    ProjectState,
    ProjectSettings,
    Camera,
    AudioSource,
    VideoClip,
    CameraRole,
    AudioType,
    AudioChannelFormat,
)


@dataclass
class FileImportResult:
    """Result of importing a file or folder."""
    success: bool
    file_count: int
    cameras_added: List[str]
    audio_added: List[str]
    errors: List[str]


class IntakeTab:
    """
    Intake Tab: Load footage and audio files into the project.
    
    Workflow:
    1. Select footage folder(s) — auto-organize into cameras
    2. Tag each camera role (wide/booth/roaming/audience)
    3. Select audio files (clean mix, ambient, wireless feeds)
    4. Tag audio type (clean/ambient/wireless)
    5. Set project frame rate, resolution
    
    Section 6.1: "Make it hard to screw up. Offer presets. Auto-group files
    by creation timestamp or naming convention. Clear labeling."
    """

    # Common video extensions
    VIDEO_EXTENSIONS = {".mov", ".mp4", ".mxf", ".avi", ".mkv"}
    AUDIO_EXTENSIONS = {".wav", ".aiff", ".mp3", ".aac", ".m4a"}

    def __init__(self, project: ProjectState):
        self.project = project
        self.pending_cameras: List[Camera] = []
        self.pending_audio: List[AudioSource] = []

    def import_footage_folder(
        self,
        folder_path: str,
        auto_group_by_timestamp: bool = True,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> FileImportResult:
        """
        Import all video files from a folder.
        
        Auto-groups files by:
        - Creation timestamp (if timestamps are close, group as one camera)
        - Naming convention (if filename contains camera name, use it)
        
        Args:
          folder_path: path to footage directory
          auto_group_by_timestamp: group files with similar timestamps
          progress_callback: called with status messages
        
        Returns:
          FileImportResult with counts and errors
        """
        result = FileImportResult(
            success=True,
            file_count=0,
            cameras_added=[],
            audio_added=[],
            errors=[],
        )
        
        try:
            folder = Path(folder_path)
            if not folder.is_dir():
                result.errors.append(f"Not a directory: {folder_path}")
                result.success = False
                return result
            
            # Find all video files
            video_files = []
            for ext in self.VIDEO_EXTENSIONS:
                video_files.extend(folder.glob(f"**/*{ext}"))
                video_files.extend(folder.glob(f"**/*{ext.upper()}"))
            
            if not video_files:
                result.errors.append(f"No video files found in {folder_path}")
                result.success = False
                return result
            
            result.file_count = len(video_files)
            
            # Group files into cameras
            if auto_group_by_timestamp:
                camera_groups = self._group_files_by_timestamp(video_files)
            else:
                camera_groups = self._group_files_by_naming(video_files)
            
            # Create Camera objects
            for group_name, file_list in camera_groups.items():
                if progress_callback:
                    progress_callback(f"Processing {group_name}...")
                
                try:
                    camera = self._create_camera_from_files(group_name, file_list)
                    self.pending_cameras.append(camera)
                    result.cameras_added.append(camera.name)
                except Exception as e:
                    result.errors.append(f"Failed to process {group_name}: {e}")
            
            result.success = len(result.errors) == 0
            return result
        
        except Exception as e:
            result.errors.append(f"Folder import failed: {e}")
            result.success = False
            return result

    def import_audio_file(
        self,
        file_path: str,
        audio_type: AudioType = AudioType.CLEAN,
        channel_format: AudioChannelFormat = AudioChannelFormat.STEREO,
        in_point: float = 0.0,
        out_point: Optional[float] = None,
    ) -> bool:
        """Import a single audio file."""
        try:
            file = Path(file_path)
            if not file.exists():
                print(f"[IntakeTab] Audio file not found: {file_path}")
                return False
            
            # Get duration (probe file)
            duration = self._probe_audio_duration(file_path)
            if duration is None:
                print(f"[IntakeTab] Could not determine duration: {file_path}")
                return False
            
            audio = AudioSource(
                name=file.stem,
                file_path=file_path,
                audio_type=audio_type,
                channel_format=channel_format,
                duration=duration,
                in_point=in_point,
                out_point=out_point or duration,
            )
            
            self.pending_audio.append(audio)
            print(f"[IntakeTab] Added audio: {audio.name}")
            return True
        
        except Exception as e:
            print(f"[IntakeTab] Failed to import audio {file_path}: {e}")
            return False

    def set_project_settings(
        self,
        frame_rate: float,
        resolution: tuple,
        project_name: str,
    ) -> bool:
        """Set project frame rate, resolution, and name."""
        try:
            self.project.settings.frame_rate = frame_rate
            self.project.settings.native_resolution = resolution
            self.project.settings.project_name = project_name
            print(f"[IntakeTab] Project settings updated: {project_name}, {resolution} @ {frame_rate} fps")
            return True
        except Exception as e:
            print(f"[IntakeTab] Failed to set project settings: {e}")
            return False

    def confirm_intake(self) -> bool:
        """
        Finalize intake: commit pending cameras and audio to the project.
        This transitions to the Sync tab.
        """
        try:
            self.project.cameras.extend(self.pending_cameras)
            self.project.audio_sources.extend(self.pending_audio)
            
            print(f"[IntakeTab] Confirmed: {len(self.pending_cameras)} cameras, {len(self.pending_audio)} audio sources")
            self.pending_cameras.clear()
            self.pending_audio.clear()
            return True
        
        except Exception as e:
            print(f"[IntakeTab] Confirm intake failed: {e}")
            return False

    # =========================================================================
    # Private Methods
    # =========================================================================

    def _group_files_by_timestamp(self, files: List[Path]) -> dict:
        """
        Group video files by creation timestamp.
        Files within ~5 minutes of each other are assumed to be from the same camera.
        """
        import time
        
        groups = {}
        file_times = []
        
        # Get timestamps
        for f in files:
            try:
                mtime = os.path.getmtime(f)
                file_times.append((mtime, f))
            except Exception as e:
                print(f"[IntakeTab] Could not get mtime for {f}: {e}")
        
        # Sort by time
        file_times.sort(key=lambda x: x[0])
        
        # Group: if gap > 5 min (300 sec), start new group
        current_group = []
        current_time = None
        
        for mtime, fpath in file_times:
            if current_time is None or (mtime - current_time) < 300:
                current_group.append(fpath)
                current_time = mtime
            else:
                # Save current group and start new
                if current_group:
                    group_name = f"Camera_{len(groups) + 1}"
                    groups[group_name] = current_group
                current_group = [fpath]
                current_time = mtime
        
        # Final group
        if current_group:
            group_name = f"Camera_{len(groups) + 1}"
            groups[group_name] = current_group
        
        return groups

    def _group_files_by_naming(self, files: List[Path]) -> dict:
        """
        Group video files by naming convention.
        E.g., "cam_a_001.mov", "cam_a_002.mov" → Camera A
        """
        groups = {}
        
        for f in files:
            # Extract camera name from filename
            # Simple heuristic: split by underscore, take first part
            parts = f.stem.lower().split("_")
            if len(parts) > 0:
                cam_name = parts[0].capitalize()
            else:
                cam_name = "Unknown"
            
            if cam_name not in groups:
                groups[cam_name] = []
            groups[cam_name].append(f)
        
        return groups

    def _create_camera_from_files(self, camera_name: str, file_list: List[Path]) -> Camera:
        """
        Create a Camera object from a list of video files.
        Probes each file for duration, frame rate, resolution.
        """
        clips = []
        
        for fpath in file_list:
            try:
                duration = self._probe_video_duration(str(fpath))
                fps = self._probe_frame_rate(str(fpath))
                resolution = self._probe_resolution(str(fpath))
                creation_time = os.path.getmtime(fpath)
                
                clip = VideoClip(
                    file_path=str(fpath),
                    duration=duration,
                    frame_rate=fps,
                    resolution=resolution,
                    creation_timestamp=creation_time,
                )
                clips.append(clip)
            
            except Exception as e:
                print(f"[IntakeTab] Failed to probe {fpath}: {e}")
        
        camera = Camera(
            name=camera_name,
            role=CameraRole.ROAMING,  # Default; user will adjust in UI
            clips=clips,
        )
        
        return camera

    def _probe_video_duration(self, file_path: str) -> float:
        """Use ffprobe to get video duration."""
        import subprocess
        import json
        
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "json",
                    file_path,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                duration = float(data["format"]["duration"])
                return duration
        except Exception as e:
            print(f"[IntakeTab] ffprobe failed for {file_path}: {e}")
        
        return 0.0

    def _probe_frame_rate(self, file_path: str) -> float:
        """Probe frame rate from video file."""
        import subprocess
        import json
        
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=r_frame_rate",
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
                    r_frame_rate = data["streams"][0].get("r_frame_rate")
                    if r_frame_rate:
                        # Format is "30/1" or "24000/1001"
                        num, denom = map(int, r_frame_rate.split("/"))
                        return num / denom
        except Exception as e:
            print(f"[IntakeTab] Frame rate probe failed: {e}")
        
        return 25.0  # Default

    def _probe_resolution(self, file_path: str) -> tuple:
        """Probe resolution from video file."""
        import subprocess
        import json
        
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
                    w = data["streams"][0].get("width")
                    h = data["streams"][0].get("height")
                    if w and h:
                        return (w, h)
        except Exception as e:
            print(f"[IntakeTab] Resolution probe failed: {e}")
        
        return (1920, 1080)  # Default

    def _probe_audio_duration(self, file_path: str) -> Optional[float]:
        """Probe audio duration."""
        import subprocess
        import json
        
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "json",
                    file_path,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                duration = float(data["format"]["duration"])
                return duration
        except Exception as e:
            print(f"[IntakeTab] Audio probe failed: {e}")
        
        return None

    def get_camera_role_presets(self) -> dict:
        """
        Return preset camera roles with descriptions.
        Section 6.1: "Offer presets."
        """
        return {
            "Wide Shot": {
                "role": CameraRole.WIDE,
                "description": "Full stage or venue view. Used during buildups and breakdowns.",
            },
            "Booth (Close-up)": {
                "role": CameraRole.BOOTH_CLOSEUP,
                "description": "DJ booth close-up. Hands, decks, face detail.",
            },
            "Booth (Full)": {
                "role": CameraRole.BOOTH_FULL,
                "description": "DJ booth full shot. Equipment and performer.",
            },
            "Roaming": {
                "role": CameraRole.ROAMING,
                "description": "Handheld or gimbal. Moves through crowd or venue.",
            },
            "Audience": {
                "role": CameraRole.AUDIENCE,
                "description": "Crowd reactions and dancing.",
            },
        }

    def get_audio_type_presets(self) -> dict:
        """Return audio type presets."""
        return {
            "Clean Mix": {
                "type": AudioType.CLEAN,
                "description": "Main stereo mixdown. Primary audio source.",
            },
            "Ambient": {
                "type": AudioType.AMBIENT,
                "description": "Room ambience, crowd noise.",
            },
            "Wireless Mic": {
                "type": AudioType.WIRELESS,
                "description": "Wireless microphone feed (DJ, emcee, etc.).",
            },
        }

    def get_project_frame_rate_presets(self) -> List[float]:
        """Common frame rates."""
        return [23.976, 24.0, 25.0, 29.97, 30.0, 50.0, 59.94, 60.0]

    def get_project_resolution_presets(self) -> dict:
        """Common resolutions."""
        return {
            "HD (720p)": (1280, 720),
            "Full HD (1080p)": (1920, 1080),
            "4K (UHD)": (3840, 2160),
            "DCI 4K": (4096, 2160),
        }

    def export_intake_state(self, output_path: str) -> bool:
        """
        Export intake state as JSON for backup/version control.
        """
        try:
            state = {
                "project_name": self.project.settings.project_name,
                "frame_rate": self.project.settings.frame_rate,
                "resolution": self.project.settings.native_resolution,
                "cameras": [
                    {
                        "name": cam.name,
                        "role": cam.role.value if cam.role else "roaming",
                        "clip_count": len(cam.clips),
                        "total_duration": sum(c.duration for c in cam.clips),
                    }
                    for cam in self.project.cameras
                ],
                "audio_sources": [
                    {
                        "name": src.name,
                        "type": src.audio_type.value,
                        "duration": src.duration,
                        "sample_rate": src.sample_rate,
                    }
                    for src in self.project.audio_sources
                ],
            }
            
            with open(output_path, "w") as f:
                json.dump(state, f, indent=2)
            
            print(f"[IntakeTab] Exported intake state to {output_path}")
            return True
        
        except Exception as e:
            print(f"[IntakeTab] Export failed: {e}")
            return False

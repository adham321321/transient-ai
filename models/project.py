"""Data models for project state, cameras, audio sources, and sync."""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from enum import Enum
import json


class CameraRole(str, Enum):
    """Camera role for bias weighting during multicam cut."""
    ROAMING = "roaming"
    BOOTH_FULL = "booth-full"
    WIDE = "wide"
    CUSTOM = "custom"


class AudioType(str, Enum):
    """Audio feed type classification."""
    CLEAN = "clean"
    AMBIENT = "ambient"


class AudioChannelFormat(str, Enum):
    """Audio channel configuration."""
    STEREO = "stereo"
    MONO = "mono"


@dataclass
class VideoClip:
    """A single video file belonging to a camera."""
    file_path: str
    duration: float  # seconds
    frame_rate: float  # fps
    resolution: Tuple[int, int]  # (width, height)
    creation_timestamp: Optional[float] = None  # embedded timestamp if available
    in_point: float = 0.0  # trim in (seconds)
    out_point: Optional[float] = None  # trim out; None = to end

    def get_duration(self) -> float:
        """Effective duration after trimming."""
        end = self.out_point if self.out_point is not None else self.duration
        return end - self.in_point


@dataclass
class Camera:
    """A named camera/source with ordered list of clips."""
    name: str
    role: CameraRole = CameraRole.ROAMING
    clips: List[VideoClip] = field(default_factory=list)
    custom_role_label: Optional[str] = None  # user-typed custom role

    def total_duration(self) -> float:
        """Sum of all clip durations (after trim)."""
        return sum(clip.get_duration() for clip in self.clips)

    def get_coverage_at(self, timeline_seconds: float) -> Optional[VideoClip]:
        """Find the clip covering a given timeline position. None if gap."""
        # Clips are assumed to be placed sequentially on timeline
        current_pos = 0.0
        for clip in self.clips:
            clip_duration = clip.get_duration()
            if current_pos <= timeline_seconds < current_pos + clip_duration:
                return clip
            current_pos += clip_duration
        return None


@dataclass
class AudioSource:
    """An audio input feed (line feed, room mic, etc.)."""
    name: str
    file_path: str
    description: str  # e.g. "line feed · 4 takes"
    audio_type: AudioType = AudioType.CLEAN
    channel_format: AudioChannelFormat = AudioChannelFormat.STEREO
    duration: float = 0.0  # seconds
    sample_rate: int = 48000
    timeline_slot: Optional[str] = None  # e.g. "A1", "A2"
    in_point: float = 0.0  # file offset where timeline should start
    out_point: Optional[float] = None  # file offset where timeline should end; None = to EOF

    def get_duration(self) -> float:
        """Effective duration on timeline."""
        end = self.out_point if self.out_point is not None else self.duration
        return end - self.in_point


@dataclass
class ProjectSettings:
    """Global project metadata and settings."""
    project_name: str
    native_resolution: Tuple[int, int]  # (width, height)
    frame_rate: float  # fps
    target_bpm: Optional[float] = None
    peak_threshold: float = 0.55  # 0–1, for drop detection
    sync_scratch_audio_idx: int = 0  # which audio source to sync to
    correct_latency: bool = True


@dataclass
class PremixConfig:
    """Audio premix settings."""
    mode: str = "Loudness · stems"  # e.g. "Loudness · stems"
    target_lufs: float = -14.0
    crowd_level: float = 5.0  # 0–10
    
    # EQ/processing toggles (name -> (enabled, amount))
    processing: Dict[str, Tuple[bool, float]] = field(default_factory=lambda: {
        "Ambient HP": (False, 24.0),
        "Ambient brightness": (False, 0.5),
        "Crowd boost": (False, 0.5),
    })


@dataclass
class CutConfig:
    """Multicam cut engine parameters."""
    target_bpm: float
    peak_threshold: float = 0.55
    drop_pace: float = 4.0  # beats per cut
    calm_pace: float = 8.0
    randomness: float = 0.3  # 0–1
    min_shot_duration: float = 0.5  # seconds
    max_shot_duration: float = 4.0
    seed: Optional[int] = None  # for reproducibility
    section_sensitivity: float = 0.7  # 0–1, for intro/build/drop detection
    
    # Camera weights: camera_name -> weight (0–2.0, default 1.0)
    camera_weights: Dict[str, float] = field(default_factory=dict)


@dataclass
class ProjectState:
    """Complete project state: settings, cameras, audio, cuts, sync."""
    settings: ProjectSettings
    cameras: List[Camera] = field(default_factory=list)
    audio_sources: List[AudioSource] = field(default_factory=list)
    premix_config: PremixConfig = field(default_factory=PremixConfig)
    cut_config: CutConfig = field(default_factory=lambda: CutConfig(target_bpm=128.0))
    
    # Sync map: camera_name -> offset_in_seconds (relative to sync reference audio)
    sync_offsets: Dict[str, float] = field(default_factory=dict)
    
    # Moments: named cut points (from Analysis tab)
    moments: List[Dict] = field(default_factory=list)  # {name, timecode, bars_in, bars_out, in_trim, out_trim}
    
    # Generated cuts (from Cut tab)
    generated_cuts: Optional[List[Dict]] = None  # {start, end, camera, confidence}
    
    # Export settings
    export_aspect_ratios: List[str] = field(default_factory=lambda: ["16:9"])
    export_credit: str = ""
    export_start_number: int = 1
    export_gaps_mode: str = "leave black"  # or "ripple delete"

    def get_camera(self, name: str) -> Optional[Camera]:
        """Lookup camera by name."""
        for cam in self.cameras:
            if cam.name == name:
                return cam
        return None

    def get_audio_source(self, name: str) -> Optional[AudioSource]:
        """Lookup audio source by name."""
        for src in self.audio_sources:
            if src.name == name:
                return src
        return None

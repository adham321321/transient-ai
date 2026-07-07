"""Multicam edit engine: rule-based cut generation with camera weighting (Section 4.4)."""

import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import random


class SectionType(str, Enum):
    """Musical section classification."""
    INTRO = "intro"
    BUILDUP = "buildup"
    DROP = "drop"
    PEAK = "peak"
    BREAKDOWN = "breakdown"
    OUTRO = "outro"


@dataclass
class Cut:
    """A single cut in the multicam sequence."""
    start: float  # timeline seconds
    end: float
    duration: float
    camera: str
    section_type: SectionType
    confidence: float  # 0–1, how confident the engine is in this choice


@dataclass
class ShotStatistics:
    """Learned statistics from a user's past cuts."""
    avg_duration: float  # seconds
    duration_std: float
    camera_frequency: Dict[str, float]  # camera -> proportion (0–1)
    transition_matrix: Dict[Tuple[str, str], float]  # (cam_from, cam_to) -> frequency
    cut_pace_by_section: Dict[SectionType, float]  # section -> beats per cut


class MulticamEditEngine:
    """
    Rule-based multicam edit generation.
    Section 4.4: cut frequency, randomness, drop/calm pace, per-camera weight,
    section-aware bias, visual repetition avoidance.
    """

    def __init__(self, audio_analyzer, clip_mapper, project_state):
        """
        Initialize with:
          - audio_analyzer: AudioAnalyzer with beat grid, sections, energy
          - clip_mapper: ClipMapper for coverage queries
          - project_state: ProjectState with CutConfig, cameras
        """
        self.audio = audio_analyzer
        self.mapper = clip_mapper
        self.project = project_state
        self.config = project_state.cut_config
        
        # Cache section classifications
        self._sections = None
        self._beat_grid = None

    def set_seed(self, seed: Optional[int]):
        """Set random seed for reproducible cuts."""
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)

    def _classify_sections(self) -> Dict[float, SectionType]:
        """
        Classify timeline into sections (intro/buildup/drop/etc).
        Returns dict: timeline_seconds -> SectionType
        """
        if self._sections is not None:
            return self._sections
        
        try:
            sections_data = self.audio.detect_sections(self.config.section_sensitivity)
            if not sections_data:
                return {}
            
            # Create timeline classification
            classification = {}
            total_time = self.audio.y.shape[0] / self.audio.sr if self.audio.y is not None else 300.0
            
            # Assign each second a section type based on heuristic
            for t in np.arange(0, total_time, 1.0):
                # Simplistic: find nearest drop marker
                drops = sections_data.get("drop", [])
                if drops:
                    nearest_drop = min(drops, key=lambda d: abs(d - t))
                    if abs(nearest_drop - t) < 10:  # Within 10 sec of drop
                        classification[t] = SectionType.DROP
                    else:
                        classification[t] = SectionType.BUILDUP
                else:
                    classification[t] = SectionType.BUILDUP
            
            self._sections = classification
            return classification
        
        except Exception as e:
            print(f"[MulticamEditEngine] Section classification failed: {e}")
            return {}

    def _get_beat_grid(self) -> Optional[np.ndarray]:
        """Get or compute beat grid."""
        if self._beat_grid is not None:
            return self._beat_grid
        
        try:
            self._beat_grid = self.audio.get_beat_grid(self.config.target_bpm)
            return self._beat_grid
        except Exception as e:
            print(f"[MulticamEditEngine] Beat grid fetch failed: {e}")
            return None

    def _get_section_at(self, timeline_seconds: float) -> SectionType:
        """Classify section for a specific timeline position."""
        sections = self._classify_sections()
        # Find nearest section marker
        if not sections:
            return SectionType.BUILDUP
        
        closest_t = min(sections.keys(), key=lambda t: abs(t - timeline_seconds))
        if abs(closest_t - timeline_seconds) < 5.0:
            return sections[closest_t]
        return SectionType.BUILDUP

    def _get_beat_duration(self, section: SectionType) -> float:
        """
        Get beats per cut for a section.
        Returns duration in seconds for one "beat duration" at the given pace.
        """
        beat_duration = 60.0 / self.config.target_bpm  # seconds per beat
        
        if section == SectionType.DROP:
            beats = self.config.drop_pace
        else:
            beats = self.config.calm_pace
        
        return beat_duration * beats

    def _choose_camera(
        self,
        timeline_seconds: float,
        available_cameras: List[str],
        last_camera: Optional[str] = None,
        avoid_cameras: Optional[set] = None,
    ) -> Optional[str]:
        """
        Choose which camera to show at this point.
        
        Logic:
        1. Filter to cameras with actual coverage
        2. Apply section bias (drops → close-ups, breakdowns → wides)
        3. Apply user weights
        4. Penalize last camera (1–2 cuts back)
        5. Humanize with randomness
        
        Returns camera name or None if no coverage available.
        """
        if avoid_cameras is None:
            avoid_cameras = set()
        
        # Check coverage
        candidates = []
        for cam in available_cameras:
            if self.mapper.has_coverage_at(cam, timeline_seconds):
                candidates.append(cam)
        
        if not candidates:
            return None
        
        # Apply weights
        weighted_scores = {}
        section = self._get_section_at(timeline_seconds)
        
        for cam in candidates:
            score = 1.0
            
            # User-defined weight
            weight = self.config.camera_weights.get(cam, 1.0)
            score *= weight
            
            # Section bias
            cam_role = self.project.get_camera(cam).role if self.project.get_camera(cam) else None
            if section == SectionType.DROP:
                # Favor close-ups on drops
                if cam_role and "booth" in str(cam_role):
                    score *= 1.5
                elif cam_role and "wide" in str(cam_role):
                    score *= 0.7
            elif section in [SectionType.BREAKDOWN, SectionType.BUILDUP]:
                # Favor wides on breakdowns
                if cam_role and "wide" in str(cam_role):
                    score *= 1.5
                elif cam_role and "booth" in str(cam_role):
                    score *= 0.7
            
            # Penalize recent camera
            if cam == last_camera:
                score *= 0.3
            elif cam in avoid_cameras:
                score *= 0.5
            
            weighted_scores[cam] = score
        
        # Humanize with randomness
        if self.config.randomness > 0:
            # Add jitter to scores
            for cam in weighted_scores:
                jitter = np.random.normal(0, self.config.randomness)
                weighted_scores[cam] *= (1.0 + jitter)
        
        # Choose
        best_cam = max(weighted_scores, key=weighted_scores.get)
        return best_cam

    def generate_cuts(
        self,
        timeline_duration: float,
        moments: Optional[List[Dict]] = None,
    ) -> Tuple[List[Cut], float]:
        """
        Generate multicam cuts for the timeline.
        
        Args:
          timeline_duration: total seconds to cover
          moments: if provided, only cut the named moments (from Analysis tab)
        
        Returns:
          (list of Cut objects, actual duration covered in seconds)
          
        Section 4.4: "When a chosen camera's real coverage ends before a cut's
        planned duration, stop or split — never substitute."
        "If NO camera has coverage at some point, stop generating further cuts
        there and clearly report how far the edit actually got."
        """
        cuts = []
        self.set_seed(self.config.seed)
        
        # Determine what to cut
        if moments:
            time_ranges = [(m["start"], m["end"]) for m in moments]
        else:
            time_ranges = [(0.0, timeline_duration)]
        
        available_cameras = [cam.name for cam in self.project.cameras]
        if not available_cameras:
            print("[MulticamEditEngine] No cameras available")
            return [], 0.0
        
        last_camera = None
        recent_cameras = set()  # Cameras used in last 2 cuts
        actual_coverage = 0.0
        
        for range_start, range_end in time_ranges:
            current_time = range_start
            
            while current_time < range_end:
                section = self._get_section_at(current_time)
                beat_duration = self._get_beat_duration(section)
                
                # Planned cut duration
                planned_end = current_time + beat_duration
                
                # Clamp to range
                cut_end = min(planned_end, range_end)
                
                # Choose camera
                chosen_camera = self._choose_camera(
                    current_time,
                    available_cameras,
                    last_camera=last_camera,
                    avoid_cameras=recent_cameras,
                )
                
                if chosen_camera is None:
                    # No coverage at this point
                    print(f"[MulticamEditEngine] No coverage at {current_time:.2f}s, stopping")
                    break
                
                # Check if chosen camera can cover the planned duration
                coverage_end = cut_end
                while coverage_end > current_time and not self.mapper.has_coverage_at(chosen_camera, coverage_end - 0.1):
                    coverage_end -= 0.1
                
                if coverage_end <= current_time:
                    # Camera's coverage ends before cut can start
                    print(f"[MulticamEditEngine] Camera {chosen_camera} coverage gap at {current_time:.2f}s, stopping")
                    break
                
                # Clamp cut to actual coverage
                cut_end = min(cut_end, coverage_end)
                
                # Enforce min/max duration
                cut_duration = cut_end - current_time
                if cut_duration < self.config.min_shot_duration:
                    current_time = cut_end
                    continue
                
                cut_duration = min(cut_duration, self.config.max_shot_duration)
                cut_end = current_time + cut_duration
                
                # Create cut
                cut = Cut(
                    start=current_time,
                    end=cut_end,
                    duration=cut_duration,
                    camera=chosen_camera,
                    section_type=section,
                    confidence=0.8,  # Default; could be refined
                )
                cuts.append(cut)
                
                actual_coverage = cut_end
                last_camera = chosen_camera
                recent_cameras.add(chosen_camera)
                if len(recent_cameras) > 2:
                    recent_cameras.pop()
                
                current_time = cut_end
        
        return cuts, actual_coverage

    def learn_from_cuts(self, cut_sequence: List[Dict]) -> ShotStatistics:
        """
        Ingest a user's past cut export and learn shot statistics.
        Section 4.4: Learn shot duration, camera frequency, transitions, pacing.
        
        Args:
          cut_sequence: list of {start, end, camera, section}
        
        Returns:
          ShotStatistics object that can be used as a preset
        """
        if not cut_sequence:
            return ShotStatistics(
                avg_duration=2.0,
                duration_std=0.5,
                camera_frequency={},
                transition_matrix={},
                cut_pace_by_section={},
            )
        
        try:
            # Duration statistics
            durations = [c["end"] - c["start"] for c in cut_sequence]
            avg_dur = np.mean(durations)
            std_dur = np.std(durations)
            
            # Camera frequency
            cameras = [c["camera"] for c in cut_sequence]
            camera_freq = {}
            for cam in set(cameras):
                camera_freq[cam] = cameras.count(cam) / len(cameras)
            
            # Transition matrix
            transitions = {}
            for i in range(len(cut_sequence) - 1):
                from_cam = cut_sequence[i]["camera"]
                to_cam = cut_sequence[i + 1]["camera"]
                key = (from_cam, to_cam)
                transitions[key] = transitions.get(key, 0) + 1
            
            # Normalize transitions
            for key in transitions:
                transitions[key] /= len(cut_sequence)
            
            # Pacing by section
            pacing = {}
            for section in SectionType:
                section_cuts = [c for c in cut_sequence if c.get("section") == section]
                if section_cuts:
                    avg_pace = np.mean([c["end"] - c["start"] for c in section_cuts])
                    pacing[section] = avg_pace
            
            return ShotStatistics(
                avg_duration=float(avg_dur),
                duration_std=float(std_dur),
                camera_frequency=camera_freq,
                transition_matrix=transitions,
                cut_pace_by_section=pacing,
            )
        
        except Exception as e:
            print(f"[MulticamEditEngine] Error learning from cuts: {e}")
            return ShotStatistics(
                avg_duration=2.0,
                duration_std=0.5,
                camera_frequency={},
                transition_matrix={},
                cut_pace_by_section={},
            )

    def apply_learned_preset(self, stats: ShotStatistics):
        """
        Apply learned statistics as a preset, filling in slider defaults.
        Section 4.4: "offer that back as a style preset that biases the sliders
        above — never override manual slider values, only pre-fill them."
        """
        # Pre-fill only if user hasn't manually set these
        if self.config.min_shot_duration == 0.5:  # Default
            self.config.min_shot_duration = max(0.3, stats.avg_duration - stats.duration_std)
        
        if self.config.max_shot_duration == 4.0:  # Default
            self.config.max_shot_duration = stats.avg_duration + stats.duration_std
        
        # Pre-fill camera weights from learned frequency
        for cam, freq in stats.camera_frequency.items():
            if cam not in self.config.camera_weights or self.config.camera_weights[cam] == 1.0:
                # Map frequency to weight (0.5 – 2.0 range)
                weight = 0.5 + (freq * 3.0)
                self.config.camera_weights[cam] = min(2.0, max(0.5, weight))

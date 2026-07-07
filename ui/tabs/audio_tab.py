"""Audio Tab: Premix, analyze, section detection (Section 6.3)."""

from typing import List, Optional, Dict, Tuple
from enum import Enum
from dataclasses import dataclass
import os

from models.project import ProjectState, AudioSource, AudioType
from engine.audio_analysis import (
    AudioAnalyzer,
    BeatDetector,
    EnergyDetector,
    SilenceDetector,
    DropDetector,
)


@dataclass
class AnalysisResult:
    """Result of audio analysis."""
    audio_name: str
    beats: List[float]  # Timecodes (seconds) of detected beats
    energy_envelope: Dict[str, float]  # Time -> energy level
    silence_regions: List[Tuple[float, float]]  # Silence (start, end)
    drops: List[Tuple[float, float]]  # Drop regions
    bpm: float
    confidence: float


class AudioTab:
    """
    Audio Tab: Analyze the sync audio for beats, energy, and sections.
    
    Workflow:
    1. Select which audio track to analyze (usually clean mix)
    2. Configure analysis settings (sensitivity, min beat interval, etc.)
    3. Run analysis (beat detection, energy curve, silence detection)
    4. Mark sections: intro, buildup, drop, breakdown, outro
    5. Optionally: extract/remix isolated stems (if available)
    6. Confirm and prepare for Cut tab
    
    Section 6.3: "Audio analysis should be fast (< 10 sec for 90 min).
    Mark natural section boundaries. Offer visual waveform preview."
    """

    def __init__(self, project: ProjectState, clip_mapper=None):
        self.project = project
        self.clip_mapper = clip_mapper
        self.analyzer = AudioAnalyzer()
        self.beat_detector = BeatDetector()
        self.energy_detector = EnergyDetector()
        self.silence_detector = SilenceDetector()
        self.drop_detector = DropDetector()
        
        self.analysis_results: Dict[str, AnalysisResult] = {}
        self.sections: List[Dict] = []  # User-defined sections

    # =========================================================================
    # Analysis Configuration
    # =========================================================================

    def configure_analysis(
        self,
        beat_min_interval: float = 0.2,  # seconds (min distance between beats)
        energy_smoothing: float = 0.5,  # 0-1 (higher = smoother envelope)
        silence_threshold: float = -40.0,  # dB
        drop_threshold: float = -15.0,  # dB drop needed to trigger
    ) -> bool:
        """Configure analysis parameters."""
        try:
            self.beat_detector.min_beat_interval = beat_min_interval
            self.energy_detector.smoothing_factor = energy_smoothing
            self.silence_detector.threshold_db = silence_threshold
            self.drop_detector.threshold_db = drop_threshold
            
            print(
                f"[AudioTab] Analysis configured: "
                f"beat_interval={beat_min_interval}s, "
                f"energy_smoothing={energy_smoothing}, "
                f"silence={silence_threshold}dB, "
                f"drop={drop_threshold}dB"
            )
            return True
        except Exception as e:
            print(f"[AudioTab] Configuration failed: {e}")
            return False

    # =========================================================================
    # Analysis Execution
    # =========================================================================

    def analyze_audio_track(self, audio_name: str) -> Tuple[bool, str]:
        """
        Analyze a single audio track.
        
        Detects:
        - Beats (BPM, individual beat timecodes)
        - Energy envelope (dynamic range, peaks)
        - Silence regions
        - Drops/breakdowns
        
        Returns:
          (success, message)
        """
        try:
            # Find audio source
            audio_source = None
            for src in self.project.audio_sources:
                if src.name == audio_name:
                    audio_source = src
                    break
            
            if not audio_source:
                return False, f"Audio source not found: {audio_name}"
            
            print(f"[AudioTab] Analyzing {audio_name} ({audio_source.duration:.1f}s)...")
            
            # Run beat detection
            beats = self.beat_detector.detect(audio_source.file_path)
            bpm = self.beat_detector.estimate_bpm(beats)
            confidence = self.beat_detector.confidence
            
            print(f"[AudioTab] Detected {len(beats)} beats, BPM={bpm:.1f} (conf={confidence:.2f})")
            
            # Run energy analysis
            energy_envelope = self.energy_detector.compute_envelope(audio_source.file_path)
            print(f"[AudioTab] Computed energy envelope ({len(energy_envelope)} samples)")
            
            # Run silence detection
            silence_regions = self.silence_detector.detect(audio_source.file_path)
            print(f"[AudioTab] Found {len(silence_regions)} silence regions")
            
            # Run drop detection
            drops = self.drop_detector.detect(audio_source.file_path, energy_envelope)
            print(f"[AudioTab] Found {len(drops)} drops/breakdowns")
            
            # Store result
            result = AnalysisResult(
                audio_name=audio_name,
                beats=beats,
                energy_envelope=energy_envelope,
                silence_regions=silence_regions,
                drops=drops,
                bpm=bpm,
                confidence=confidence,
            )
            self.analysis_results[audio_name] = result
            
            msg = (
                f"Analysis complete: {len(beats)} beats @ {bpm:.1f} BPM, "
                f"{len(drops)} drops, {len(silence_regions)} silences"
            )
            return True, msg
        
        except Exception as e:
            return False, f"Analysis failed: {e}"

    def analyze_all_audio(self) -> Tuple[int, List[str]]:
        """
        Analyze all audio tracks in the project.
        
        Returns:
          (success_count, error_messages)
        """
        success_count = 0
        errors = []
        
        for audio_source in self.project.audio_sources:
            success, msg = self.analyze_audio_track(audio_source.name)
            if success:
                success_count += 1
            else:
                errors.append(msg)
        
        print(f"[AudioTab] Analyzed {success_count}/{len(self.project.audio_sources)} tracks")
        return success_count, errors

    # =========================================================================
    # Results & Preview
    # =========================================================================

    def get_analysis_result(self, audio_name: str) -> Optional[AnalysisResult]:
        """Get stored analysis result for a track."""
        return self.analysis_results.get(audio_name)

    def get_beat_times(self, audio_name: str) -> List[float]:
        """Get list of beat timecodes (in seconds)."""
        result = self.analysis_results.get(audio_name)
        return result.beats if result else []

    def get_energy_curve(self, audio_name: str, sample_rate: float = 1.0) -> Dict[float, float]:
        """
        Get energy envelope sampled at specified rate.
        
        Args:
          audio_name: track to query
          sample_rate: samples per second (lower = smoother for UI)
        
        Returns:
          Dict: timecode -> energy level
        """
        result = self.analysis_results.get(audio_name)
        if not result:
            return {}
        
        # Simple downsampling
        env = result.energy_envelope
        if not env:
            return {}
        
        # Get original sample interval
        times = sorted(env.keys())
        if len(times) < 2:
            return env
        
        # Downsample by averaging
        resampled = {}
        current_time = 0.0
        interval = 1.0 / sample_rate
        
        while current_time < times[-1]:
            window_end = current_time + interval
            values_in_window = [
                v for t, v in env.items()
                if current_time <= t < window_end
            ]
            if values_in_window:
                resampled[current_time] = sum(values_in_window) / len(values_in_window)
            current_time += interval
        
        return resampled

    def get_silence_regions(self, audio_name: str) -> List[Tuple[float, float]]:
        """Get silence regions (start, end) in seconds."""
        result = self.analysis_results.get(audio_name)
        return result.silence_regions if result else []

    def get_drops(self, audio_name: str) -> List[Tuple[float, float]]:
        """Get drop/breakdown regions."""
        result = self.analysis_results.get(audio_name)
        return result.drops if result else []

    def get_bpm(self, audio_name: str) -> float:
        """Get estimated BPM."""
        result = self.analysis_results.get(audio_name)
        return result.bpm if result else 0.0

    # =========================================================================
    # Section Marking
    # =========================================================================

    def add_section(
        self,
        name: str,
        start: float,
        end: float,
        section_type: str,
    ) -> bool:
        """
        Manually mark a section (intro, buildup, drop, etc.).
        
        Args:
          name: "Intro", "Build 1", "Drop 1", etc.
          start: start timecode (seconds)
          end: end timecode (seconds)
          section_type: "intro", "buildup", "drop", "breakdown", "outro"
        
        Validates:
        - start < end
        - No overlap with existing sections
        """
        try:
            if start >= end:
                print(f"[AudioTab] Invalid section: start ({start}) >= end ({end})")
                return False
            
            # Check overlap
            for existing in self.sections:
                if not (end <= existing["start"] or start >= existing["end"]):
                    print(f"[AudioTab] Section overlaps with {existing['name']}")
                    return False
            
            self.sections.append({
                "name": name,
                "start": start,
                "end": end,
                "type": section_type,
            })
            
            # Keep sorted
            self.sections.sort(key=lambda s: s["start"])
            
            print(f"[AudioTab] Added section: {name} ({start:.1f}–{end:.1f}s, type={section_type})")
            return True
        
        except Exception as e:
            print(f"[AudioTab] Failed to add section: {e}")
            return False

    def suggest_sections(self, audio_name: str) -> List[Dict]:
        """
        Auto-suggest section boundaries based on analysis.
        
        Uses:
        - Silence regions (end of intro, start of outro)
        - Drops (start of drop)
        - Energy peaks (start of buildup)
        - BPM consistency changes
        
        Returns:
          List of suggested sections (user must confirm)
        """
        result = self.analysis_results.get(audio_name)
        if not result:
            return []
        
        suggestions = []
        
        try:
            # Intro: from start to first substantial energy rise
            # Find where energy crosses some threshold
            energy = result.energy_envelope
            if energy:
                sorted_times = sorted(energy.keys())
                first_high_energy_time = None
                
                for t in sorted_times[:len(sorted_times) // 3]:  # First third
                    if energy[t] > -20:  # Above -20dB
                        first_high_energy_time = t
                        break
                
                if first_high_energy_time and first_high_energy_time > 10:
                    suggestions.append({
                        "name": "Intro",
                        "start": 0.0,
                        "end": first_high_energy_time,
                        "type": "intro",
                        "confidence": 0.7,
                    })
            
            # Drops from detected drops
            for drop_start, drop_end in result.drops:
                suggestions.append({
                    "name": f"Drop @ {drop_start:.0f}s",
                    "start": drop_start,
                    "end": drop_end,
                    "type": "drop",
                    "confidence": 0.8,
                })
            
            # Outro: from last silence region end to end
            if result.silence_regions:
                last_silence = result.silence_regions[-1]
                if last_silence[1] > 0:
                    audio_duration = max(energy.keys()) if energy else 0.0
                    if audio_duration - last_silence[1] > 30:  # At least 30s outro
                        suggestions.append({
                            "name": "Outro",
                            "start": last_silence[1],
                            "end": audio_duration,
                            "type": "outro",
                            "confidence": 0.6,
                        })
            
            print(f"[AudioTab] Suggested {len(suggestions)} sections")
            return suggestions
        
        except Exception as e:
            print(f"[AudioTab] Section suggestion failed: {e}")
            return []

    def accept_suggested_sections(self, suggestions: List[Dict]) -> int:
        """Accept auto-suggested sections. Returns count added."""
        count = 0
        for sugg in suggestions:
            if self.add_section(sugg["name"], sugg["start"], sugg["end"], sugg["type"]):
                count += 1
        return count

    def get_sections(self) -> List[Dict]:
        """Get all marked sections."""
        return self.sections.copy()

    def remove_section(self, name: str) -> bool:
        """Remove a marked section."""
        try:
            self.sections = [s for s in self.sections if s["name"] != name]
            print(f"[AudioTab] Removed section: {name}")
            return True
        except Exception as e:
            print(f"[AudioTab] Failed to remove section: {e}")
            return False

    # =========================================================================
    # Audio Mixing / Stem Extraction
    # =========================================================================

    def extract_stems(self, audio_name: str) -> Tuple[bool, Dict[str, str]]:
        """
        Attempt to extract stems (kick, bass, mids, highs) if available.
        
        This is advanced; typically requires:
        - Isolated stems already in project
        - Or use of STEMS format / source separation
        
        Returns:
          (success, stem_paths)
        """
        print(f"[AudioTab] Stem extraction requested for {audio_name}")
        print(f"[AudioTab] Note: Requires isolated stems or advanced DSP (not yet implemented)")
        return False, {}

    def get_audio_mix_info(self, audio_name: str) -> Optional[Dict]:
        """Get info about the audio mix (channel count, sample rate, duration)."""
        audio_source = None
        for src in self.project.audio_sources:
            if src.name == audio_name:
                audio_source = src
                break
        
        if not audio_source:
            return None
        
        return {
            "name": audio_name,
            "file": audio_source.file_path,
            "duration": audio_source.duration,
            "sample_rate": audio_source.sample_rate,
            "channels": audio_source.channels,
            "audio_type": audio_source.audio_type.value if audio_source.audio_type else "unknown",
        }

    # =========================================================================
    # Validation & Confirmation
    # =========================================================================

    def validate_audio_analysis(self) -> Tuple[bool, List[str]]:
        """
        Validate before proceeding to Cut tab.
        
        Checks:
        - At least one audio track analyzed
        - Sections marked (or at least suggested)
        - BPM reasonable (20–300)
        """
        warnings = []
        
        if not self.analysis_results:
            warnings.append("No audio analyzed")
        
        if not self.sections:
            warnings.append("No sections marked (auto-suggest or mark manually)")
        
        # Check BPM
        for audio_name, result in self.analysis_results.items():
            if result.bpm < 20 or result.bpm > 300:
                warnings.append(f"{audio_name}: BPM={result.bpm:.0f} seems unrealistic")
            
            if result.confidence < 0.5:
                warnings.append(f"{audio_name}: beat detection confidence low ({result.confidence:.2f})")
        
        valid = len(warnings) == 0 or all("No sections" in w for w in warnings)
        return valid, warnings

    def confirm_audio_analysis(self) -> Tuple[bool, str]:
        """Finalize audio analysis and prepare for Cut tab."""
        try:
            valid, warnings = self.validate_audio_analysis()
            
            # Store in project
            self.project.audio_analysis_results = self.analysis_results
            self.project.sections = self.sections
            
            msg = f"Audio analysis confirmed: {len(self.analysis_results)} tracks, {len(self.sections)} sections"
            return True, msg
        
        except Exception as e:
            return False, f"Confirmation failed: {e}"

    # =========================================================================
    # Export & Diagnostics
    # =========================================================================

    def export_analysis_report(self, output_path: str) -> bool:
        """Export analysis results as JSON."""
        import json
        
        try:
            report = {
                "audio_tracks": {},
                "sections": self.sections,
            }
            
            for audio_name, result in self.analysis_results.items():
                report["audio_tracks"][audio_name] = {
                    "bpm": result.bpm,
                    "confidence": result.confidence,
                    "beat_count": len(result.beats),
                    "silence_regions": len(result.silence_regions),
                    "drops": len(result.drops),
                }
            
            with open(output_path, "w") as f:
                json.dump(report, f, indent=2)
            
            print(f"[AudioTab] Analysis report exported to {output_path}")
            return True
        
        except Exception as e:
            print(f"[AudioTab] Export failed: {e}")
            return False

    def get_diagnostics(self) -> Dict:
        """Return analysis diagnostics."""
        return {
            "analyzed_tracks": list(self.analysis_results.keys()),
            "sections_marked": len(self.sections),
            "analysis_available": bool(self.analysis_results),
        }

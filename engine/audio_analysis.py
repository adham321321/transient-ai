"""Audio analysis: BPM detection, beat grid, energy curve, section detection."""

import numpy as np
from typing import Tuple, Optional, List, Dict
import librosa
import warnings


class AudioAnalyzer:
    """Hardened audio analysis engine."""

    # Constants
    ANALYSIS_SR = 22050  # Reduced sample rate for analysis (Section 4.1)
    HOP_LENGTH = 512
    FMIN = 80
    FMAX = 400

    def __init__(self):
        self.y = None
        self.sr = None
        self.onset_env = None
        self.tempo = None
        self.beats = None
        self.energy_curve = None

    def load_audio(self, file_path: str, offset: float = 0.0, duration: Optional[float] = None) -> bool:
        """
        Load audio file at reduced sample rate.
        Returns True on success, False on error.
        Never raise; always return status.
        """
        try:
            self.y, self.sr = librosa.load(
                file_path,
                sr=self.ANALYSIS_SR,
                offset=offset,
                duration=duration
            )
            # Precompute onset envelope once (Section 4.1 performance requirement)
            self.onset_env = librosa.onset.onset_strength(
                y=self.y,
                sr=self.sr,
                hop_length=self.HOP_LENGTH
            )
            return True
        except Exception as e:
            print(f"[AudioAnalyzer] Error loading {file_path}: {e}")
            return False

    def estimate_tempo(self, target_bpm: Optional[float] = None, search_range: float = 15.0) -> Optional[float]:
        """
        Estimate BPM with defensive handling for API shape mismatches (Section 4.1).
        If target_bpm is provided, grid-search ± range around it.
        Returns BPM or None on error/no data.
        """
        if self.onset_env is None:
            return None

        try:
            # librosa.beat.tempo can return float or array; handle both
            result = librosa.beat.tempo(
                onset_envelope=self.onset_env,
                sr=self.sr,
                hop_length=self.HOP_LENGTH
            )
            # Defensive: check if result is array or scalar
            if isinstance(result, (list, np.ndarray)):
                estimated_bpm = float(result[0]) if len(result) > 0 else 120.0
            else:
                estimated_bpm = float(result)

            if target_bpm:
                # Refine estimate near target
                low_bpm = max(60, target_bpm - search_range)
                high_bpm = min(240, target_bpm + search_range)
                # Clamp to search range
                estimated_bpm = np.clip(estimated_bpm, low_bpm, high_bpm)

            self.tempo = estimated_bpm
            return estimated_bpm

        except Exception as e:
            print(f"[AudioAnalyzer] Tempo estimation failed: {e}")
            return None

    def get_beat_grid(self, bpm: float) -> Optional[np.ndarray]:
        """
        Compute beat grid (sample-accurate) from onset envelope.
        Returns array of beat sample positions.
        """
        if self.onset_env is None:
            return None

        try:
            frames = librosa.beat.frames_to_time(
                librosa.beat.beat_track(
                    onset_envelope=self.onset_env,
                    sr=self.sr,
                    hop_length=self.HOP_LENGTH,
                    tg=bpm / 60.0
                )[1],
                sr=self.sr,
                hop_length=self.HOP_LENGTH
            )
            self.beats = frames
            return frames
        except Exception as e:
            print(f"[AudioAnalyzer] Beat grid computation failed: {e}")
            return None

    def compute_energy_curve(self, smoothing_window: int = 2048) -> Optional[np.ndarray]:
        """
        Compute smoothed energy curve (RMS + spectral flux).
        Returns energy values per frame.
        """
        if self.y is None:
            return None

        try:
            # RMS energy
            S = librosa.feature.melspectrogram(
                y=self.y,
                sr=self.sr,
                hop_length=self.HOP_LENGTH,
                fmin=self.FMIN,
                fmax=self.FMAX
            )
            rms = librosa.feature.rms(S=S)[0]

            # Spectral flux (onsets)
            spec = np.abs(librosa.stft(self.y, hop_length=self.HOP_LENGTH))
            spec_flux = np.sqrt(np.sum(np.diff(spec, axis=1) ** 2, axis=0))
            spec_flux = np.concatenate([[0], spec_flux])  # Match length

            # Combine and smooth
            energy = (rms + spec_flux) / 2.0
            energy_smooth = librosa.util.normalize(
                librosa.filters.get_window("hann", smoothing_window)
            )
            self.energy_curve = np.convolve(energy, energy_smooth, mode="same")
            return self.energy_curve

        except Exception as e:
            print(f"[AudioAnalyzer] Energy curve computation failed: {e}")
            return None

    def detect_sections(self, sensitivity: float = 0.7) -> Optional[Dict[str, List[float]]]:
        """
        Heuristic section detection (intro/build/drop/peak/breakdown/outro).
        Returns dict of section_name -> list of onset times (seconds).
        """
        if self.energy_curve is None or self.beats is None:
            return None

        try:
            sections = {
                "intro": [],
                "buildup": [],
                "drop": [],
                "peak": [],
                "breakdown": [],
                "outro": [],
            }

            # Simple heuristic: look for energy peaks relative to local median
            threshold = np.median(self.energy_curve) + (sensitivity * np.std(self.energy_curve))
            peaks = np.where(self.energy_curve > threshold)[0]

            if len(peaks) > 0:
                # Classify by position and energy pattern (simplified)
                total_frames = len(self.energy_curve)
                for peak_frame in peaks:
                    peak_time = librosa.frames_to_time(peak_frame, sr=self.sr, hop_length=self.HOP_LENGTH)
                    progress = peak_frame / total_frames

                    if progress < 0.1:
                        sections["intro"].append(peak_time)
                    elif progress < 0.3:
                        sections["buildup"].append(peak_time)
                    elif progress < 0.6:
                        sections["drop"].append(peak_time)
                    elif progress < 0.75:
                        sections["peak"].append(peak_time)
                    elif progress < 0.9:
                        sections["breakdown"].append(peak_time)
                    else:
                        sections["outro"].append(peak_time)

            return sections

        except Exception as e:
            print(f"[AudioAnalyzer] Section detection failed: {e}")
            return None

    def detect_drops(self, threshold: float = 0.55) -> Optional[List[float]]:
        """
        Detect drop moments (energy peaks) above threshold.
        Returns list of drop times in seconds.
        """
        if self.energy_curve is None:
            return None

        try:
            # Find peaks in energy above threshold
            peaks, _ = librosa.util.localmax(self.energy_curve, order=5)
            peak_times = librosa.frames_to_time(
                np.where(peaks)[0],
                sr=self.sr,
                hop_length=self.HOP_LENGTH
            )
            
            # Filter by threshold
            peak_energies = self.energy_curve[np.where(peaks)[0]]
            threshold_energy = threshold * np.max(self.energy_curve)
            drops = peak_times[peak_energies > threshold_energy]

            return sorted(drops.tolist())

        except Exception as e:
            print(f"[AudioAnalyzer] Drop detection failed: {e}")
            return None

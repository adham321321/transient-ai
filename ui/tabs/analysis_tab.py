"""Analysis Tab: Mark moments and named cut points (Section 6.4)."""

from typing import List, Optional, Dict, Tuple
from enum import Enum
from dataclasses import dataclass, field
import os

from models.project import ProjectState


class MomentType(Enum):
    """Types of notable moments."""
    BEAT = "beat"
    DROP = "drop"
    BUILD_START = "build_start"
    BUILD_PEAK = "build_peak"
    BREAKDOWN = "breakdown"
    SOLO = "solo"
    TRANSITION = "transition"
    HIGHLIGHT = "highlight"
    AUDIENCE_REACTION = "audience_reaction"
    CUSTOM = "custom"


@dataclass
class Moment:
    """A marked moment in time."""
    time: float  # seconds
    name: str
    moment_type: MomentType
    description: str = ""
    camera_suggestions: List[str] = field(default_factory=list)  # Which cameras to show here
    duration: float = 0.5  # Suggested hold time (seconds)
    tags: List[str] = field(default_factory=list)


@dataclass
class CutPoint:
    """A named cut point for cut list generation."""
    time: float  # seconds
    name: str
    priority: int = 1  # 1=must use, 2=preferred, 3=nice to have
    description: str = ""
    associated_cameras: List[str] = field(default_factory=list)


class AnalysisTab:
    """
    Analysis Tab: Mark moments and define named cut points.
    
    Workflow:
    1. Review audio analysis (BPM, drops, sections)
    2. Mark moments: beats, drops, solos, highlight reel material
    3. For each moment: suggest which camera(s) to show
    4. Define named cut points for the cut list
    5. Tag moments (e.g., "funky", "energy high", "crowd reaction")
    6. Export moment sheet
    7. Proceed to Cut tab
    
    Section 6.4: "Make it intuitive to mark 'good bits'.
    Allow user to jump to marked moments in preview.
    Show suggested cameras for each moment."
    """

    def __init__(self, project: ProjectState):
        self.project = project
        self.moments: List[Moment] = []
        self.cut_points: List[CutPoint] = []
        self.highlight_reel_moments: List[Moment] = []

    # =========================================================================
    # Moment Management
    # =========================================================================

    def add_moment(
        self,
        time: float,
        name: str,
        moment_type: MomentType,
        description: str = "",
        camera_suggestions: Optional[List[str]] = None,
        duration: float = 0.5,
        tags: Optional[List[str]] = None,
    ) -> bool:
        """
        Mark a moment in the timeline.
        
        Args:
          time: timecode (seconds)
          name: e.g., "Drop 1", "DJ solo", "Crowd singing"
          moment_type: category
          description: notes about this moment
          camera_suggestions: which cameras to use
          duration: how long to show this (for cut list)
          tags: searchable tags
        
        Validates:
        - time is non-negative
        - name is not empty
        - no duplicate times (warn if within 0.5s)
        """
        try:
            if time < 0:
                print(f"[AnalysisTab] Invalid moment time: {time}")
                return False
            
            if not name:
                print(f"[AnalysisTab] Moment name required")
                return False
            
            # Check for duplicates
            for existing in self.moments:
                if abs(existing.time - time) < 0.5:
                    print(f"[AnalysisTab] Warning: moment near existing at {existing.time:.1f}s")
            
            moment = Moment(
                time=time,
                name=name,
                moment_type=moment_type,
                description=description,
                camera_suggestions=camera_suggestions or [],
                duration=duration,
                tags=tags or [],
            )
            
            self.moments.append(moment)
            self.moments.sort(key=lambda m: m.time)
            
            print(f"[AnalysisTab] Added moment: {name} @ {time:.1f}s ({moment_type.value})")
            return True
        
        except Exception as e:
            print(f"[AnalysisTab] Failed to add moment: {e}")
            return False

    def remove_moment(self, time: float) -> bool:
        """Remove moment at given time."""
        try:
            self.moments = [m for m in self.moments if abs(m.time - time) > 0.1]
            print(f"[AnalysisTab] Removed moment at {time:.1f}s")
            return True
        except Exception as e:
            print(f"[AnalysisTab] Failed to remove moment: {e}")
            return False

    def get_moments(self) -> List[Moment]:
        """Get all marked moments (sorted by time)."""
        return sorted(self.moments, key=lambda m: m.time)

    def get_moments_by_type(self, moment_type: MomentType) -> List[Moment]:
        """Get moments of a specific type."""
        return [m for m in self.moments if m.moment_type == moment_type]

    def get_moments_by_tag(self, tag: str) -> List[Moment]:
        """Get moments with a specific tag."""
        return [m for m in self.moments if tag in m.tags]

    def find_nearby_moments(self, time: float, window: float = 5.0) -> List[Moment]:
        """Find moments within a time window."""
        return [m for m in self.moments if abs(m.time - time) <= window]

    # =========================================================================
    # Auto-Population from Audio Analysis
    # =========================================================================

    def populate_moments_from_analysis(self) -> int:
        """
        Auto-populate moments from audio analysis results.
        
        Uses:
        - Detected beats → BEAT moments
        - Detected drops → DROP moments
        - Section boundaries → BUILD_START, BREAKDOWN moments
        
        Returns:
          Count of moments added
        """
        if not self.project.audio_analysis_results:
            print("[AnalysisTab] No audio analysis available")
            return 0
        
        count = 0
        
        try:
            for audio_name, analysis_result in self.project.audio_analysis_results.items():
                # Add beat moments (sparse: every 4th beat for readability)
                beats = analysis_result.beats
                for i, beat_time in enumerate(beats):
                    if i % 4 == 0:  # Every 4th beat
                        if self.add_moment(
                            time=beat_time,
                            name=f"Beat {i//4 + 1}",
                            moment_type=MomentType.BEAT,
                            duration=0.2,
                        ):
                            count += 1
                
                # Add drop moments
                for drop_start, drop_end in analysis_result.drops:
                    if self.add_moment(
                        time=drop_start,
                        name=f"Drop @ {drop_start:.0f}s",
                        moment_type=MomentType.DROP,
                        duration=drop_end - drop_start,
                    ):
                        count += 1
            
            # Add section boundaries as moments
            if self.project.sections:
                for section in self.project.sections:
                    if self.add_moment(
                        time=section["start"],
                        name=f"{section['name']} start",
                        moment_type=MomentType.BUILD_START
                        if section["type"] == "buildup"
                        else MomentType.BREAKDOWN,
                        duration=1.0,
                    ):
                        count += 1
            
            print(f"[AnalysisTab] Populated {count} moments from analysis")
            return count
        
        except Exception as e:
            print(f"[AnalysisTab] Auto-populate failed: {e}")
            return 0

    # =========================================================================
    # Highlight Reel
    # =========================================================================

    def mark_as_highlight(self, time: float) -> bool:
        """Mark a moment as part of the highlight reel."""
        try:
            for moment in self.moments:
                if abs(moment.time - time) < 0.1:
                    self.highlight_reel_moments.append(moment)
                    print(f"[AnalysisTab] Marked as highlight: {moment.name}")
                    return True
            
            print(f"[AnalysisTab] No moment found at {time:.1f}s")
            return False
        
        except Exception as e:
            print(f"[AnalysisTab] Failed to mark highlight: {e}")
            return False

    def unmark_as_highlight(self, time: float) -> bool:
        """Unmark a moment from highlight reel."""
        try:
            self.highlight_reel_moments = [
                m for m in self.highlight_reel_moments
                if abs(m.time - time) > 0.1
            ]
            print(f"[AnalysisTab] Unmarked as highlight: {time:.1f}s")
            return True
        except Exception as e:
            print(f"[AnalysisTab] Failed to unmark highlight: {e}")
            return False

    def get_highlight_reel(self) -> List[Moment]:
        """Get all moments marked for highlight reel."""
        return sorted(self.highlight_reel_moments, key=lambda m: m.time)

    def get_highlight_reel_duration(self) -> float:
        """Get total duration of highlight reel."""
        return sum(m.duration for m in self.highlight_reel_moments)

    # =========================================================================
    # Cut Point Management
    # =========================================================================

    def add_cut_point(
        self,
        time: float,
        name: str,
        priority: int = 1,
        description: str = "",
        associated_cameras: Optional[List[str]] = None,
    ) -> bool:
        """
        Define a named cut point for the cut list.
        
        Args:
          time: timecode (seconds)
          name: e.g., "Intro end", "First drop", "Breakdow start"
          priority: 1=must use, 2=preferred, 3=nice to have
          description: notes
          associated_cameras: suggested cameras for this cut
        
        Cut points are used by the Cut tab to generate the cut list.
        """
        try:
            if time < 0:
                print(f"[AnalysisTab] Invalid cut point time: {time}")
                return False
            
            if not name:
                print(f"[AnalysisTab] Cut point name required")
                return False
            
            cut_point = CutPoint(
                time=time,
                name=name,
                priority=priority,
                description=description,
                associated_cameras=associated_cameras or [],
            )
            
            self.cut_points.append(cut_point)
            self.cut_points.sort(key=lambda cp: cp.time)
            
            priority_str = {1: "MUST", 2: "PREFERRED", 3: "NICE"}.get(priority, "?")
            print(f"[AnalysisTab] Added cut point: {name} @ {time:.1f}s [{priority_str}]")
            return True
        
        except Exception as e:
            print(f"[AnalysisTab] Failed to add cut point: {e}")
            return False

    def remove_cut_point(self, time: float) -> bool:
        """Remove cut point at given time."""
        try:
            self.cut_points = [cp for cp in self.cut_points if abs(cp.time - time) > 0.1]
            print(f"[AnalysisTab] Removed cut point at {time:.1f}s")
            return True
        except Exception as e:
            print(f"[AnalysisTab] Failed to remove cut point: {e}")
            return False

    def get_cut_points(self) -> List[CutPoint]:
        """Get all cut points (sorted by time)."""
        return sorted(self.cut_points, key=lambda cp: cp.time)

    def get_cut_points_by_priority(self, priority: int) -> List[CutPoint]:
        """Get cut points of specific priority."""
        return [cp for cp in self.cut_points if cp.priority == priority]

    def populate_cut_points_from_sections(self) -> int:
        """
        Auto-populate cut points from project sections.
        Each section boundary becomes a cut point (priority 2).
        
        Returns:
          Count added
        """
        if not self.project.sections:
            return 0
        
        count = 0
        try:
            for section in self.project.sections:
                if self.add_cut_point(
                    time=section["start"],
                    name=f"{section['name']} start",
                    priority=2,
                    description=f"Start of {section['type']}",
                ):
                    count += 1
            
            print(f"[AnalysisTab] Populated {count} cut points from sections")
            return count
        
        except Exception as e:
            print(f"[AnalysisTab] Populate cut points failed: {e}")
            return 0

    # =========================================================================
    # Moment Suggestions
    # =========================================================================

    def suggest_camera_for_moment(self, moment: Moment) -> List[str]:
        """
        Suggest which cameras to show for a moment.
        
        Logic:
        - BEAT, BUILDUP: wide shot or roaming
        - DROP, BREAKDOWN: close-up (booth or audience)
        - SOLO: booth close-up
        - HIGHLIGHT: varies
        """
        if moment.camera_suggestions:
            return moment.camera_suggestions
        
        suggestions = []
        
        if moment.moment_type in [MomentType.BEAT, MomentType.BUILD_START]:
            # Wide or roaming
            suggestions = ["wide", "roaming"]
        elif moment.moment_type in [MomentType.DROP, MomentType.BREAKDOWN]:
            # Close-up or audience
            suggestions = ["booth_closeup", "audience"]
        elif moment.moment_type == MomentType.SOLO:
            # Booth close-up
            suggestions = ["booth_closeup"]
        elif moment.moment_type == MomentType.AUDIENCE_REACTION:
            # Audience
            suggestions = ["audience"]
        else:
            # Default: any available
            suggestions = [c.name for c in self.project.cameras] if self.project.cameras else []
        
        return suggestions

    def apply_camera_suggestions(self) -> int:
        """Auto-apply camera suggestions to all moments. Returns count updated."""
        count = 0
        try:
            for moment in self.moments:
                if not moment.camera_suggestions:
                    moment.camera_suggestions = self.suggest_camera_for_moment(moment)
                    count += 1
            
            print(f"[AnalysisTab] Applied camera suggestions to {count} moments")
            return count
        
        except Exception as e:
            print(f"[AnalysisTab] Camera suggestion failed: {e}")
            return 0

    # =========================================================================
    # Validation & Confirmation
    # =========================================================================

    def validate_analysis(self) -> Tuple[bool, List[str]]:
        """
        Validate before proceeding to Cut tab.
        
        Checks:
        - At least some moments marked
        - Cut points defined
        - Highlight reel not empty (or warn)
        """
        warnings = []
        
        if not self.moments:
            warnings.append("No moments marked")
        
        if not self.cut_points:
            warnings.append("No cut points defined")
        
        if not self.highlight_reel_moments:
            warnings.append("Highlight reel is empty (optional but recommended)")
        
        valid = len(warnings) <= 1  # Allow if only highlight reel is missing
        return valid, warnings

    def confirm_analysis(self) -> Tuple[bool, str]:
        """Finalize analysis and prepare for Cut tab."""
        try:
            valid, warnings = self.validate_analysis()
            
            if warnings:
                print(f"[AnalysisTab] Warnings: {', '.join(warnings)}")
            
            # Store in project
            self.project.moments = self.moments
            self.project.cut_points = self.cut_points
            self.project.highlight_reel = self.highlight_reel_moments
            
            msg = (
                f"Analysis confirmed: {len(self.moments)} moments, "
                f"{len(self.cut_points)} cut points, "
                f"{len(self.highlight_reel_moments)} highlight moments"
            )
            return True, msg
        
        except Exception as e:
            return False, f"Confirmation failed: {e}"

    # =========================================================================
    # Export & Diagnostics
    # =========================================================================

    def export_moment_sheet(self, output_path: str) -> bool:
        """Export moment sheet as CSV for review in spreadsheet."""
        import csv
        
        try:
            with open(output_path, "w", newline="") as f:
                writer = csv.writer(f)
                
                writer.writerow([
                    "Time (s)", "Name", "Type", "Duration (s)",
                    "Cameras", "Tags", "Description"
                ])
                
                for moment in self.get_moments():
                    writer.writerow([
                        f"{moment.time:.2f}",
                        moment.name,
                        moment.moment_type.value,
                        f"{moment.duration:.2f}",
                        "|".join(moment.camera_suggestions),
                        "|".join(moment.tags),
                        moment.description,
                    ])
            
            print(f"[AnalysisTab] Moment sheet exported to {output_path}")
            return True
        
        except Exception as e:
            print(f"[AnalysisTab] Export failed: {e}")
            return False

    def export_cut_list(self, output_path: str) -> bool:
        """Export cut point list as CSV."""
        import csv
        
        try:
            with open(output_path, "w", newline="") as f:
                writer = csv.writer(f)
                
                writer.writerow([
                    "Time (s)", "Name", "Priority", "Cameras", "Description"
                ])
                
                for cp in self.get_cut_points():
                    priority_str = {1: "MUST", 2: "PREFERRED", 3: "NICE"}.get(cp.priority, "?")
                    writer.writerow([
                        f"{cp.time:.2f}",
                        cp.name,
                        priority_str,
                        "|".join(cp.associated_cameras),
                        cp.description,
                    ])
            
            print(f"[AnalysisTab] Cut list exported to {output_path}")
            return True
        
        except Exception as e:
            print(f"[AnalysisTab] Export failed: {e}")
            return False

    def get_diagnostics(self) -> Dict:
        """Return diagnostics."""
        return {
            "moments_count": len(self.moments),
            "cut_points_count": len(self.cut_points),
            "highlight_reel_count": len(self.highlight_reel_moments),
            "highlight_duration": self.get_highlight_reel_duration(),
            "must_use_cut_points": len(self.get_cut_points_by_priority(1)),
            "moment_types": {mt.value: len(self.get_moments_by_type(mt))
                             for mt in MomentType},
        }

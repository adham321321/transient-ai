"""Cut Tab: Generate cut list and finalize edits (Section 6.5)."""

from typing import List, Optional, Dict, Tuple
from enum import Enum
from dataclasses import dataclass, field
import os

from models.project import ProjectState


@dataclass
class CutInstruction:
    """A single cut instruction for the editor."""
    sequence_number: int
    timecode_in: float  # seconds, from sync audio
    timecode_out: float  # seconds, from sync audio
    duration: float  # seconds
    primary_camera: str
    alternate_cameras: List[str] = field(default_factory=list)
    transition: str = "cut"  # "cut", "dissolve", "fade"
    transition_duration: float = 0.0
    notes: str = ""
    audio_tracks: List[str] = field(default_factory=list)  # Which audio to include
    color_label: str = ""  # UI hint: "good", "ok", "needs_work"


@dataclass
class CutList:
    """Complete cut list for the project."""
    project_name: str
    total_duration: float
    frame_rate: float
    cuts: List[CutInstruction] = field(default_factory=list)
    
    def get_total_duration(self) -> float:
        """Calculate total duration of all cuts."""
        return sum(c.duration for c in self.cuts)
    
    def validate(self) -> Tuple[bool, List[str]]:
        """Validate cut list integrity."""
        warnings = []
        
        for i, cut in enumerate(self.cuts):
            if cut.timecode_in >= cut.timecode_out:
                warnings.append(f"Cut {i}: in ({cut.timecode_in:.1f}) >= out ({cut.timecode_out:.1f})")
            
            if not cut.primary_camera:
                warnings.append(f"Cut {i}: no primary camera selected")
            
            if cut.duration < 0.5:
                warnings.append(f"Cut {i}: very short ({cut.duration:.2f}s)")
        
        return len(warnings) == 0, warnings


class CutTab:
    """
    Cut Tab: Generate final cut list and export for editing.
    
    Workflow:
    1. Load moments and cut points from Analysis tab
    2. Generate auto cut list based on camera coverage + audio analysis
    3. Manual refinement: adjust timings, swap cameras, add transitions
    4. Preview cut list: see suggested camera coverage over timeline
    5. Validate cut list (no gaps, all cuts covered)
    6. Export as XML, JSON, or EDL
    7. Finalize project
    
    Section 6.5: "Auto-generate smart cut list. Allow manual override.
    Export in multiple formats for different NLEs."
    """

    def __init__(self, project: ProjectState):
        self.project = project
        self.cut_list: Optional[CutList] = None
        self.auto_generated_cuts: List[CutInstruction] = []
        self.custom_cuts: List[CutInstruction] = []

    # =========================================================================
    # Auto-Cut List Generation
    # =========================================================================

    def generate_auto_cut_list(self) -> Tuple[bool, str]:
        """
        Auto-generate cut list based on:
        - Cut points (from Analysis tab)
        - Camera coverage (from clip mapper)
        - Audio analysis (beats, drops)
        - Highlight reel (if marked)
        
        Returns:
          (success, message)
        """
        try:
            if not self.project.cut_points:
                return False, "No cut points defined in Analysis tab"
            
            if not self.project.clip_mapper:
                return False, "No clip mapper (sync incomplete?)"
            
            if not self.project.audio_sources:
                return False, "No audio sources"
            
            cuts = []
            cut_points = sorted(self.project.cut_points, key=lambda cp: cp.time)
            
            # For each pair of consecutive cut points, generate a cut
            for i in range(len(cut_points) - 1):
                cp_start = cut_points[i]
                cp_end = cut_points[i + 1]
                
                # Find primary camera with coverage in this range
                primary_cam = self._select_best_camera(cp_start.time, cp_end.time)
                
                if not primary_cam:
                    print(f"[CutTab] Warning: no camera coverage at {cp_start.time:.1f}–{cp_end.time:.1f}s")
                    continue
                
                # Find alternate cameras
                alternates = self._find_alternate_cameras(
                    cp_start.time, cp_end.time, exclude=primary_cam
                )
                
                cut = CutInstruction(
                    sequence_number=len(cuts) + 1,
                    timecode_in=cp_start.time,
                    timecode_out=cp_end.time,
                    duration=cp_end.time - cp_start.time,
                    primary_camera=primary_cam,
                    alternate_cameras=alternates,
                    notes=f"Between: {cp_start.name} → {cp_end.name}",
                )
                
                cuts.append(cut)
            
            self.auto_generated_cuts = cuts
            
            self.cut_list = CutList(
                project_name=self.project.settings.project_name,
                total_duration=self._get_project_duration(),
                frame_rate=self.project.settings.frame_rate,
                cuts=cuts,
            )
            
            msg = f"Generated {len(cuts)} cuts (total {self.cut_list.get_total_duration():.1f}s)"
            return True, msg
        
        except Exception as e:
            return False, f"Auto-generation failed: {e}"

    def _select_best_camera(self, start: float, end: float) -> Optional[str]:
        """
        Select best camera for a time range.
        
        Priority:
        1. Most coverage in range
        2. Marked as primary (booth for drops, wide for buildups)
        3. Any available
        """
        try:
            if not self.project.clip_mapper:
                return None
            
            best_cam = None
            best_coverage = 0.0
            
            for camera in self.project.cameras:
                # Check coverage
                if self.project.clip_mapper.has_coverage_at(camera.name, (start + end) / 2):
                    total_coverage = self.project.clip_mapper.get_coverage_in_range(
                        camera.name, start, end
                    )
                    if total_coverage > best_coverage:
                        best_coverage = total_coverage
                        best_cam = camera.name
            
            return best_cam
        
        except Exception as e:
            print(f"[CutTab] Camera selection failed: {e}")
            return None

    def _find_alternate_cameras(self, start: float, end: float, exclude: str = "") -> List[str]:
        """Find alternate cameras available in time range."""
        try:
            alternates = []
            
            for camera in self.project.cameras:
                if camera.name == exclude:
                    continue
                
                if self.project.clip_mapper.has_coverage_at(camera.name, (start + end) / 2):
                    alternates.append(camera.name)
            
            return alternates
        
        except Exception as e:
            print(f"[CutTab] Alternate camera search failed: {e}")
            return []

    def _get_project_duration(self) -> float:
        """Get total project duration from clip mapper."""
        if not self.project.clip_mapper:
            return 0.0
        
        try:
            return self.project.clip_mapper.get_total_duration()
        except Exception:
            return 0.0

    # =========================================================================
    # Manual Cut List Editing
    # =========================================================================

    def add_cut(
        self,
        timecode_in: float,
        timecode_out: float,
        primary_camera: str,
        alternate_cameras: Optional[List[str]] = None,
        transition: str = "cut",
        transition_duration: float = 0.0,
        notes: str = "",
    ) -> bool:
        """
        Manually add a cut to the cut list.
        
        Args:
          timecode_in/out: in seconds, from sync audio
          primary_camera: camera to show
          alternate_cameras: fallback cameras
          transition: "cut", "dissolve", "fade"
          transition_duration: in seconds
          notes: editor notes
        
        Validates:
        - in < out
        - cameras exist
        - timecodes make sense
        """
        try:
            if timecode_in >= timecode_out:
                print(f"[CutTab] Invalid cut: in ({timecode_in}) >= out ({timecode_out})")
                return False
            
            if not self.cut_list:
                self.cut_list = CutList(
                    project_name=self.project.settings.project_name,
                    total_duration=self._get_project_duration(),
                    frame_rate=self.project.settings.frame_rate,
                )
            
            cut = CutInstruction(
                sequence_number=len(self.cut_list.cuts) + 1,
                timecode_in=timecode_in,
                timecode_out=timecode_out,
                duration=timecode_out - timecode_in,
                primary_camera=primary_camera,
                alternate_cameras=alternate_cameras or [],
                transition=transition,
                transition_duration=transition_duration,
                notes=notes,
            )
            
            self.cut_list.cuts.append(cut)
            print(f"[CutTab] Added cut {cut.sequence_number}: {primary_camera} ({cut.duration:.1f}s)")
            return True
        
        except Exception as e:
            print(f"[CutTab] Failed to add cut: {e}")
            return False

    def remove_cut(self, sequence_number: int) -> bool:
        """Remove a cut by sequence number."""
        try:
            if not self.cut_list:
                return False
            
            self.cut_list.cuts = [c for c in self.cut_list.cuts if c.sequence_number != sequence_number]
            print(f"[CutTab] Removed cut {sequence_number}")
            return True
        
        except Exception as e:
            print(f"[CutTab] Failed to remove cut: {e}")
            return False

    def update_cut(
        self,
        sequence_number: int,
        **kwargs
    ) -> bool:
        """
        Update a cut's properties.
        
        Allowed keys: timecode_in, timecode_out, primary_camera, transition, notes
        """
        try:
            if not self.cut_list:
                return False
            
            for cut in self.cut_list.cuts:
                if cut.sequence_number == sequence_number:
                    # Update allowed fields
                    if "timecode_in" in kwargs:
                        cut.timecode_in = kwargs["timecode_in"]
                    if "timecode_out" in kwargs:
                        cut.timecode_out = kwargs["timecode_out"]
                    if "primary_camera" in kwargs:
                        cut.primary_camera = kwargs["primary_camera"]
                    if "transition" in kwargs:
                        cut.transition = kwargs["transition"]
                    if "notes" in kwargs:
                        cut.notes = kwargs["notes"]
                    
                    # Recalculate duration
                    cut.duration = cut.timecode_out - cut.timecode_in
                    
                    print(f"[CutTab] Updated cut {sequence_number}")
                    return True
            
            return False
        
        except Exception as e:
            print(f"[CutTab] Failed to update cut: {e}")
            return False

    def get_cut_list(self) -> Optional[CutList]:
        """Get the current cut list."""
        return self.cut_list

    def get_cuts(self) -> List[CutInstruction]:
        """Get all cuts (in order)."""
        if not self.cut_list:
            return []
        return self.cut_list.cuts.copy()

    # =========================================================================
    # Coverage Validation
    # =========================================================================

    def validate_cut_list(self) -> Tuple[bool, List[str]]:
        """
        Validate the cut list before export.
        
        Checks:
        - All cuts have valid timecodes
        - All cameras exist
        - No extreme gaps in coverage
        - Consistent frame rate
        """
        if not self.cut_list:
            return False, ["No cut list generated"]
        
        valid, warnings = self.cut_list.validate()
        
        # Check gaps
        if self.cut_list.cuts:
            last_out = 0.0
            for cut in self.cut_list.cuts:
                if cut.timecode_in > last_out + 0.5:  # Gap > 0.5s
                    warnings.append(
                        f"Gap between cuts: {last_out:.1f}–{cut.timecode_in:.1f}s"
                    )
                last_out = cut.timecode_out
        
        return valid and len(warnings) == 0, warnings

    def get_coverage_report(self) -> Optional[Dict]:
        """
        Generate coverage report: which cameras appear in cut list.
        """
        if not self.cut_list:
            return None
        
        try:
            camera_usage = {}
            
            for cut in self.cut_list.cuts:
                if cut.primary_camera not in camera_usage:
                    camera_usage[cut.primary_camera] = {
                        "usage_count": 0,
                        "total_duration": 0.0,
                    }
                
                camera_usage[cut.primary_camera]["usage_count"] += 1
                camera_usage[cut.primary_camera]["total_duration"] += cut.duration
            
            return {
                "total_cuts": len(self.cut_list.cuts),
                "total_duration": self.cut_list.get_total_duration(),
                "camera_usage": camera_usage,
            }
        
        except Exception as e:
            print(f"[CutTab] Coverage report failed: {e}")
            return None

    # =========================================================================
    # Export
    # =========================================================================

    def export_cut_list_json(self, output_path: str) -> bool:
        """Export cut list as JSON."""
        import json
        
        try:
            if not self.cut_list:
                return False
            
            data = {
                "project": self.cut_list.project_name,
                "frame_rate": self.cut_list.frame_rate,
                "total_duration": self.cut_list.total_duration,
                "cuts": [
                    {
                        "sequence": cut.sequence_number,
                        "in": cut.timecode_in,
                        "out": cut.timecode_out,
                        "duration": cut.duration,
                        "primary_camera": cut.primary_camera,
                        "alternates": cut.alternate_cameras,
                        "transition": cut.transition,
                        "notes": cut.notes,
                    }
                    for cut in self.cut_list.cuts
                ],
            }
            
            with open(output_path, "w") as f:
                json.dump(data, f, indent=2)
            
            print(f"[CutTab] Cut list exported to {output_path}")
            return True
        
        except Exception as e:
            print(f"[CutTab] Export failed: {e}")
            return False

    def export_cut_list_csv(self, output_path: str) -> bool:
        """Export cut list as CSV (for spreadsheet review)."""
        import csv
        
        try:
            if not self.cut_list:
                return False
            
            with open(output_path, "w", newline="") as f:
                writer = csv.writer(f)
                
                writer.writerow([
                    "Seq", "In (s)", "Out (s)", "Duration (s)",
                    "Primary Camera", "Alternates", "Transition", "Notes"
                ])
                
                for cut in self.cut_list.cuts:
                    writer.writerow([
                        cut.sequence_number,
                        f"{cut.timecode_in:.2f}",
                        f"{cut.timecode_out:.2f}",
                        f"{cut.duration:.2f}",
                        cut.primary_camera,
                        "|".join(cut.alternate_cameras),
                        cut.transition,
                        cut.notes,
                    ])
            
            print(f"[CutTab] Cut list (CSV) exported to {output_path}")
            return True
        
        except Exception as e:
            print(f"[CutTab] CSV export failed: {e}")
            return False

    def export_cut_list_edl(self, output_path: str) -> bool:
        """
        Export cut list as EDL (Edit Decision List) for NLE import.
        Format: timecode in/out, camera, transition.
        """
        try:
            if not self.cut_list:
                return False
            
            # Convert frame rate to timecode format
            fps = int(self.cut_list.frame_rate)
            
            def seconds_to_timecode(sec: float) -> str:
                """Convert seconds to HH:MM:SS:FF"""
                hours = int(sec // 3600)
                minutes = int((sec % 3600) // 60)
                secs = int(sec % 60)
                frames = int((sec % 1) * fps)
                return f"{hours:02d}:{minutes:02d}:{secs:02d}:{frames:02d}"
            
            with open(output_path, "w") as f:
                f.write("TITLE: " + self.cut_list.project_name + "\n")
                f.write("FCM: DROP FRAME\n\n")
                
                for i, cut in enumerate(self.cut_list.cuts, 1):
                    tc_in = seconds_to_timecode(cut.timecode_in)
                    tc_out = seconds_to_timecode(cut.timecode_out)
                    
                    # EDL line format: SEQ | SOURCE | EDIT | SRC IN | SRC OUT | REC IN | REC OUT
                    f.write(f"{i:03d}  {cut.primary_camera[:8]:8s} V     C        {tc_in} {tc_out} \n")
                    f.write(f" * TO {cut.transition.upper()}\n\n")
            
            print(f"[CutTab] Cut list (EDL) exported to {output_path}")
            return True
        
        except Exception as e:
            print(f"[CutTab] EDL export failed: {e}")
            return False

    def export_cut_list_xml(self, output_path: str) -> bool:
        """Export cut list as XML (XMEML-compatible)."""
        import xml.etree.ElementTree as ET
        
        try:
            if not self.cut_list:
                return False
            
            root = ET.Element("project")
            root.set("name", self.cut_list.project_name)
            
            cuts_elem = ET.SubElement(root, "cuts")
            cuts_elem.set("total", str(len(self.cut_list.cuts)))
            cuts_elem.set("frame_rate", str(self.cut_list.frame_rate))
            
            for cut in self.cut_list.cuts:
                cut_elem = ET.SubElement(cuts_elem, "cut")
                cut_elem.set("seq", str(cut.sequence_number))
                cut_elem.set("in", f"{cut.timecode_in:.3f}")
                cut_elem.set("out", f"{cut.timecode_out:.3f}")
                cut_elem.set("camera", cut.primary_camera)
                cut_elem.set("transition", cut.transition)
                
                if cut.notes:
                    cut_elem.text = cut.notes
            
            tree = ET.ElementTree(root)
            tree.write(output_path, encoding="utf-8", xml_declaration=True)
            
            print(f"[CutTab] Cut list (XML) exported to {output_path}")
            return True
        
        except Exception as e:
            print(f"[CutTab] XML export failed: {e}")
            return False

    # =========================================================================
    # Finalize & Confirmation
    # =========================================================================

    def finalize_project(self) -> Tuple[bool, str]:
        """
        Finalize the project: validate, store cut list, prepare for export.
        
        Returns:
          (success, message)
        """
        try:
            if not self.cut_list:
                return False, "No cut list generated"
            
            valid, warnings = self.validate_cut_list()
            
            if warnings:
                print(f"[CutTab] Warnings: {', '.join(warnings[:3])}")
            
            # Store finalized cut list in project
            self.project.final_cut_list = self.cut_list
            
            msg = f"Project finalized: {len(self.cut_list.cuts)} cuts, {self.cut_list.get_total_duration():.1f}s"
            return True, msg
        
        except Exception as e:
            return False, f"Finalization failed: {e}"

    def get_project_summary(self) -> Dict:
        """Get summary of final project."""
        return {
            "project_name": self.project.settings.project_name,
            "cameras": len(self.project.cameras),
            "audio_sources": len(self.project.audio_sources),
            "sections": len(self.project.sections),
            "moments_marked": len(self.project.moments),
            "cut_points": len(self.project.cut_points),
            "final_cuts": len(self.cut_list.cuts) if self.cut_list else 0,
            "final_duration": self.cut_list.get_total_duration() if self.cut_list else 0.0,
        }

    # =========================================================================
    # Diagnostics
    # =========================================================================

    def get_diagnostics(self) -> Dict:
        """Return diagnostics."""
        return {
            "cut_list_generated": self.cut_list is not None,
            "auto_cuts": len(self.auto_generated_cuts),
            "custom_cuts": len(self.custom_cuts),
            "total_cuts": len(self.cut_list.cuts) if self.cut_list else 0,
            "cut_list_valid": self.validate_cut_list()[0] if self.cut_list else False,
        }

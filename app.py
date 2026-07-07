"""Transient AI: Complete event video editing automation system.

Main application entry point and orchestration.
Integrates all tabs, engine modules, and data models.
"""

import sys
import os
from pathlib import Path
from typing import Optional

# PyQt5 imports
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QVBoxLayout, QHBoxLayout,
    QWidget, QLabel, QPushButton, QStatusBar, QMenuBar, QMenu, QFileDialog,
    QMessageBox, QProgressBar, QSplitter
)
from PyQt5.QtCore import Qt, QSize, pyqtSignal, QObject, QThread
from PyQt5.QtGui import QIcon, QFont

# Local imports
from models.project import ProjectState, ProjectSettings
from ui.tabs.intake_tab import IntakeTab
from ui.tabs.sync_tab import SyncTab
from ui.tabs.audio_tab import AudioTab
from ui.tabs.analysis_tab import AnalysisTab
from ui.tabs.cut_tab import CutTab

from engine.sync_manager import SyncXMLParser, SyncOffsetComputer, ClipMapper
from engine.audio_analysis import AudioAnalyzer, BeatDetector, EnergyDetector
from engine.project_manager import ProjectManager


class WorkerSignals(QObject):
    """Signals for background tasks."""
    progress = pyqtSignal(str)
    finished = pyqtSignal(bool, str)
    error = pyqtSignal(str)


class TransientAIApp(QMainWindow):
    """
    Transient AI: Main application window.
    
    Workflow:
    1. Intake Tab — load footage and audio
    2. Sync Tab — establish sync (XMEML or manual)
    3. Audio Tab — analyze audio, mark sections
    4. Analysis Tab — mark moments and cut points
    5. Cut Tab — generate and finalize cut list
    6. Export — to NLE (EDL, XML, JSON)
    """

    def __init__(self):
        super().__init__()
        
        self.project = ProjectState()
        self.project_manager = ProjectManager()
        
        # Initialize UI
        self.setWindowTitle("Transient AI — Event Video Editing Automation")
        self.setWindowIcon(self._create_icon())
        self.setGeometry(100, 100, 1600, 900)
        
        # Create central widget and layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # Create menu bar
        self._create_menu_bar()
        
        # Create status bar
        self.status_bar = self.statusBar()
        self.status_bar.showMessage("Ready")
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        
        # Initialize tabs
        self.intake_tab = IntakeTabUI(self.project)
        self.sync_tab = SyncTabUI(self.project)
        self.audio_tab = AudioTabUI(self.project)
        self.analysis_tab = AnalysisTabUI(self.project)
        self.cut_tab = CutTabUI(self.project)
        
        # Add tabs
        self.tab_widget.addTab(self.intake_tab, "1. Intake")
        self.tab_widget.addTab(self.sync_tab, "2. Sync")
        self.tab_widget.addTab(self.audio_tab, "3. Audio")
        self.tab_widget.addTab(self.analysis_tab, "4. Analysis")
        self.tab_widget.addTab(self.cut_tab, "5. Cut")
        
        layout.addWidget(self.tab_widget)
        
        # Connect signals
        self._connect_signals()

    def _create_menu_bar(self):
        """Create application menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("File")
        
        new_action = file_menu.addAction("New Project")
        new_action.triggered.connect(self.new_project)
        
        open_action = file_menu.addAction("Open Project")
        open_action.triggered.connect(self.open_project)
        
        save_action = file_menu.addAction("Save Project")
        save_action.triggered.connect(self.save_project)
        
        save_as_action = file_menu.addAction("Save Project As...")
        save_as_action.triggered.connect(self.save_project_as)
        
        file_menu.addSeparator()
        
        export_menu = file_menu.addMenu("Export Cut List")
        export_menu.addAction("Export as JSON", lambda: self.export_cut_list("json"))
        export_menu.addAction("Export as CSV", lambda: self.export_cut_list("csv"))
        export_menu.addAction("Export as EDL", lambda: self.export_cut_list("edl"))
        export_menu.addAction("Export as XML", lambda: self.export_cut_list("xml"))
        
        file_menu.addSeparator()
        
        exit_action = file_menu.addAction("Exit")
        exit_action.triggered.connect(self.close)
        
        # Edit menu
        edit_menu = menubar.addMenu("Edit")
        edit_menu.addAction("Project Settings", self.show_project_settings)
        
        # Help menu
        help_menu = menubar.addMenu("Help")
        help_menu.addAction("About", self.show_about)
        help_menu.addAction("Documentation", self.show_documentation)

    def _connect_signals(self):
        """Connect signals between tabs and main window."""
        pass

    def _create_icon(self) -> QIcon:
        """Create a simple application icon."""
        # Placeholder: use system default
        return QIcon()

    def new_project(self):
        """Create a new project."""
        self.project = ProjectState()
        self.status_bar.showMessage("New project created")
        self.intake_tab.refresh()

    def open_project(self):
        """Open an existing project."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Project", "", "Transient Projects (*.transient);;All Files (*)"
        )
        
        if not file_path:
            return
        
        try:
            self.project = self.project_manager.load_project(file_path)
            self.status_bar.showMessage(f"Loaded: {file_path}")
            self._refresh_all_tabs()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open project: {e}")

    def save_project(self):
        """Save the current project."""
        if not self.project.settings.project_name:
            self.save_project_as()
            return
        
        try:
            file_path = self.project_manager.save_project(self.project)
            self.status_bar.showMessage(f"Saved: {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save project: {e}")

    def save_project_as(self):
        """Save project with a new name."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Project As", "", "Transient Projects (*.transient)"
        )
        
        if not file_path:
            return
        
        try:
            self.project.settings.project_name = Path(file_path).stem
            self.project_manager.save_project(self.project, file_path)
            self.status_bar.showMessage(f"Saved: {file_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save project: {e}")

    def export_cut_list(self, format_type: str):
        """Export cut list in various formats."""
        if not self.cut_tab.cut_list:
            QMessageBox.warning(self, "No Cut List", "Please generate a cut list first (Cut tab)")
            return
        
        filter_map = {
            "json": "JSON Files (*.json)",
            "csv": "CSV Files (*.csv)",
            "edl": "EDL Files (*.edl)",
            "xml": "XML Files (*.xml)",
        }
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, f"Export as {format_type.upper()}", "",
            filter_map.get(format_type, "All Files (*)")
        )
        
        if not file_path:
            return
        
        try:
            if format_type == "json":
                success = self.cut_tab.export_cut_list_json(file_path)
            elif format_type == "csv":
                success = self.cut_tab.export_cut_list_csv(file_path)
            elif format_type == "edl":
                success = self.cut_tab.export_cut_list_edl(file_path)
            elif format_type == "xml":
                success = self.cut_tab.export_cut_list_xml(file_path)
            else:
                success = False
            
            if success:
                QMessageBox.information(self, "Success", f"Exported to {file_path}")
                self.status_bar.showMessage(f"Exported: {file_path}")
            else:
                QMessageBox.critical(self, "Error", "Export failed")
        
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Export failed: {e}")

    def show_project_settings(self):
        """Show project settings dialog."""
        from ui.dialogs.project_settings_dialog import ProjectSettingsDialog
        dialog = ProjectSettingsDialog(self.project, self)
        if dialog.exec_():
            self.status_bar.showMessage("Project settings updated")

    def show_about(self):
        """Show about dialog."""
        QMessageBox.information(
            self,
            "About Transient AI",
            "Transient AI — Event Video Editing Automation\n\n"
            "Version 1.0\n\n"
            "Automates multi-camera event video editing with intelligent camera selection, "
            "audio analysis, and cut list generation.\n\n"
            "© 2026 Transient AI"
        )

    def show_documentation(self):
        """Show documentation."""
        import webbrowser
        webbrowser.open("https://github.com/adham321321/transient-ai")

    def _refresh_all_tabs(self):
        """Refresh all tabs with new project data."""
        self.intake_tab.refresh()
        self.sync_tab.refresh()
        self.audio_tab.refresh()
        self.analysis_tab.refresh()
        self.cut_tab.refresh()

    def closeEvent(self, event):
        """Handle application close."""
        if self.project.cameras or self.project.audio_sources:
            reply = QMessageBox.question(
                self,
                "Unsaved Changes",
                "Project has changes. Save before closing?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel
            )
            
            if reply == QMessageBox.Save:
                self.save_project()
                event.accept()
            elif reply == QMessageBox.Discard:
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


# ============================================================================
# Tab UI Implementations
# ============================================================================

class IntakeTabUI(QWidget):
    """UI for Intake Tab."""
    
    def __init__(self, project: ProjectState):
        super().__init__()
        self.project = project
        self.intake_tab = IntakeTab(project)
        self._create_ui()
    
    def _create_ui(self):
        """Create UI elements."""
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel("Intake — Load Cameras, Audio, and Project Settings")
        title_font = title.font()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        import_footage_btn = QPushButton("Import Footage Folder")
        import_footage_btn.clicked.connect(self.import_footage)
        button_layout.addWidget(import_footage_btn)
        
        import_audio_btn = QPushButton("Import Audio File")
        import_audio_btn.clicked.connect(self.import_audio)
        button_layout.addWidget(import_audio_btn)
        
        layout.addLayout(button_layout)
        
        # Status
        self.status_label = QLabel("No footage loaded")
        layout.addWidget(self.status_label)
        
        layout.addStretch()
    
    def import_footage(self):
        """Import footage folder."""
        from PyQt5.QtWidgets import QFileDialog
        folder = QFileDialog.getExistingDirectory(self, "Select Footage Folder")
        
        if folder:
            result = self.intake_tab.import_footage_folder(folder)
            self.status_label.setText(
                f"Imported {result.file_count} files, {len(result.cameras_added)} cameras"
            )
            if result.errors:
                for error in result.errors:
                    print(f"[IntakeTab] {error}")
    
    def import_audio(self):
        """Import audio file."""
        from PyQt5.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Audio File", "",
            "Audio Files (*.wav *.mp3 *.aiff *.aac);;All Files (*)"
        )
        
        if file_path:
            success = self.intake_tab.import_audio_file(file_path)
            if success:
                self.status_label.setText(f"Added audio: {Path(file_path).name}")
    
    def refresh(self):
        """Refresh UI."""
        pass


class SyncTabUI(QWidget):
    """UI for Sync Tab."""
    
    def __init__(self, project: ProjectState):
        super().__init__()
        self.project = project
        self.sync_tab = SyncTab(project)
        self._create_ui()
    
    def _create_ui(self):
        """Create UI elements."""
        layout = QVBoxLayout(self)
        
        title = QLabel("Sync — Establish Camera-to-Audio Synchronization")
        title_font = title.font()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)
        
        button_layout = QHBoxLayout()
        
        import_xmeml_btn = QPushButton("Import XMEML")
        import_xmeml_btn.clicked.connect(self.import_xmeml)
        button_layout.addWidget(import_xmeml_btn)
        
        auto_sync_btn = QPushButton("Auto-Compute Offsets")
        auto_sync_btn.clicked.connect(self.auto_sync)
        button_layout.addWidget(auto_sync_btn)
        
        layout.addLayout(button_layout)
        
        self.status_label = QLabel("No sync established")
        layout.addWidget(self.status_label)
        
        layout.addStretch()
    
    def import_xmeml(self):
        """Import XMEML file."""
        from PyQt5.QtWidgets import QFileDialog
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select XMEML File", "", "XMEML Files (*.xml);;All Files (*)"
        )
        
        if file_path:
            success, msg = self.sync_tab.import_xmeml(file_path)
            self.status_label.setText(msg)
    
    def auto_sync(self):
        """Auto-compute offsets."""
        if not self.sync_tab.parser:
            self.status_label.setText("No XMEML loaded")
            return
        
        success, offsets = self.sync_tab.auto_compute_offsets()
        if success:
            self.status_label.setText(f"Auto-sync complete: {len(offsets)} cameras")
    
    def refresh(self):
        """Refresh UI."""
        pass


class AudioTabUI(QWidget):
    """UI for Audio Tab."""
    
    def __init__(self, project: ProjectState):
        super().__init__()
        self.project = project
        self.audio_tab = AudioTab(project)
        self._create_ui()
    
    def _create_ui(self):
        """Create UI elements."""
        layout = QVBoxLayout(self)
        
        title = QLabel("Audio — Analyze and Mark Sections")
        title_font = title.font()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)
        
        button_layout = QHBoxLayout()
        
        analyze_btn = QPushButton("Analyze Audio")
        analyze_btn.clicked.connect(self.analyze_audio)
        button_layout.addWidget(analyze_btn)
        
        suggest_sections_btn = QPushButton("Suggest Sections")
        suggest_sections_btn.clicked.connect(self.suggest_sections)
        button_layout.addWidget(suggest_sections_btn)
        
        layout.addLayout(button_layout)
        
        self.status_label = QLabel("No audio analyzed")
        layout.addWidget(self.status_label)
        
        layout.addStretch()
    
    def analyze_audio(self):
        """Analyze audio."""
        count, errors = self.audio_tab.analyze_all_audio()
        self.status_label.setText(f"Analyzed {count} tracks")
        if errors:
            print("Errors:", errors)
    
    def suggest_sections(self):
        """Suggest sections."""
        if not self.project.audio_sources:
            self.status_label.setText("No audio sources")
            return
        
        audio_name = self.project.audio_sources[0].name
        suggestions = self.audio_tab.suggest_sections(audio_name)
        count = self.audio_tab.accept_suggested_sections(suggestions)
        self.status_label.setText(f"Marked {count} sections")
    
    def refresh(self):
        """Refresh UI."""
        pass


class AnalysisTabUI(QWidget):
    """UI for Analysis Tab."""
    
    def __init__(self, project: ProjectState):
        super().__init__()
        self.project = project
        self.analysis_tab = AnalysisTab(project)
        self._create_ui()
    
    def _create_ui(self):
        """Create UI elements."""
        layout = QVBoxLayout(self)
        
        title = QLabel("Analysis — Mark Moments and Define Cut Points")
        title_font = title.font()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)
        
        button_layout = QHBoxLayout()
        
        populate_moments_btn = QPushButton("Populate Moments from Audio")
        populate_moments_btn.clicked.connect(self.populate_moments)
        button_layout.addWidget(populate_moments_btn)
        
        populate_cut_points_btn = QPushButton("Populate Cut Points from Sections")
        populate_cut_points_btn.clicked.connect(self.populate_cut_points)
        button_layout.addWidget(populate_cut_points_btn)
        
        layout.addLayout(button_layout)
        
        self.status_label = QLabel("No analysis data")
        layout.addWidget(self.status_label)
        
        layout.addStretch()
    
    def populate_moments(self):
        """Populate moments from audio."""
        count = self.analysis_tab.populate_moments_from_analysis()
        self.status_label.setText(f"Marked {count} moments")
    
    def populate_cut_points(self):
        """Populate cut points from sections."""
        count = self.analysis_tab.populate_cut_points_from_sections()
        self.status_label.setText(f"Defined {count} cut points")
    
    def refresh(self):
        """Refresh UI."""
        pass


class CutTabUI(QWidget):
    """UI for Cut Tab."""
    
    def __init__(self, project: ProjectState):
        super().__init__()
        self.project = project
        self.cut_tab = CutTab(project)
        self.cut_list = None
        self._create_ui()
    
    def _create_ui(self):
        """Create UI elements."""
        layout = QVBoxLayout(self)
        
        title = QLabel("Cut — Generate and Finalize Cut List")
        title_font = title.font()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title.setFont(title_font)
        layout.addWidget(title)
        
        button_layout = QHBoxLayout()
        
        generate_btn = QPushButton("Generate Auto Cut List")
        generate_btn.clicked.connect(self.generate_cut_list)
        button_layout.addWidget(generate_btn)
        
        finalize_btn = QPushButton("Finalize Project")
        finalize_btn.clicked.connect(self.finalize_project)
        button_layout.addWidget(finalize_btn)
        
        layout.addLayout(button_layout)
        
        self.status_label = QLabel("No cut list generated")
        layout.addWidget(self.status_label)
        
        layout.addStretch()
    
    def generate_cut_list(self):
        """Generate cut list."""
        success, msg = self.cut_tab.generate_auto_cut_list()
        self.status_label.setText(msg)
        if success:
            self.cut_list = self.cut_tab.cut_list
    
    def finalize_project(self):
        """Finalize project."""
        if not self.cut_list:
            self.status_label.setText("Generate cut list first")
            return
        
        success, msg = self.cut_tab.finalize_project()
        self.status_label.setText(msg)
    
    def export_cut_list_json(self, file_path: str) -> bool:
        """Export cut list as JSON."""
        return self.cut_tab.export_cut_list_json(file_path)
    
    def export_cut_list_csv(self, file_path: str) -> bool:
        """Export cut list as CSV."""
        return self.cut_tab.export_cut_list_csv(file_path)
    
    def export_cut_list_edl(self, file_path: str) -> bool:
        """Export cut list as EDL."""
        return self.cut_tab.export_cut_list_edl(file_path)
    
    def export_cut_list_xml(self, file_path: str) -> bool:
        """Export cut list as XML."""
        return self.cut_tab.export_cut_list_xml(file_path)
    
    def refresh(self):
        """Refresh UI."""
        pass


def main():
    """Main entry point."""
    app = QApplication(sys.argv)
    window = TransientAIApp()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

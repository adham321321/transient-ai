"""Main window orchestration for six-tab workflow."""

from PyQt5.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QTabWidget
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon

from models.project import ProjectState, ProjectSettings

# Placeholder imports; these will be built in subsequent steps
# from ui.tabs.intake import IntakeTab
# from ui.tabs.sync import SyncTab
# from ui.tabs.audio import AudioTab
# from ui.tabs.analysis import AnalysisTab
# from ui.tabs.cut import CutTab
# from ui.tabs.deliver import DeliverTab


class MainWindow(QMainWindow):
    """Main application window with tabbed workflow."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Transient AI — Multicam DJ/Nightlife Editing")
        self.setGeometry(100, 100, 1400, 900)
        
        # Initialize project state
        self.project = ProjectState(
            settings=ProjectSettings(
                project_name="Untitled Project",
                native_resolution=(1920, 1080),
                frame_rate=25.0,
            )
        )
        
        # Build tab widget
        self.tabs = QTabWidget()
        self.setup_tabs()
        
        # Central widget
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.addWidget(self.tabs)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setCentralWidget(container)

    def setup_tabs(self):
        """Initialize all six tabs (stubs for now)."""
        tab_names = [
            "Intake",
            "Sync",
            "Audio",
            "Analysis",
            "Cut",
            "Deliver",
        ]
        
        for name in tab_names:
            # Placeholder: will be replaced with actual tab classes
            tab_widget = QWidget()
            layout = QVBoxLayout(tab_widget)
            layout.addWidget(QWidget())  # Empty for now
            self.tabs.addTab(tab_widget, name)

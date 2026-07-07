"""Dark theme stylesheet for Transient AI."""

DARK_STYLESHEET = """
QMainWindow {
    background-color: #0e0e12;
    color: #ffffff;
}

QTabWidget::pane {
    border: none;
}

QTabBar::tab {
    background-color: #17181c;
    color: #888888;
    padding: 8px 20px;
    margin-right: 4px;
    border: none;
    border-radius: 4px;
}

QTabBar::tab:selected {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                              stop:0 #6c4bff, stop:1 #8f6bff);
    color: #ffffff;
}

QWidget {
    background-color: #0e0e12;
    color: #ffffff;
}

QGroupBox {
    color: #999999;
    border: 1px solid #2a2a30;
    border-radius: 6px;
    padding-top: 12px;
    margin-top: 10px;
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 1px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 4px;
}

QPushButton {
    background-color: #6c4bff;
    color: #ffffff;
    border: none;
    border-radius: 4px;
    padding: 8px 16px;
    font-weight: bold;
}

QPushButton:hover {
    background-color: #7d5fff;
}

QPushButton:pressed {
    background-color: #5a3ae0;
}

QPushButton.secondary {
    background-color: #2a2a30;
    border: 1px solid #444444;
    color: #cccccc;
}

QPushButton.secondary:hover {
    background-color: #333338;
}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #1a1a20;
    color: #ffffff;
    border: 1px solid #333333;
    border-radius: 4px;
    padding: 6px;
}

QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border: 1px solid #6c4bff;
}

QSlider::groove:horizontal {
    background-color: #2a2a30;
    border-radius: 4px;
    height: 6px;
}

QSlider::handle:horizontal {
    background-color: #ffffff;
    border: none;
    width: 16px;
    margin: -5px 0;
    border-radius: 8px;
}

QSlider::sub-page:horizontal {
    background-color: #6c4bff;
}

QLabel {
    color: #ffffff;
}

QLabel.helper {
    color: #777777;
    font-size: 10px;
}

QLabel.section-label {
    color: #999999;
    font-size: 10px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 1px;
}

QCheckBox {
    color: #ffffff;
    spacing: 8px;
}

QCheckBox::indicator:unchecked {
    background-color: #1a1a20;
    border: 1px solid #333333;
    border-radius: 3px;
}

QCheckBox::indicator:checked {
    background-color: #6c4bff;
    border: 1px solid #6c4bff;
    border-radius: 3px;
}

QScrollBar:vertical {
    background-color: #0e0e12;
    width: 12px;
    border: none;
}

QScrollBar::handle:vertical {
    background-color: #444444;
    border-radius: 6px;
    min-height: 20px;
}

QScrollBar::handle:vertical:hover {
    background-color: #555555;
}
"""

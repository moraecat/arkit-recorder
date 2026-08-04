# arkit_recorder/qt/app.py
from __future__ import annotations

import sys

DARK_QSS = """
QWidget { background-color: #1e1f22; color: #e8e8e8; font-size: 13px; }
QMainWindow { background-color: #1e1f22; }
QPushButton {
    background-color: #33353a; border: 1px solid #45474d;
    border-radius: 4px; padding: 6px 10px;
}
QPushButton:hover { background-color: #3f4147; }
QPushButton:pressed { background-color: #2a2c30; }
QPushButton:disabled { color: #6a6a6a; background-color: #26272b; }
QListWidget {
    background-color: #26272b; border: 1px solid #3a3c42; border-radius: 4px;
}
QListWidget::item { padding: 4px; }
QListWidget::item:selected { background-color: #3d5a80; color: #ffffff; }
QComboBox, QLineEdit {
    background-color: #26272b; border: 1px solid #3a3c42;
    border-radius: 4px; padding: 4px;
}
QCheckBox { spacing: 6px; }
QDialog { background-color: #1e1f22; }
"""


def run_app(proxy, config, config_path) -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("PySide6가 설치되어 있지 않습니다. 설치: py -3.11 -m pip install PySide6")
        return 1
    from .main_window import MainWindow

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_QSS)
    window = MainWindow(proxy, config, config_path)
    window.show()
    return app.exec()

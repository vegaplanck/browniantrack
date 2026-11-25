import sys

from PySide6.QtWidgets import QApplication

from browniantrack.ui.main_window import MainWindow


def main() -> None:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    app.setApplicationName("BrownianTrack")
    window = MainWindow()
    window.show()
    app.exec()

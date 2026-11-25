import os
import unittest
from pathlib import Path

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.colors import to_hex
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from browniantrack.core.video_preview import PreviewResult
from browniantrack.ui.main_window import MainWindow


class QtMainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QApplication.instance() or QApplication([])

    def test_builds_qt_interface_and_matplotlib_canvas(self) -> None:
        window = MainWindow()
        try:
            self.assertEqual(window.windowTitle(), "BrownianTrack")
            self.assertIsNone(window.menuWidget())
            self.assertIsInstance(window.canvas, FigureCanvasQTAgg)
            self.assertFalse(window.analyze_interval_button.isEnabled())
            self.assertFalse(window.analyze_all_button.isEnabled())
        finally:
            window.close()
            self.application.processEvents()

    def test_seek_updates_frame_position_label(self) -> None:
        window = MainWindow()
        try:
            window.video_path = Path("sample.mp4")
            window.video_frame_count = 20
            window.video_frame_rate = 10
            window.position_scale.setMaximum(19)
            window.position_scale.setValue(2)

            self.assertEqual(window.current_frame_index, 2)
            self.assertEqual(window.frame_label.text(), "Quadro: 3 / 20")
        finally:
            window.close()
            self.application.processEvents()

    def test_interval_unit_conversion_preserves_time(self) -> None:
        window = MainWindow()
        try:
            window.video_path = Path("sample.mp4")
            window.video_frame_count = 100
            window.video_frame_rate = 10
            window.interval_start_edit.setText("11")
            window.interval_end_edit.setText("21")
            window.interval_unit_box.setCurrentText("Segundos")

            self.assertEqual(window.interval_start_edit.text(), "1")
            self.assertEqual(window.interval_end_edit.text(), "2")
        finally:
            window.close()
            self.application.processEvents()

    def test_theme_toggle_updates_qt_palette_and_plot(self) -> None:
        window = MainWindow()
        try:
            window.resize(1000, 700)
            window.show()
            self.application.processEvents()
            self.assertFalse(window.dark_mode)
            self.assertEqual(
                window.toolBarArea(window.appearance_toolbar),
                Qt.ToolBarArea.TopToolBarArea,
            )
            self.assertEqual(window.sun_icon.text(), "☀")
            self.assertEqual(window.moon_icon.text(), "☾")
            self.assertGreater(
                window.theme_control.geometry().center().x(),
                window.appearance_toolbar.width() // 2,
            )
            self.assertEqual(self.application.styleSheet(), "")
            self.assertEqual(
                self.application.palette()
                .color(QPalette.ColorRole.Window)
                .name(),
                "#f4f5f7",
            )

            window.theme_switch.setChecked(True)
            self.assertTrue(window.dark_mode)
            self.assertEqual(
                self.application.palette()
                .color(QPalette.ColorRole.Window)
                .name(),
                "#202124",
            )
            self.assertEqual(to_hex(window.figure.get_facecolor()), "#202124")

            frame = np.zeros((8, 8, 3), dtype=np.uint8)
            window.video_frame_count = 1
            window._display_preview(
                PreviewResult(0, color_frame=frame, grayscale_frame=frame)
            )
            self.assertEqual(to_hex(window.axes.get_facecolor()), "#202124")

            window.theme_switch.setChecked(False)
            self.assertFalse(window.dark_mode)
            self.assertEqual(to_hex(window.figure.get_facecolor()), "#f4f5f7")
        finally:
            window.close()
            self.application.processEvents()


if __name__ == "__main__":
    unittest.main()

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np
import pandas as pd

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.colors import to_hex
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QProgressBar,
    QTabWidget,
    QTableView,
)

from browniantrack.core.video_preview import PreviewResult
from browniantrack.ui.main_window import (
    MainWindow,
    PhysicalReportDialog,
    TrackingDataDialog,
)


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
            self.assertEqual(window.tracking_data_button.text(), "Dados de Tracking")
            self.assertFalse(window.tracking_data_button.isEnabled())
            self.assertFalse(window.visualize_plot_button.isEnabled())
            self.assertEqual(window.calculate_physical_button.text(), "Calcular Grandezas")
            self.assertFalse(window.calculate_physical_button.isEnabled())
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

    def test_result_actions_unlock_only_after_nonempty_analysis(self) -> None:
        window = MainWindow()
        tracking_data = pd.DataFrame(
            {
                "frame": [0, 1],
                "particle": [0, 0],
                "x": [1.0, 2.0],
                "y": [2.0, 3.0],
            }
        )
        buttons = (
            window.tracking_data_button,
            window.visualize_plot_button,
            window.calculate_physical_button,
        )
        try:
            self.assertTrue(all(not button.isEnabled() for button in buttons))

            window.analysis_in_progress = True
            window.results = tracking_data
            window._update_result_actions()
            self.assertTrue(all(not button.isEnabled() for button in buttons))

            window.analysis_in_progress = False
            window._analysis_finished(tracking_data)
            self.assertTrue(all(button.isEnabled() for button in buttons))
        finally:
            window.close()
            self.application.processEvents()

    def test_analysis_progress_bar_displays_current_frame(self) -> None:
        window = MainWindow()
        window.video_path = Path("sample.mp4")
        window.video_frame_count = 120
        try:
            with patch("browniantrack.ui.main_window.threading.Thread") as thread:
                window._start_analysis(40, 59)

            thread.return_value.start.assert_called_once()
            progress_bar = window.analysis_progress_bar
            self.assertIsInstance(progress_bar, QProgressBar)
            self.assertFalse(progress_bar.isHidden())
            window._queue_analysis_progress(7, 20)
            window._poll_analysis_progress()

            self.assertEqual(progress_bar.value(), 7)
            self.assertEqual(progress_bar.maximum(), 20)
            self.assertEqual(progress_bar.text(), "Quadro 47 de 120 (35%)")
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
            disabled_button_palette = window.tracking_data_button.palette()
            self.assertEqual(
                disabled_button_palette.color(
                    QPalette.ColorGroup.Disabled,
                    QPalette.ColorRole.Button,
                ).name(),
                "#dfe2e6",
            )
            self.assertEqual(
                disabled_button_palette.color(
                    QPalette.ColorGroup.Disabled,
                    QPalette.ColorRole.ButtonText,
                ).name(),
                "#767b82",
            )

            window.theme_switch.setChecked(True)
            self.assertTrue(window.dark_mode)
            self.assertEqual(
                self.application.palette()
                .color(QPalette.ColorRole.Window)
                .name(),
                "#202124",
            )
            self.assertEqual(
                window.tracking_data_button.palette()
                .color(
                    QPalette.ColorGroup.Disabled,
                    QPalette.ColorRole.Button,
                )
                .name(),
                "#303134",
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

    def test_visualize_plot_opens_matplotlib_toolbar_dialog(self) -> None:
        window = MainWindow()
        window.results = pd.DataFrame(
            {
                "frame": [0, 1, 0, 1],
                "particle": [0, 0, 1, 1],
                "x": [1.0, 2.0, 2.0, 3.0],
                "y": [2.0, 3.0, 1.0, 2.0],
            }
        )
        active_dialogs: list[QDialog | None] = []

        def capture_and_close_dialog() -> None:
            dialog = QApplication.activeModalWidget()
            active_dialogs.append(dialog if isinstance(dialog, QDialog) else None)
            if dialog is not None:
                dialog.close()

        try:
            self.assertEqual(window.visualize_plot_button.text(), "Visualizar gráfico")
            QTimer.singleShot(0, capture_and_close_dialog)
            window._show_trajectory_plot()

            self.assertEqual(len(active_dialogs), 1)
            dialog = active_dialogs[0]
            self.assertIsInstance(dialog, QDialog)
            assert dialog is not None
            self.assertIsInstance(
                dialog.findChild(FigureCanvasQTAgg),
                FigureCanvasQTAgg,
            )
            self.assertIsInstance(
                dialog.findChild(NavigationToolbar2QT),
                NavigationToolbar2QT,
            )
            toolbar = dialog.findChild(NavigationToolbar2QT)
            assert toolbar is not None
            self.assertIn("Save", [action.text() for action in toolbar.actions()])
        finally:
            window.close()
            self.application.processEvents()

    def test_tracking_data_table_can_save_csv(self) -> None:
        window = MainWindow()
        tracking_data = pd.DataFrame(
            {
                "frame": [0, 1],
                "particle": [0, 0],
                "x": [1.0, 2.0],
                "y": [2.0, 3.0],
            }
        )
        with TemporaryDirectory() as directory:
            output_path = Path(directory) / "tracking.csv"
            selected_path = Path(directory) / "tracking"
            active_dialogs: list[TrackingDataDialog | None] = []

            def save_and_close_dialog() -> None:
                dialog = QApplication.activeModalWidget()
                if isinstance(dialog, TrackingDataDialog):
                    active_dialogs.append(dialog)
                    dialog.save_button.click()
                    dialog.close()
                else:
                    active_dialogs.append(None)

            try:
                window.results = tracking_data
                with patch(
                    "browniantrack.ui.main_window.QFileDialog.getSaveFileName",
                    return_value=(str(selected_path), ""),
                ):
                    QTimer.singleShot(0, save_and_close_dialog)
                    window._show_tracking_data()

                self.assertEqual(len(active_dialogs), 1)
                dialog = active_dialogs[0]
                self.assertIsInstance(dialog, TrackingDataDialog)
                assert dialog is not None
                self.assertEqual(dialog.save_button.text(), "Salvar CSV…")
                table = dialog.findChild(QTableView)
                self.assertIsNotNone(table)
                assert table is not None
                model = table.model()
                self.assertIsNotNone(model)
                assert model is not None
                self.assertEqual(model.rowCount(), 2)

                saved_data = pd.read_csv(output_path)
                pd.testing.assert_frame_equal(saved_data, tracking_data)
                self.assertEqual(
                    window.status.text(),
                    f"Dados de tracking salvos em {output_path}",
                )
            finally:
                window.close()
                self.application.processEvents()

    def test_physical_report_tables_can_save_xlsx(self) -> None:
        window = MainWindow()
        summary = pd.DataFrame(
            [
                {
                    "Grandeza": "Coeficiente de difusão",
                    "Valor": 0.5,
                    "Unidade": "px²/s",
                }
            ]
        )
        msd_curve = pd.DataFrame(
            [{"lag_frames": 1, "lag_time_s": 1.0, "pair_count": 2, "msd_px2": 4.0}]
        )
        with TemporaryDirectory() as directory:
            output_path = Path(directory) / "physical.xlsx"
            selected_path = Path(directory) / "physical"
            active_dialogs: list[PhysicalReportDialog | None] = []

            def save_and_close_dialog() -> None:
                dialog = QApplication.activeModalWidget()
                if isinstance(dialog, PhysicalReportDialog):
                    active_dialogs.append(dialog)
                    dialog.save_button.click()
                    dialog.close()
                else:
                    active_dialogs.append(None)

            try:
                with patch(
                    "browniantrack.ui.main_window.QFileDialog.getSaveFileName",
                    return_value=(str(selected_path), ""),
                ):
                    QTimer.singleShot(0, save_and_close_dialog)
                    window._show_physical_report(summary, msd_curve)

                self.assertEqual(len(active_dialogs), 1)
                dialog = active_dialogs[0]
                self.assertIsInstance(dialog, PhysicalReportDialog)
                assert dialog is not None
                tabs = dialog.findChild(QTabWidget)
                self.assertIsNotNone(tabs)
                self.assertEqual(tabs.count(), 2)
                self.assertEqual(dialog.save_button.text(), "Salvar planilha…")
                tables = dialog.findChildren(QTableView)
                table_models = [table.model() for table in tables]
                self.assertEqual(
                    [model.rowCount() for model in table_models if model is not None],
                    [1, 1],
                )

                with pd.ExcelFile(output_path) as workbook:
                    self.assertEqual(workbook.sheet_names, ["Resumo", "Curva MSD"])
                    report = pd.read_excel(workbook, sheet_name="Resumo")
                    curve = pd.read_excel(workbook, sheet_name="Curva MSD")
                self.assertIn("Coeficiente de difusão", report["Grandeza"].values)
                self.assertIn("msd_px2", curve.columns)
                self.assertEqual(
                    window.status.text(),
                    f"Planilha de grandezas salva em {output_path}",
                )
            finally:
                window.close()
                self.application.processEvents()


if __name__ == "__main__":
    unittest.main()

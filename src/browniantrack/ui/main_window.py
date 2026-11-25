import queue
import threading
from pathlib import Path

import pandas as pd
import trackpy as tp
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPoint,
    QRectF,
    QSignalBlocker,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import (
    QColor,
    QCloseEvent,
    QPainter,
    QPaintEvent,
    QPalette,
)
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSizePolicy,
    QTabWidget,
    QTableView,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from browniantrack.core.tracking import (
    TrackingSettings,
    analyze_video,
    calculate_physical_metrics,
    create_trajectory_figure,
    inspect_video,
    resolve_frame_range,
    write_physical_report_xlsx,
)
from browniantrack.core.video_preview import PreviewResult, VideoPreviewWorker


class ThemeSwitch(QCheckBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Alternar modo escuro")
        self.setAccessibleDescription(
            "Desativado: modo claro. Ativado: modo escuro."
        )
        self.setToolTip("Alternar entre os modos claro e escuro")
        self.setFixedSize(52, 30)

    def sizeHint(self) -> QSize:
        return QSize(52, 30)

    def hitButton(self, position: QPoint) -> bool:
        return self.rect().contains(position)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setClipRect(event.rect())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QRectF(1, 2, self.width() - 2, self.height() - 4)
        track_color = QColor("#8ab4f8" if self.isChecked() else "#9aa0a6")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)

        knob_size = track.height() - 6
        knob_x = (
            track.right() - knob_size - 3
            if self.isChecked()
            else track.left() + 3
        )
        knob = QRectF(
            knob_x,
            track.top() + 3,
            knob_size,
            knob_size,
        )
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(knob)

        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QColor("#1a73e8"))
            painter.drawRoundedRect(
                track.adjusted(-1, -1, 1, 1),
                track.height() / 2,
                track.height() / 2,
            )
        painter.end()


class DataFrameTableModel(QAbstractTableModel):
    def __init__(
        self,
        dataframe: pd.DataFrame,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._dataframe = dataframe

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._dataframe)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._dataframe.columns)

    def data(
        self,
        index: QModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> str | None:
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        value = self._dataframe.iat[index.row(), index.column()]
        return "" if pd.isna(value) else str(value)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> str | None:
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            if 0 <= section < len(self._dataframe.columns):
                return str(self._dataframe.columns[section])
            return None
        if 0 <= section < len(self._dataframe):
            return str(section + 1)
        return None


def _create_dataframe_table(dataframe: pd.DataFrame) -> QTableView:
    table = QTableView()
    table.setModel(DataFrameTableModel(dataframe, table))
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(
        QHeaderView.ResizeMode.ResizeToContents
    )
    table.horizontalHeader().setResizeContentsPrecision(100)
    table.horizontalHeader().setStretchLastSection(True)
    return table


class PhysicalReportDialog(QDialog):
    def __init__(
        self,
        summary: pd.DataFrame,
        msd_curve: pd.DataFrame,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Grandezas físicas")
        self.resize(900, 600)

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(_create_dataframe_table(summary), "Resumo")
        tabs.addTab(_create_dataframe_table(msd_curve), "Curva MSD")
        layout.addWidget(tabs)

        self.save_button = QPushButton("Salvar planilha…")
        layout.addWidget(self.save_button)


class TrackingDataDialog(QDialog):
    def __init__(
        self,
        tracking_data: pd.DataFrame,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Dados de Tracking")
        self.resize(1000, 650)

        layout = QVBoxLayout(self)
        layout.addWidget(_create_dataframe_table(tracking_data))

        self.save_button = QPushButton("Salvar CSV…")
        layout.addWidget(self.save_button)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("BrownianTrack")
        self.resize(1120, 760)
        self.setMinimumSize(820, 560)
        self.video_path: Path | None = None
        self.video_frame_count = 0
        self.video_frame_rate = 30.0
        self.current_frame_index = 0
        self.preview_worker: VideoPreviewWorker | None = None
        self.preview_in_flight = False
        self.playing = False
        self.current_preview: PreviewResult | None = None
        self.results: pd.DataFrame | None = None
        self.analysis_range: tuple[int, int] | None = None
        self.analysis_queue: queue.Queue[
            tuple[pd.DataFrame | None, Exception | None]
        ] = queue.Queue()
        self.analysis_progress_queue: queue.Queue[tuple[int, int]] = queue.Queue(
            maxsize=1
        )
        self.report_queue: queue.Queue[
            tuple[tuple[pd.DataFrame, pd.DataFrame] | None, Exception | None]
        ] = queue.Queue()
        self.analysis_in_progress = False
        self.report_in_progress = False
        self.applied_settings = TrackingSettings()
        self._previous_interval_unit = "Quadros"
        self.dark_mode = False

        self._build_ui()
        self._apply_theme(False)
        self._configure_timers()
        self._update_result_actions()

    def _build_ui(self) -> None:
        self.appearance_toolbar = QToolBar("Aparência", self)
        self.appearance_toolbar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.appearance_toolbar)

        spacer = QWidget()
        spacer.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self.appearance_toolbar.addWidget(spacer)
        theme_control = QWidget()
        theme_layout = QHBoxLayout(theme_control)
        theme_layout.setContentsMargins(8, 0, 8, 0)
        theme_layout.setSpacing(8)
        self.sun_icon = QLabel("☀")
        self.sun_icon.setAccessibleName("Modo claro")
        self.sun_icon.setToolTip("Modo claro")
        self.sun_icon.setStyleSheet("color: #e0a800; font-size: 15pt;")
        theme_layout.addWidget(self.sun_icon)
        self.theme_switch = ThemeSwitch()
        self.theme_switch.toggled.connect(self._apply_theme)
        theme_layout.addWidget(self.theme_switch)
        self.moon_icon = QLabel("☾")
        self.moon_icon.setAccessibleName("Modo escuro")
        self.moon_icon.setToolTip("Modo escuro")
        self.moon_icon.setStyleSheet("color: #718096; font-size: 15pt;")
        theme_layout.addWidget(self.moon_icon)
        self.theme_control = theme_control
        self.appearance_toolbar.addWidget(self.theme_control)

        body = QWidget()
        self.setCentralWidget(body)
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(12)

        controls_scroll = QScrollArea()
        controls_scroll.setWidgetResizable(True)
        controls_scroll.setMinimumWidth(300)
        controls_scroll.setMaximumWidth(340)
        body_layout.addWidget(controls_scroll)

        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(4, 4, 8, 4)
        controls_layout.setSpacing(8)
        controls_scroll.setWidget(controls)

        title = QLabel("BrownianTrack")
        title.setStyleSheet("font-size: 18pt; font-weight: bold;")
        controls_layout.addWidget(title)

        open_button = QPushButton("Abrir vídeo…")
        open_button.clicked.connect(lambda: self._open_video())
        controls_layout.addWidget(open_button)

        self.video_label = QLabel("Nenhum vídeo aberto")
        self.video_label.setWordWrap(True)
        controls_layout.addWidget(self.video_label)

        parameters = QGroupBox("Detecção trackpy")
        parameters_layout = QGridLayout(parameters)
        parameters_layout.addWidget(QLabel("Diâmetro (px, ímpar)"), 0, 0)
        self.diameter_edit = QLineEdit("11")
        self.diameter_edit.setMaximumWidth(100)
        parameters_layout.addWidget(self.diameter_edit, 0, 1)
        self.apply_diameter_button = QPushButton("Aplicar")
        self.apply_diameter_button.clicked.connect(lambda: self._apply_diameter())
        parameters_layout.addWidget(self.apply_diameter_button, 0, 2)
        parameters_layout.addWidget(QLabel("Massa mínima"), 1, 0)
        self.minmass_edit = QLineEdit("100")
        self.minmass_edit.setMaximumWidth(100)
        parameters_layout.addWidget(self.minmass_edit, 1, 1)
        self.apply_minmass_button = QPushButton("Aplicar")
        self.apply_minmass_button.clicked.connect(lambda: self._apply_minmass())
        parameters_layout.addWidget(self.apply_minmass_button, 1, 2)
        controls_layout.addWidget(parameters)

        physical = QGroupBox("Parâmetros físicos")
        physical_layout = QGridLayout(physical)
        physical_layout.addWidget(QLabel("Raio hidrodinâmico (nm)"), 0, 0)
        self.radius_nm_edit = QLineEdit()
        self.radius_nm_edit.setMaximumWidth(120)
        physical_layout.addWidget(self.radius_nm_edit, 0, 1)
        physical_layout.addWidget(QLabel("Temperatura (°C)"), 1, 0)
        self.temperature_c_edit = QLineEdit()
        self.temperature_c_edit.setMaximumWidth(120)
        physical_layout.addWidget(self.temperature_c_edit, 1, 1)
        physical_layout.addWidget(QLabel("Escala espacial (µm/px)"), 2, 0)
        self.micrometers_per_pixel_edit = QLineEdit()
        self.micrometers_per_pixel_edit.setMaximumWidth(120)
        physical_layout.addWidget(self.micrometers_per_pixel_edit, 2, 1)
        physical_note = QLabel(
            "Sem calibração, MSD e D ficam em unidades de pixel e η física não é calculada."
        )
        physical_note.setWordWrap(True)
        physical_layout.addWidget(physical_note, 3, 0, 1, 2)
        controls_layout.addWidget(physical)

        self.show_circles_check = QCheckBox("Círculos vermelhos (tp.annotate)")
        self.show_circles_check.setChecked(True)
        self.show_circles_check.toggled.connect(
            lambda: self._on_display_settings_changed()
        )
        controls_layout.addWidget(self.show_circles_check)
        self.show_grayscale_check = QCheckBox("Exibir em escala de cinza")
        self.show_grayscale_check.toggled.connect(
            lambda: self._on_display_settings_changed()
        )
        controls_layout.addWidget(self.show_grayscale_check)
        grayscale_note = QLabel(
            "A detecção do trackpy é feita em tons de cinza nos dois modos."
        )
        grayscale_note.setWordWrap(True)
        controls_layout.addWidget(grayscale_note)

        interval = QGroupBox("Intervalo de análise")
        interval_layout = QGridLayout(interval)
        interval_layout.addWidget(QLabel("Unidade"), 0, 0)
        self.interval_unit_box = QComboBox()
        self.interval_unit_box.addItems(("Quadros", "Segundos"))
        self.interval_unit_box.currentTextChanged.connect(
            self._on_interval_unit_changed
        )
        interval_layout.addWidget(self.interval_unit_box, 0, 1)
        self.interval_start_label = QLabel("Início (quadro)")
        interval_layout.addWidget(self.interval_start_label, 1, 0)
        self.interval_start_edit = QLineEdit("0")
        self.interval_start_edit.setMaximumWidth(120)
        interval_layout.addWidget(self.interval_start_edit, 1, 1)
        self.interval_end_label = QLabel("Fim (quadro)")
        interval_layout.addWidget(self.interval_end_label, 2, 0)
        self.interval_end_edit = QLineEdit("0")
        self.interval_end_edit.setMaximumWidth(120)
        interval_layout.addWidget(self.interval_end_edit, 2, 1)
        interval_note = QLabel(
            "Limites inclusivos. Em segundos, o tempo é convertido para o quadro correspondente."
        )
        interval_note.setWordWrap(True)
        interval_layout.addWidget(interval_note, 3, 0, 1, 2)
        controls_layout.addWidget(interval)

        self.detection_label = QLabel("Detecções: —")
        controls_layout.addWidget(self.detection_label)
        self.analyze_interval_button = QPushButton("Analisar intervalo")
        self.analyze_interval_button.setEnabled(False)
        self.analyze_interval_button.clicked.connect(
            lambda: self._start_interval_analysis()
        )
        controls_layout.addWidget(self.analyze_interval_button)
        self.analyze_all_button = QPushButton("Analisar vídeo todo")
        self.analyze_all_button.setEnabled(False)
        self.analyze_all_button.clicked.connect(lambda: self._start_full_analysis())
        controls_layout.addWidget(self.analyze_all_button)
        self.analysis_progress_bar = QProgressBar()
        self.analysis_progress_bar.setRange(0, 1)
        self.analysis_progress_bar.setValue(0)
        self.analysis_progress_bar.setFormat("Aguardando análise")
        self.analysis_progress_bar.setVisible(False)
        controls_layout.addWidget(self.analysis_progress_bar)
        self.tracking_data_button = QPushButton("Dados de Tracking")
        self.tracking_data_button.setEnabled(False)
        self.tracking_data_button.clicked.connect(
            lambda: self._show_tracking_data()
        )
        controls_layout.addWidget(self.tracking_data_button)
        self.visualize_plot_button = QPushButton("Visualizar gráfico")
        self.visualize_plot_button.setEnabled(False)
        self.visualize_plot_button.clicked.connect(
            lambda: self._show_trajectory_plot()
        )
        controls_layout.addWidget(self.visualize_plot_button)
        self.calculate_physical_button = QPushButton("Calcular Grandezas")
        self.calculate_physical_button.setEnabled(False)
        self.calculate_physical_button.clicked.connect(
            lambda: self._calculate_physical_report()
        )
        controls_layout.addWidget(self.calculate_physical_button)
        controls_layout.addStretch(1)

        video_panel = QWidget()
        video_layout = QVBoxLayout(video_panel)
        video_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.addWidget(video_panel, 1)

        self.figure = Figure(figsize=(8, 6), dpi=100)
        self.axes = self.figure.add_subplot(111)
        self.axes.set_axis_off()
        self.axes.text(
            0.5,
            0.5,
            "Abra um vídeo para exibi-lo aqui",
            ha="center",
            va="center",
            transform=self.axes.transAxes,
        )
        self.canvas = FigureCanvasQTAgg(self.figure)
        video_layout.addWidget(self.canvas, 1)

        playback = QWidget()
        playback_layout = QHBoxLayout(playback)
        playback_layout.setContentsMargins(0, 0, 0, 0)
        self.play_button = QPushButton("▶ Reproduzir")
        self.play_button.setEnabled(False)
        self.play_button.clicked.connect(lambda: self._toggle_playback())
        playback_layout.addWidget(self.play_button)
        self.position_scale = QSlider(Qt.Orientation.Horizontal)
        self.position_scale.setRange(0, 0)
        self.position_scale.valueChanged.connect(self._on_seek)
        self.position_scale.sliderReleased.connect(self._on_seek_released)
        playback_layout.addWidget(self.position_scale, 1)
        self.frame_label = QLabel("Posição: —")
        self.frame_label.setMinimumWidth(170)
        playback_layout.addWidget(self.frame_label)
        video_layout.addWidget(playback)

        self.status = QLabel("Abra um vídeo para começar.")
        self.status.setWordWrap(True)
        video_layout.addWidget(self.status)

    def _apply_theme(self, dark: bool) -> None:
        self.dark_mode = dark
        if dark:
            colors = {
                "window": "#202124",
                "surface": "#292a2d",
                "alternate": "#34363a",
                "text": "#e8eaed",
                "muted": "#9aa0a6",
                "border": "#5f6368",
                "accent": "#8ab4f8",
                "accent_text": "#202124",
                "disabled_button": "#303134",
                "disabled_text": "#80868b",
                "tooltip": "#303134",
            }
        else:
            colors = {
                "window": "#f4f5f7",
                "surface": "#ffffff",
                "alternate": "#eceff1",
                "text": "#202124",
                "muted": "#5f6368",
                "border": "#c4c7c5",
                "accent": "#1a73e8",
                "accent_text": "#ffffff",
                "disabled_button": "#dfe2e6",
                "disabled_text": "#767b82",
                "tooltip": "#fff8dc",
            }

        application = QApplication.instance()
        if application is not None:
            palette = QPalette()
            palette.setColor(QPalette.ColorRole.Window, QColor(colors["window"]))
            palette.setColor(QPalette.ColorRole.WindowText, QColor(colors["text"]))
            palette.setColor(QPalette.ColorRole.Base, QColor(colors["surface"]))
            palette.setColor(
                QPalette.ColorRole.AlternateBase, QColor(colors["alternate"])
            )
            palette.setColor(QPalette.ColorRole.Text, QColor(colors["text"]))
            palette.setColor(QPalette.ColorRole.Button, QColor(colors["alternate"]))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor(colors["text"]))
            palette.setColor(
                QPalette.ColorRole.PlaceholderText, QColor(colors["muted"])
            )
            palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(colors["tooltip"]))
            palette.setColor(QPalette.ColorRole.ToolTipText, QColor(colors["text"]))
            palette.setColor(QPalette.ColorRole.Link, QColor(colors["accent"]))
            palette.setColor(QPalette.ColorRole.Highlight, QColor(colors["accent"]))
            palette.setColor(
                QPalette.ColorRole.HighlightedText,
                QColor(colors["accent_text"]),
            )
            palette.setColor(
                QPalette.ColorGroup.Disabled,
                QPalette.ColorRole.Button,
                QColor(colors["disabled_button"]),
            )
            palette.setColor(
                QPalette.ColorGroup.Disabled,
                QPalette.ColorRole.ButtonText,
                QColor(colors["disabled_text"]),
            )
            application.setPalette(palette)
            self.setPalette(palette)

        background = colors["window"]
        foreground = colors["text"]
        self._plot_background_color = background
        self.figure.set_facecolor(background)
        self.axes.set_facecolor(background)
        for text in self.axes.texts:
            text.set_color(foreground)
        self.canvas.draw_idle()

    def _configure_timers(self) -> None:
        self.playback_timer = QTimer(self)
        self.playback_timer.setSingleShot(True)
        self.playback_timer.timeout.connect(self._advance_frame)

        self.preview_poll_timer = QTimer(self)
        self.preview_poll_timer.setInterval(25)
        self.preview_poll_timer.timeout.connect(self._poll_preview)
        self.preview_poll_timer.start()

        self.analysis_poll_timer = QTimer(self)
        self.analysis_poll_timer.setInterval(100)
        self.analysis_poll_timer.timeout.connect(self._poll_analysis_result)
        self.analysis_poll_timer.start()

        self.report_poll_timer = QTimer(self)
        self.report_poll_timer.setInterval(100)
        self.report_poll_timer.timeout.connect(self._poll_report_result)
        self.report_poll_timer.start()

    def _open_video(self) -> None:
        if self.analysis_in_progress or self.report_in_progress:
            QMessageBox.information(
                self,
                "Operação em andamento",
                "Aguarde a operação atual terminar antes de abrir outro vídeo.",
            )
            return
        selected = QFileDialog.getOpenFileName(
            self,
            "Abrir vídeo",
            "",
            "Arquivos de vídeo (*.avi *.mp4 *.mov *.mkv *.mpeg *.mpg);;Todos os arquivos (*)",
        )[0]
        if not selected:
            return

        video_path = Path(selected)
        try:
            info = inspect_video(video_path)
            settings = self._read_settings()
        except Exception as error:
            QMessageBox.critical(self, "Não foi possível abrir o vídeo", str(error))
            return

        self._stop_playback()
        if self.preview_worker is not None:
            self.preview_worker.close()

        self.video_path = video_path
        self.video_frame_count = info.frame_count
        self.video_frame_rate = info.frame_rate
        self.current_frame_index = 0
        self.current_preview = None
        self.preview_worker = VideoPreviewWorker(video_path)
        self.preview_in_flight = False
        self.video_label.setText(
            f"{video_path.name}\n{info.frame_shape[1]} × "
            f"{info.frame_shape[0]} px · {info.frame_count} quadros"
        )
        self.interval_start_edit.setText(
            "0" if self.interval_unit_box.currentText() == "Segundos" else "1"
        )
        self.interval_end_edit.setText(
            self._format_interval_value(
                (info.frame_count - 1) / info.frame_rate
                if self.interval_unit_box.currentText() == "Segundos"
                else info.frame_count
            )
        )
        with QSignalBlocker(self.position_scale):
            self.position_scale.setRange(0, max(0, info.frame_count - 1))
            self.position_scale.setValue(0)
        self._update_playback_position_label()
        self.detection_label.setText("Detecções: —")
        self.status.setText("Carregando primeiro quadro…")
        self.play_button.setEnabled(True)
        self.analyze_interval_button.setEnabled(True)
        self.analyze_all_button.setEnabled(True)
        self.results = None
        self.analysis_range = None
        self._update_result_actions()
        self._request_frame(0, settings)

    def _update_result_actions(self) -> None:
        has_results = self.results is not None and not self.results.empty
        analysis_ready = has_results and not self.analysis_in_progress
        self.tracking_data_button.setEnabled(analysis_ready)
        self.visualize_plot_button.setEnabled(analysis_ready)
        self.calculate_physical_button.setEnabled(
            analysis_ready and not self.report_in_progress
        )

    def _read_settings(self) -> TrackingSettings:
        return self.applied_settings

    def _apply_diameter(self) -> None:
        try:
            diameter = int(self.diameter_edit.text())
            settings = TrackingSettings(
                diameter=diameter,
                minmass=self.applied_settings.minmass,
                search_range=self.applied_settings.search_range,
                memory=self.applied_settings.memory,
            )
        except ValueError as error:
            QMessageBox.critical(self, "Diâmetro inválido", str(error))
            return
        self._apply_settings(settings, f"Diâmetro {settings.diameter} px aplicado.")

    def _apply_minmass(self) -> None:
        try:
            minmass = float(self.minmass_edit.text())
            settings = TrackingSettings(
                diameter=self.applied_settings.diameter,
                minmass=minmass,
                search_range=self.applied_settings.search_range,
                memory=self.applied_settings.memory,
            )
        except ValueError as error:
            QMessageBox.critical(self, "Massa mínima inválida", str(error))
            return
        self._apply_settings(settings, f"Massa mínima {settings.minmass:g} aplicada.")

    def _apply_settings(self, settings: TrackingSettings, message: str) -> None:
        self.applied_settings = settings
        self.status.setText(message)
        if self.video_path is not None and not self.playing:
            self._request_frame(self.current_frame_index, settings)

    def _request_frame(
        self, frame_index: int, settings: TrackingSettings | None = None
    ) -> None:
        if self.preview_worker is None or self.preview_in_flight:
            return
        current_settings = settings or self._read_settings()
        self.current_frame_index = frame_index
        self.preview_in_flight = True
        self.preview_worker.request_frame(frame_index, current_settings)

    def _poll_preview(self) -> None:
        if self.preview_worker is None or not self.preview_in_flight:
            return
        try:
            result = self.preview_worker.results.get_nowait()
        except queue.Empty:
            return

        self.preview_in_flight = False
        if result.error is not None:
            if result.frame_index >= 0 and result.frame_index != self.current_frame_index:
                self._request_frame(self.current_frame_index)
            else:
                self._preview_failed(result)
        elif result.frame_index != self.current_frame_index:
            self._request_frame(self.current_frame_index)
        elif result.settings != self.applied_settings:
            self._request_frame(self.current_frame_index)
        else:
            self._display_preview(result)
            if self.playing:
                self._schedule_next_frame()

    def _display_preview(self, result: PreviewResult) -> None:
        self.current_preview = result
        if result.color_frame is None or result.grayscale_frame is None:
            return

        image = (
            result.grayscale_frame
            if self.show_grayscale_check.isChecked()
            else result.color_frame
        )
        self.axes.clear()
        self.axes.set_facecolor(self._plot_background_color)
        if self.show_circles_check.isChecked() and result.features is not None:
            tp.annotate(
                result.features,
                image,
                ax=self.axes,
                plot_style={
                    "markersize": 15,
                    "markeredgewidth": 2,
                    "markeredgecolor": "red",
                },
            )
        else:
            self.axes.imshow(
                image,
                cmap="gray" if image.ndim == 2 else None,
                origin="upper",
                interpolation="nearest",
            )
        self.axes.set_axis_off()
        self.canvas.draw_idle()

        count = len(result.features) if result.features is not None else 0
        self.detection_label.setText(f"Detecções: {count}")
        self._update_playback_position_label(result.frame_index)
        with QSignalBlocker(self.position_scale):
            self.position_scale.setValue(result.frame_index)
        self.status.setText(
            f"Quadro {result.frame_index + 1}: {count} partículas detectadas."
        )

    def _preview_failed(self, result: PreviewResult) -> None:
        self._stop_playback()
        if result.frame_index < 0:
            self.play_button.setEnabled(False)
        self.status.setText("Não foi possível processar este quadro.")
        QMessageBox.critical(
            self,
            "Erro ao reproduzir vídeo",
            result.error or "Falha desconhecida ao ler ou processar o quadro.",
        )

    def _toggle_playback(self) -> None:
        if self.preview_worker is None:
            return
        if self.playing:
            self._stop_playback()
            return

        if self.current_frame_index >= self.video_frame_count - 1:
            self.current_frame_index = 0
            with QSignalBlocker(self.position_scale):
                self.position_scale.setValue(0)
        self.playing = True
        self.play_button.setText("❚❚ Pausar")
        if not self.preview_in_flight:
            self._request_frame(self.current_frame_index)

    def _stop_playback(self) -> None:
        self.playing = False
        self.play_button.setText("▶ Reproduzir")
        self.playback_timer.stop()

    def _schedule_next_frame(self) -> None:
        if not self.playing:
            return
        if self.current_frame_index >= self.video_frame_count - 1:
            self._stop_playback()
            return
        delay_ms = max(1, round(1000 / self.video_frame_rate))
        self.playback_timer.start(delay_ms)

    def _advance_frame(self) -> None:
        if self.playing:
            self._request_frame(self.current_frame_index + 1)

    def _on_seek(self, value: int) -> None:
        if self.video_path is None:
            return
        self.current_frame_index = value
        self._update_playback_position_label()
        if not self.playing:
            self._request_frame(self.current_frame_index)

    def _on_seek_released(self) -> None:
        if self.video_path is not None and not self.preview_in_flight:
            self._request_frame(self.current_frame_index)

    def _on_display_settings_changed(self) -> None:
        if self.video_path is not None and not self.playing:
            self._request_frame(self.current_frame_index)
        elif self.current_preview is not None:
            self._display_preview(self.current_preview)

    @staticmethod
    def _format_interval_value(value: float) -> str:
        return f"{value:.3f}".rstrip("0").rstrip(".")

    def _update_playback_position_label(self, frame_index: int | None = None) -> None:
        if self.video_frame_count == 0:
            self.frame_label.setText("Posição: —")
            return

        current_index = (
            self.current_frame_index if frame_index is None else frame_index
        )
        if self.interval_unit_box.currentText() == "Segundos":
            current_seconds = current_index / self.video_frame_rate
            duration_seconds = (
                self.video_frame_count - 1
            ) / self.video_frame_rate
            self.frame_label.setText(
                f"Tempo: {current_seconds:.2f} / {duration_seconds:.2f} s"
            )
        else:
            self.frame_label.setText(
                f"Quadro: {current_index + 1} / {self.video_frame_count}"
            )

    def _on_interval_unit_changed(self, new_unit: str) -> None:
        old_unit = self._previous_interval_unit
        if self.video_path is not None and old_unit != new_unit:
            try:
                start_value = float(self.interval_start_edit.text())
                end_value = float(self.interval_end_edit.text())
                if old_unit == "Quadros":
                    start_value = (start_value - 1) / self.video_frame_rate
                    end_value = (end_value - 1) / self.video_frame_rate
                else:
                    start_value = round(start_value * self.video_frame_rate) + 1
                    end_value = round(end_value * self.video_frame_rate) + 1
                self.interval_start_edit.setText(
                    self._format_interval_value(start_value)
                )
                self.interval_end_edit.setText(
                    self._format_interval_value(end_value)
                )
            except ValueError:
                self.interval_start_edit.setText(
                    "0" if new_unit == "Segundos" else "1"
                )
                self.interval_end_edit.setText(
                    self._format_interval_value(
                        (self.video_frame_count - 1) / self.video_frame_rate
                        if new_unit == "Segundos"
                        else self.video_frame_count
                    )
                )

        self._previous_interval_unit = new_unit
        unit_label = "quadro" if new_unit == "Quadros" else "segundo"
        self.interval_start_label.setText(f"Início ({unit_label})")
        self.interval_end_label.setText(f"Fim ({unit_label})")
        self._update_playback_position_label()

    def _start_interval_analysis(self) -> None:
        try:
            start_frame, end_frame = resolve_frame_range(
                float(self.interval_start_edit.text()),
                float(self.interval_end_edit.text()),
                self.interval_unit_box.currentText(),
                self.video_frame_rate,
                self.video_frame_count,
            )
        except ValueError as error:
            QMessageBox.critical(self, "Intervalo inválido", str(error))
            return
        self._start_analysis(start_frame, end_frame)

    def _start_full_analysis(self) -> None:
        if self.video_frame_count == 0:
            return
        self._start_analysis(0, self.video_frame_count - 1)

    def _start_analysis(self, start_frame: int, end_frame: int) -> None:
        if self.video_path is None or self.analysis_in_progress:
            return
        settings = self._read_settings()

        self._stop_playback()
        self.analysis_in_progress = True
        self.analysis_range = (start_frame, end_frame)
        self.results = None
        self._update_result_actions()
        total_frames = end_frame - start_frame + 1
        self.analysis_progress_bar.setRange(0, total_frames)
        self.analysis_progress_bar.setValue(0)
        self.analysis_progress_bar.setFormat("Preparando análise…")
        self.analysis_progress_bar.setVisible(True)
        self.analyze_interval_button.setEnabled(False)
        self.analyze_all_button.setEnabled(False)
        if start_frame == 0 and end_frame == self.video_frame_count - 1:
            self.status.setText("Analisando o vídeo completo em segundo plano…")
        else:
            self.status.setText(
                f"Analisando quadros {start_frame + 1}–{end_frame + 1} "
                "em segundo plano…"
            )
        threading.Thread(
            target=self._analyze_in_background,
            args=(self.video_path, settings, start_frame, end_frame),
            daemon=True,
        ).start()

    def _analyze_in_background(
        self,
        video_path: Path,
        settings: TrackingSettings,
        start_frame: int,
        end_frame: int,
    ) -> None:
        try:
            results = analyze_video(
                video_path,
                settings,
                start_frame=start_frame,
                end_frame=end_frame,
                progress_callback=self._queue_analysis_progress,
            )
        except Exception as error:
            self.analysis_queue.put((None, error))
            return
        self.analysis_queue.put((results, None))

    def _queue_analysis_progress(self, processed_frames: int, total_frames: int) -> None:
        try:
            self.analysis_progress_queue.put_nowait((processed_frames, total_frames))
        except queue.Full:
            try:
                self.analysis_progress_queue.get_nowait()
            except queue.Empty:
                pass
            self.analysis_progress_queue.put_nowait((processed_frames, total_frames))

    def _poll_analysis_progress(self) -> None:
        latest_progress: tuple[int, int] | None = None
        while True:
            try:
                latest_progress = self.analysis_progress_queue.get_nowait()
            except queue.Empty:
                break

        if latest_progress is None or self.analysis_range is None:
            return

        processed_frames, total_frames = latest_progress
        start_frame, _ = self.analysis_range
        current_frame = start_frame + processed_frames
        self.analysis_progress_bar.setRange(0, total_frames)
        self.analysis_progress_bar.setValue(processed_frames)
        self.analysis_progress_bar.setFormat(
            f"Quadro {current_frame} de {self.video_frame_count} (%p%)"
        )

    def _poll_analysis_result(self) -> None:
        self._poll_analysis_progress()
        try:
            results, error = self.analysis_queue.get_nowait()
        except queue.Empty:
            return

        self.analysis_progress_bar.setVisible(False)
        self.analysis_in_progress = False
        self._update_result_actions()
        if self.video_path is not None:
            self.analyze_interval_button.setEnabled(True)
            self.analyze_all_button.setEnabled(True)
        if error is not None:
            self.status.setText("A análise completa não foi concluída.")
            QMessageBox.critical(self, "Erro na análise", str(error))
        elif results is not None:
            self._analysis_finished(results)

    def _poll_report_result(self) -> None:
        try:
            metrics, error = self.report_queue.get_nowait()
        except queue.Empty:
            return

        self.report_in_progress = False
        self._update_result_actions()
        if error is not None:
            self.status.setText("Não foi possível calcular as grandezas físicas.")
            QMessageBox.critical(self, "Erro ao calcular grandezas", str(error))
        elif metrics is not None:
            self.status.setText("Grandezas calculadas.")
            self._show_physical_report(*metrics)
        else:
            self.status.setText("Não foi possível calcular as grandezas físicas.")
            QMessageBox.critical(
                self,
                "Erro ao calcular grandezas",
                "O cálculo não retornou resultados.",
            )

    def _analysis_finished(self, results: pd.DataFrame) -> None:
        self.results = results
        self._update_result_actions()
        if results.empty:
            self.status.setText("Análise concluída: nenhuma partícula foi detectada.")
            return

        particle_count = int(results["particle"].nunique())
        range_text = ""
        if self.analysis_range is not None:
            start_frame, end_frame = self.analysis_range
            range_text = f" nos quadros {start_frame + 1}–{end_frame + 1}"
        self.status.setText(
            f"Análise concluída{range_text}: {len(results)} localizações em "
            f"{particle_count} trajetórias."
        )

    def _show_tracking_data(self) -> None:
        if self.results is None or self.results.empty:
            return

        tracking_data = self.results.copy()
        dialog = TrackingDataDialog(tracking_data, self)
        dialog.save_button.clicked.connect(
            lambda: self._save_tracking_data(tracking_data, dialog)
        )
        dialog.exec()

    def _save_tracking_data(
        self,
        tracking_data: pd.DataFrame,
        dialog: TrackingDataDialog,
    ) -> None:
        destination = QFileDialog.getSaveFileName(
            dialog,
            "Salvar dados de tracking",
            "",
            "Arquivo CSV (*.csv)",
        )[0]
        if not destination:
            return
        if not destination.lower().endswith(".csv"):
            destination += ".csv"
        try:
            tracking_data.to_csv(destination, index=False)
        except OSError as error:
            QMessageBox.critical(dialog, "Erro ao salvar dados de tracking", str(error))
            return
        self.status.setText(f"Dados de tracking salvos em {destination}")

    def _show_trajectory_plot(self) -> None:
        if self.results is None or self.results.empty:
            return

        try:
            figure = create_trajectory_figure(self.results)
        except (ValueError, RuntimeError) as error:
            QMessageBox.critical(self, "Erro ao gerar gráfico", str(error))
            return

        foreground = "#e8eaed" if self.dark_mode else "#202124"
        background = self._plot_background_color
        figure.set_facecolor(background)
        axes = figure.axes[0]
        axes.set_facecolor(background)
        axes.title.set_color(foreground)
        axes.xaxis.label.set_color(foreground)
        axes.yaxis.label.set_color(foreground)
        axes.tick_params(colors=foreground)
        for spine in axes.spines.values():
            spine.set_color(foreground)

        dialog = QDialog(self)
        dialog.setWindowTitle("Trajetórias das partículas")
        dialog.resize(900, 650)
        layout = QVBoxLayout(dialog)
        canvas = FigureCanvasQTAgg(figure)
        toolbar = NavigationToolbar2QT(canvas, dialog)
        layout.addWidget(toolbar)
        layout.addWidget(canvas)
        dialog.exec()

    def _calculate_physical_report(self) -> None:
        if self.results is None or self.results.empty or self.report_in_progress:
            return
        try:
            radius_nm = float(self.radius_nm_edit.text())
            temperature_c = float(self.temperature_c_edit.text())
            calibration = self.micrometers_per_pixel_edit.text().strip()
            micrometers_per_pixel = float(calibration) if calibration else None
        except ValueError as error:
            QMessageBox.critical(
                self,
                "Parâmetros físicos inválidos",
                "Informe um raio, temperatura e, se disponível, uma calibração válida.\n"
                f"{error}",
            )
            return

        self.report_in_progress = True
        self.calculate_physical_button.setEnabled(False)
        self.status.setText("Calculando MSD e grandezas físicas…")
        threading.Thread(
            target=self._generate_physical_report,
            args=(
                self.results.copy(),
                radius_nm,
                temperature_c,
                micrometers_per_pixel,
            ),
            daemon=True,
        ).start()

    def _generate_physical_report(
        self,
        trajectories: pd.DataFrame,
        radius_nm: float,
        temperature_c: float,
        micrometers_per_pixel: float | None,
    ) -> None:
        try:
            metrics = calculate_physical_metrics(
                trajectories,
                radius_nm,
                temperature_c,
                micrometers_per_pixel,
            )
        except Exception as error:
            self.report_queue.put((None, error))
            return
        self.report_queue.put((metrics, None))

    def _show_physical_report(
        self,
        summary: pd.DataFrame,
        msd_curve: pd.DataFrame,
    ) -> None:
        dialog = PhysicalReportDialog(summary, msd_curve, self)
        dialog.save_button.clicked.connect(
            lambda: self._save_physical_report(summary, msd_curve, dialog)
        )
        dialog.exec()

    def _save_physical_report(
        self,
        summary: pd.DataFrame,
        msd_curve: pd.DataFrame,
        dialog: PhysicalReportDialog,
    ) -> None:
        destination = QFileDialog.getSaveFileName(
            dialog,
            "Salvar relatório de grandezas",
            "",
            "Planilha Excel (*.xlsx)",
        )[0]
        if not destination:
            return
        if not destination.lower().endswith(".xlsx"):
            destination += ".xlsx"

        try:
            write_physical_report_xlsx(
                summary,
                msd_curve,
                Path(destination),
            )
        except OSError as error:
            QMessageBox.critical(dialog, "Erro ao salvar relatório", str(error))
            return
        self.status.setText(f"Planilha de grandezas salva em {destination}")

    def closeEvent(self, event: QCloseEvent) -> None:
        self.playback_timer.stop()
        self.preview_poll_timer.stop()
        self.analysis_poll_timer.stop()
        self.report_poll_timer.stop()
        if self.preview_worker is not None:
            self.preview_worker.close()
        event.accept()

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import pandas as pd
import trackpy as tp
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from browniantrack.core.tracking import (
    TrackingSettings,
    analyze_video,
    export_physical_report,
    export_trajectory_plot,
    inspect_video,
    resolve_frame_range,
)
from browniantrack.core.video_preview import PreviewResult, VideoPreviewWorker


class MainWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("BrownianTrack")
        self.root.geometry("1120x760")
        self.root.minsize(820, 560)
        self.video_path: Path | None = None
        self.video_frame_count = 0
        self.video_frame_rate = 30.0
        self.current_frame_index = 0
        self.preview_worker: VideoPreviewWorker | None = None
        self.preview_in_flight = False
        self.playing = False
        self.playback_after_id: str | None = None
        self.current_preview: PreviewResult | None = None
        self.results: pd.DataFrame | None = None
        self.analysis_range: tuple[int, int] | None = None
        self.analysis_queue: queue.Queue[
            tuple[pd.DataFrame | None, Exception | None]
        ] = queue.Queue()
        self.report_queue: queue.Queue[tuple[str | None, Exception | None]] = queue.Queue()
        self.analysis_in_progress = False
        self.report_in_progress = False
        self.applied_settings = TrackingSettings()

        self.diameter = tk.StringVar(value="11")
        self.minmass = tk.StringVar(value="100")
        self.radius_nm = tk.StringVar()
        self.temperature_c = tk.StringVar()
        self.micrometers_per_pixel = tk.StringVar()
        self.interval_unit = tk.StringVar(value="Quadros")
        self.interval_start = tk.StringVar(value="0")
        self.interval_end = tk.StringVar(value="0")
        self._previous_interval_unit = self.interval_unit.get()
        self.show_circles = tk.BooleanVar(value=True)
        self.show_grayscale = tk.BooleanVar(value=False)
        self.video_label = tk.StringVar(value="Nenhum vídeo aberto")
        self.frame_label = tk.StringVar(value="Posição: —")
        self.detection_label = tk.StringVar(value="Detecções: —")
        self.status = tk.StringVar(value="Abra um vídeo para começar.")
        self.frame_position = tk.DoubleVar(value=0)

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self.root.after(25, self._poll_preview)
        self.root.after(100, self._poll_analysis_result)
        self.root.after(100, self._poll_report_result)

    def _build_ui(self) -> None:
        body = ttk.Frame(self.root, padding=12)
        body.pack(fill=tk.BOTH, expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        controls_container = ttk.Frame(body, width=300)
        controls_container.grid(row=0, column=0, sticky=tk.NS, padx=(0, 12))
        controls_container.grid_propagate(False)
        controls_canvas = tk.Canvas(controls_container, highlightthickness=0, width=280)
        controls_scrollbar = ttk.Scrollbar(
            controls_container,
            orient=tk.VERTICAL,
            command=controls_canvas.yview,
        )
        controls_canvas.configure(yscrollcommand=controls_scrollbar.set)
        controls_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        controls_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        controls = ttk.Frame(controls_canvas, width=280)
        controls_window = controls_canvas.create_window(
            (0, 0), window=controls, anchor=tk.NW
        )
        controls.bind(
            "<Configure>",
            lambda _event: controls_canvas.configure(
                scrollregion=controls_canvas.bbox("all")
            ),
        )
        controls_canvas.bind(
            "<Configure>",
            lambda event: controls_canvas.itemconfigure(
                controls_window, width=event.width
            ),
        )
        controls_canvas.bind(
            "<MouseWheel>",
            lambda event: controls_canvas.yview_scroll(
                int(-event.delta / 120), "units"
            ),
        )
        controls_canvas.bind(
            "<Button-4>",
            lambda _event: controls_canvas.yview_scroll(-1, "units"),
        )
        controls_canvas.bind(
            "<Button-5>",
            lambda _event: controls_canvas.yview_scroll(1, "units"),
        )

        ttk.Label(controls, text="BrownianTrack", font=("", 18, "bold")).pack(
            anchor=tk.W, pady=(0, 12)
        )
        ttk.Button(controls, text="Abrir vídeo…", command=self._open_video).pack(
            fill=tk.X
        )
        ttk.Label(
            controls,
            textvariable=self.video_label,
            wraplength=230,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(6, 12))

        parameters = ttk.LabelFrame(controls, text="Detecção trackpy", padding=10)
        parameters.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(parameters, text="Diâmetro (px, ímpar)").grid(
            row=0, column=0, sticky=tk.W, pady=4
        )
        ttk.Entry(parameters, textvariable=self.diameter, width=8).grid(
            row=0, column=1, sticky=tk.E, padx=(8, 4), pady=4
        )
        self.apply_diameter_button = ttk.Button(
            parameters,
            text="Aplicar",
            width=7,
            command=self._apply_diameter,
        )
        self.apply_diameter_button.grid(row=0, column=2, sticky=tk.E, pady=4)
        ttk.Label(parameters, text="Massa mínima").grid(
            row=1, column=0, sticky=tk.W, pady=4
        )
        ttk.Entry(parameters, textvariable=self.minmass, width=8).grid(
            row=1, column=1, sticky=tk.E, padx=(8, 4), pady=4
        )
        self.apply_minmass_button = ttk.Button(
            parameters,
            text="Aplicar",
            width=7,
            command=self._apply_minmass,
        )
        self.apply_minmass_button.grid(row=1, column=2, sticky=tk.E, pady=4)

        physical = ttk.LabelFrame(controls, text="Parâmetros físicos", padding=10)
        physical.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(physical, text="Raio hidrodinâmico (nm)").grid(
            row=0, column=0, sticky=tk.W, pady=3
        )
        ttk.Entry(physical, textvariable=self.radius_nm, width=11).grid(
            row=0, column=1, sticky=tk.E, pady=3
        )
        ttk.Label(physical, text="Temperatura (°C)").grid(
            row=1, column=0, sticky=tk.W, pady=3
        )
        ttk.Entry(physical, textvariable=self.temperature_c, width=11).grid(
            row=1, column=1, sticky=tk.E, pady=3
        )
        ttk.Label(physical, text="Escala espacial (µm/px)").grid(
            row=2, column=0, sticky=tk.W, pady=3
        )
        ttk.Entry(
            physical,
            textvariable=self.micrometers_per_pixel,
            width=11,
        ).grid(row=2, column=1, sticky=tk.E, pady=3)
        ttk.Label(
            physical,
            text="Sem calibração, MSD e D ficam em unidades de pixel e η física não é calculada.",
            wraplength=220,
            justify=tk.LEFT,
        ).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(5, 0))

        ttk.Checkbutton(
            controls,
            text="Círculos vermelhos (tp.annotate)",
            variable=self.show_circles,
            command=self._on_display_settings_changed,
        ).pack(anchor=tk.W, pady=4)
        ttk.Checkbutton(
            controls,
            text="Exibir em escala de cinza",
            variable=self.show_grayscale,
            command=self._on_display_settings_changed,
        ).pack(anchor=tk.W, pady=4)
        ttk.Label(
            controls,
            text="A detecção do trackpy é feita em tons de cinza nos dois modos.",
            wraplength=230,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(2, 10))

        interval = ttk.LabelFrame(controls, text="Intervalo de análise", padding=10)
        interval.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(interval, text="Unidade").grid(row=0, column=0, sticky=tk.W, pady=3)
        self.interval_unit_box = ttk.Combobox(
            interval,
            textvariable=self.interval_unit,
            values=("Quadros", "Segundos"),
            state="readonly",
            width=10,
        )
        self.interval_unit_box.grid(row=0, column=1, sticky=tk.E, pady=3)
        self.interval_unit_box.bind(
            "<<ComboboxSelected>>", self._on_interval_unit_changed
        )
        self.interval_start_label = ttk.Label(interval, text="Início (quadro)")
        self.interval_start_label.grid(row=1, column=0, sticky=tk.W, pady=3)
        ttk.Entry(interval, textvariable=self.interval_start, width=11).grid(
            row=1, column=1, sticky=tk.E, pady=3
        )
        self.interval_end_label = ttk.Label(interval, text="Fim (quadro)")
        self.interval_end_label.grid(row=2, column=0, sticky=tk.W, pady=3)
        ttk.Entry(interval, textvariable=self.interval_end, width=11).grid(
            row=2, column=1, sticky=tk.E, pady=3
        )
        ttk.Label(
            interval,
            text="Limites inclusivos. Em segundos, o tempo é convertido para o quadro correspondente.",
            wraplength=220,
            justify=tk.LEFT,
        ).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(5, 0))

        ttk.Label(controls, textvariable=self.detection_label).pack(
            anchor=tk.W, pady=(4, 10)
        )
        self.analyze_interval_button = ttk.Button(
            controls,
            text="Analisar intervalo",
            command=self._start_interval_analysis,
            state=tk.DISABLED,
        )
        self.analyze_interval_button.pack(fill=tk.X, pady=(4, 4))
        self.analyze_all_button = ttk.Button(
            controls,
            text="Analisar vídeo todo",
            command=self._start_full_analysis,
            state=tk.DISABLED,
        )
        self.analyze_all_button.pack(fill=tk.X, pady=(0, 4))
        self.export_button = ttk.Button(
            controls,
            text="Exportar CSV",
            command=self._export_csv,
            state=tk.DISABLED,
        )
        self.export_button.pack(fill=tk.X)
        self.export_plot_button = ttk.Button(
            controls,
            text="Exportar gráfico (PNG)",
            command=self._export_trajectory_plot,
            state=tk.DISABLED,
        )
        self.export_plot_button.pack(fill=tk.X, pady=(4, 0))
        self.export_physical_button = ttk.Button(
            controls,
            text="Calcular grandezas e exportar CSV",
            command=self._export_physical_report,
            state=tk.DISABLED,
        )
        self.export_physical_button.pack(fill=tk.X, pady=(4, 0))

        video_panel = ttk.Frame(body)
        video_panel.grid(row=0, column=1, sticky=tk.NSEW)
        video_panel.columnconfigure(0, weight=1)
        video_panel.rowconfigure(0, weight=1)

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
        self.canvas = FigureCanvasTkAgg(self.figure, master=video_panel)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky=tk.NSEW)
        self.canvas.draw()

        playback = ttk.Frame(video_panel)
        playback.grid(row=1, column=0, sticky=tk.EW, pady=(8, 0))
        playback.columnconfigure(1, weight=1)
        self.play_button = ttk.Button(
            playback,
            text="▶ Reproduzir",
            command=self._toggle_playback,
            state=tk.DISABLED,
        )
        self.play_button.grid(row=0, column=0, padx=(0, 8))
        self.position_scale = ttk.Scale(
            playback,
            from_=0,
            to=0,
            variable=self.frame_position,
            command=self._on_seek,
        )
        self.position_scale.grid(row=0, column=1, sticky=tk.EW)
        self.position_scale.bind("<ButtonRelease-1>", self._on_seek_released)
        ttk.Label(playback, textvariable=self.frame_label, width=26).grid(
            row=0, column=2, padx=(8, 0)
        )

        ttk.Label(
            video_panel, textvariable=self.status, wraplength=720, anchor=tk.W
        ).grid(row=2, column=0, sticky=tk.EW, pady=(8, 0))

    def _open_video(self, _event: tk.Event | None = None) -> None:
        if self.analysis_in_progress or self.report_in_progress:
            messagebox.showinfo(
                "Operação em andamento",
                "Aguarde a operação atual terminar antes de abrir outro vídeo.",
            )
            return
        selected = filedialog.askopenfilename(
            title="Abrir vídeo",
            filetypes=(
                ("Arquivos de vídeo", "*.avi *.mp4 *.mov *.mkv *.mpeg *.mpg"),
                ("Todos os arquivos", "*"),
            ),
        )
        if not selected:
            return

        video_path = Path(selected)
        try:
            info = inspect_video(video_path)
            settings = self._read_settings()
        except Exception as error:
            messagebox.showerror("Não foi possível abrir o vídeo", str(error))
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
        self.video_label.set(
            f"{video_path.name}\n{info.frame_shape[1]} × "
            f"{info.frame_shape[0]} px · {info.frame_count} quadros"
        )
        self.interval_start.set(
            "0" if self.interval_unit.get() == "Segundos" else "1"
        )
        self.interval_end.set(
            self._format_interval_value(
                (info.frame_count - 1) / info.frame_rate
                if self.interval_unit.get() == "Segundos"
                else info.frame_count
            )
        )
        self.frame_position.set(0)
        self.position_scale.configure(to=max(0, info.frame_count - 1))
        self._update_playback_position_label()
        self.detection_label.set("Detecções: —")
        self.status.set("Carregando primeiro quadro…")
        self.play_button.configure(state=tk.NORMAL)
        self.analyze_interval_button.configure(state=tk.NORMAL)
        self.analyze_all_button.configure(state=tk.NORMAL)
        self.export_button.configure(state=tk.DISABLED)
        self.export_plot_button.configure(state=tk.DISABLED)
        self.export_physical_button.configure(state=tk.DISABLED)
        self.results = None
        self.analysis_range = None
        self._request_frame(0, settings)

    def _read_settings(self) -> TrackingSettings:
        return self.applied_settings

    def _apply_diameter(self) -> None:
        try:
            diameter = int(self.diameter.get())
            settings = TrackingSettings(
                diameter=diameter,
                minmass=self.applied_settings.minmass,
                search_range=self.applied_settings.search_range,
                memory=self.applied_settings.memory,
            )
        except ValueError as error:
            messagebox.showerror("Diâmetro inválido", str(error))
            return
        self._apply_settings(settings, f"Diâmetro {settings.diameter} px aplicado.")

    def _apply_minmass(self) -> None:
        try:
            minmass = float(self.minmass.get())
            settings = TrackingSettings(
                diameter=self.applied_settings.diameter,
                minmass=minmass,
                search_range=self.applied_settings.search_range,
                memory=self.applied_settings.memory,
            )
        except ValueError as error:
            messagebox.showerror("Massa mínima inválida", str(error))
            return
        self._apply_settings(settings, f"Massa mínima {settings.minmass:g} aplicada.")

    def _apply_settings(self, settings: TrackingSettings, message: str) -> None:
        self.applied_settings = settings
        self.status.set(message)
        if self.video_path is not None and not self.playing:
            self._request_frame(self.current_frame_index, settings)

    def _request_frame(
        self, frame_index: int, settings: TrackingSettings | None = None
    ) -> None:
        if self.preview_worker is None or self.preview_in_flight:
            return
        try:
            current_settings = settings or self._read_settings()
        except ValueError as error:
            self.status.set(f"Parâmetros inválidos: {error}")
            self._stop_playback()
            return
        self.current_frame_index = frame_index
        self.preview_in_flight = True
        self.preview_worker.request_frame(frame_index, current_settings)

    def _poll_preview(self) -> None:
        if self.preview_worker is not None and self.preview_in_flight:
            try:
                result = self.preview_worker.results.get_nowait()
            except queue.Empty:
                result = None
            if result is not None:
                self.preview_in_flight = False
                if result.error is not None:
                    if result.frame_index >= 0 and result.frame_index != self.current_frame_index:
                        self._request_frame(self.current_frame_index)
                    else:
                        self._preview_failed(result)
                elif result.frame_index != self.current_frame_index:
                    self._request_frame(self.current_frame_index)
                elif result.settings != self._current_settings_or_none():
                    self._request_frame(self.current_frame_index)
                else:
                    self._display_preview(result)
                    if self.playing:
                        self._schedule_next_frame()
        self.root.after(25, self._poll_preview)

    def _current_settings_or_none(self) -> TrackingSettings | None:
        try:
            return self._read_settings()
        except ValueError:
            return None

    def _display_preview(self, result: PreviewResult) -> None:
        self.current_preview = result
        if result.color_frame is None or result.grayscale_frame is None:
            return

        image = result.grayscale_frame if self.show_grayscale.get() else result.color_frame
        self.axes.clear()
        if self.show_circles.get() and result.features is not None:
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
        self.detection_label.set(f"Detecções: {count}")
        self._update_playback_position_label(result.frame_index)
        self.frame_position.set(result.frame_index)
        self.status.set(
            f"Quadro {result.frame_index + 1}: {count} partículas detectadas."
        )

    def _preview_failed(self, result: PreviewResult) -> None:
        self._stop_playback()
        if result.frame_index < 0:
            self.play_button.configure(state=tk.DISABLED)
        self.status.set("Não foi possível processar este quadro.")
        messagebox.showerror(
            "Erro ao reproduzir vídeo",
            result.error or "Falha desconhecida ao ler ou processar o quadro.",
        )

    def _toggle_playback(self) -> None:
        if self.preview_worker is None:
            return
        if self.playing:
            self._stop_playback()
            return
        try:
            self._read_settings()
        except ValueError as error:
            messagebox.showerror("Parâmetros inválidos", str(error))
            return

        if self.current_frame_index >= self.video_frame_count - 1:
            self.current_frame_index = 0
            self.frame_position.set(0)
        self.playing = True
        self.play_button.configure(text="❚❚ Pausar")
        if not self.preview_in_flight:
            self._request_frame(self.current_frame_index)

    def _stop_playback(self) -> None:
        self.playing = False
        self.play_button.configure(text="▶ Reproduzir")
        if self.playback_after_id is not None:
            self.root.after_cancel(self.playback_after_id)
            self.playback_after_id = None

    def _schedule_next_frame(self) -> None:
        if not self.playing:
            return
        if self.current_frame_index >= self.video_frame_count - 1:
            self._stop_playback()
            return
        delay_ms = max(1, round(1000 / self.video_frame_rate))
        self.playback_after_id = self.root.after(delay_ms, self._advance_frame)

    def _advance_frame(self) -> None:
        self.playback_after_id = None
        if self.playing:
            self._request_frame(self.current_frame_index + 1)

    def _on_seek(self, value: str) -> None:
        if self.video_path is None:
            return
        self.current_frame_index = int(float(value))
        self._update_playback_position_label()
        if not self.playing:
            self._request_frame(self.current_frame_index)

    def _on_seek_released(self, _event: tk.Event) -> None:
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
            self.frame_label.set("Posição: —")
            return

        current_index = (
            self.current_frame_index if frame_index is None else frame_index
        )
        if self.interval_unit.get() == "Segundos":
            current_seconds = current_index / self.video_frame_rate
            duration_seconds = (self.video_frame_count - 1) / self.video_frame_rate
            self.frame_label.set(
                f"Tempo: {current_seconds:.2f} / {duration_seconds:.2f} s"
            )
        else:
            self.frame_label.set(
                f"Quadro: {current_index + 1} / {self.video_frame_count}"
            )

    def _on_interval_unit_changed(self, _event: tk.Event | None = None) -> None:
        new_unit = self.interval_unit.get()
        old_unit = self._previous_interval_unit
        if self.video_path is not None and old_unit != new_unit:
            try:
                start_value = float(self.interval_start.get())
                end_value = float(self.interval_end.get())
                if old_unit == "Quadros":
                    start_value = (start_value - 1) / self.video_frame_rate
                    end_value = (end_value - 1) / self.video_frame_rate
                else:
                    start_value = round(start_value * self.video_frame_rate) + 1
                    end_value = round(end_value * self.video_frame_rate) + 1
                self.interval_start.set(self._format_interval_value(start_value))
                self.interval_end.set(self._format_interval_value(end_value))
            except ValueError:
                self.interval_start.set("0")
                self.interval_end.set(
                    self._format_interval_value(
                        (self.video_frame_count - 1) / self.video_frame_rate
                        if new_unit == "Segundos"
                        else self.video_frame_count
                    )
                )
        self._previous_interval_unit = new_unit
        unit_label = "quadro" if new_unit == "Quadros" else "segundo"
        self.interval_start_label.configure(text=f"Início ({unit_label})")
        self.interval_end_label.configure(text=f"Fim ({unit_label})")
        self._update_playback_position_label()

    def _start_interval_analysis(self) -> None:
        try:
            start_frame, end_frame = resolve_frame_range(
                float(self.interval_start.get()),
                float(self.interval_end.get()),
                self.interval_unit.get(),
                self.video_frame_rate,
                self.video_frame_count,
            )
        except ValueError as error:
            messagebox.showerror("Intervalo inválido", str(error))
            return
        self._start_analysis(start_frame, end_frame)

    def _start_full_analysis(self) -> None:
        if self.video_frame_count == 0:
            return
        self._start_analysis(0, self.video_frame_count - 1)

    def _start_analysis(self, start_frame: int, end_frame: int) -> None:
        if self.video_path is None:
            return
        if self.analysis_in_progress:
            return
        try:
            settings = self._read_settings()
        except ValueError as error:
            messagebox.showerror("Parâmetros inválidos", str(error))
            return

        self._stop_playback()
        self.analysis_in_progress = True
        self.analysis_range = (start_frame, end_frame)
        self.results = None
        self.export_button.configure(state=tk.DISABLED)
        self.export_plot_button.configure(state=tk.DISABLED)
        self.export_physical_button.configure(state=tk.DISABLED)
        self.analyze_interval_button.configure(state=tk.DISABLED)
        self.analyze_all_button.configure(state=tk.DISABLED)
        if start_frame == 0 and end_frame == self.video_frame_count - 1:
            self.status.set("Analisando o vídeo completo em segundo plano…")
        else:
            self.status.set(
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
            )
        except Exception as error:
            self.analysis_queue.put((None, error))
            return
        self.analysis_queue.put((results, None))

    def _poll_analysis_result(self) -> None:
        try:
            results, error = self.analysis_queue.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_analysis_result)
            return

        self.analysis_in_progress = False
        if self.video_path is not None:
            self.analyze_interval_button.configure(state=tk.NORMAL)
            self.analyze_all_button.configure(state=tk.NORMAL)
        if error is not None:
            self.status.set("A análise completa não foi concluída.")
            messagebox.showerror("Erro na análise", str(error))
        elif results is not None:
            self._analysis_finished(results)
        self.root.after(100, self._poll_analysis_result)

    def _poll_report_result(self) -> None:
        try:
            output_path, error = self.report_queue.get_nowait()
        except queue.Empty:
            self.root.after(100, self._poll_report_result)
            return

        self.report_in_progress = False
        self.export_physical_button.configure(
            state=tk.NORMAL if self.results is not None and not self.results.empty else tk.DISABLED
        )
        if error is not None:
            self.status.set("Não foi possível gerar o relatório físico.")
            messagebox.showerror("Erro ao gerar relatório", str(error))
        elif output_path is not None:
            self.status.set(f"Relatório de grandezas exportado para {output_path}")
        self.root.after(100, self._poll_report_result)

    def _analysis_finished(self, results: pd.DataFrame) -> None:
        self.results = results
        if results.empty:
            self.export_button.configure(state=tk.DISABLED)
            self.export_plot_button.configure(state=tk.DISABLED)
            self.export_physical_button.configure(state=tk.DISABLED)
            self.status.set("Análise concluída: nenhuma partícula foi detectada.")
            return

        particle_count = int(results["particle"].nunique())
        range_text = ""
        if self.analysis_range is not None:
            start_frame, end_frame = self.analysis_range
            range_text = f" nos quadros {start_frame + 1}–{end_frame + 1}"
        self.status.set(
            f"Análise concluída{range_text}: {len(results)} localizações em "
            f"{particle_count} trajetórias."
        )
        self.export_button.configure(state=tk.NORMAL)
        self.export_plot_button.configure(state=tk.NORMAL)
        self.export_physical_button.configure(state=tk.NORMAL)

    def _export_csv(self) -> None:
        if self.results is None:
            return
        destination = filedialog.asksaveasfilename(
            title="Exportar resultados",
            defaultextension=".csv",
            filetypes=(("Arquivo CSV", "*.csv"),),
        )
        if destination:
            try:
                self.results.to_csv(destination, index=False)
            except OSError as error:
                messagebox.showerror("Erro ao exportar CSV", str(error))
                return
            self.status.set(f"Resultados exportados para {destination}")

    def _export_trajectory_plot(self) -> None:
        if self.results is None or self.results.empty:
            return
        destination = filedialog.asksaveasfilename(
            title="Exportar gráfico das trajetórias",
            defaultextension=".png",
            filetypes=(("Imagem PNG", "*.png"),),
        )
        if not destination:
            return
        try:
            export_trajectory_plot(self.results, Path(destination))
        except (OSError, ValueError, RuntimeError) as error:
            messagebox.showerror("Erro ao exportar gráfico", str(error))
            return
        self.status.set(f"Gráfico exportado para {destination}")

    def _export_physical_report(self) -> None:
        if self.results is None or self.results.empty or self.report_in_progress:
            return
        try:
            radius_nm = float(self.radius_nm.get())
            temperature_c = float(self.temperature_c.get())
            calibration = self.micrometers_per_pixel.get().strip()
            micrometers_per_pixel = float(calibration) if calibration else None
        except ValueError as error:
            messagebox.showerror(
                "Parâmetros físicos inválidos",
                f"Informe um raio, temperatura e, se disponível, uma calibração válida.\n{error}",
            )
            return

        destination = filedialog.asksaveasfilename(
            title="Exportar grandezas físicas",
            defaultextension=".csv",
            filetypes=(("Arquivo CSV", "*.csv"),),
        )
        if not destination:
            return

        self.report_in_progress = True
        self.export_physical_button.configure(state=tk.DISABLED)
        self.status.set("Calculando MSD e grandezas físicas…")
        threading.Thread(
            target=self._generate_physical_report,
            args=(
                self.results.copy(),
                Path(destination),
                radius_nm,
                temperature_c,
                micrometers_per_pixel,
            ),
            daemon=True,
        ).start()

    def _generate_physical_report(
        self,
        trajectories: pd.DataFrame,
        output_path: Path,
        radius_nm: float,
        temperature_c: float,
        micrometers_per_pixel: float | None,
    ) -> None:
        try:
            export_physical_report(
                trajectories,
                output_path,
                radius_nm,
                temperature_c,
                micrometers_per_pixel,
            )
        except Exception as error:
            self.report_queue.put((None, error))
            return
        self.report_queue.put((str(output_path), None))

    def _close(self) -> None:
        self._stop_playback()
        if self.preview_worker is not None:
            self.preview_worker.close()
        self.root.destroy()

from dataclasses import dataclass
from math import isfinite
from pathlib import Path

from matplotlib.figure import Figure
import numpy as np
import pandas as pd
import pims
import trackpy as tp

K_BOLTZMANN = 1.380649e-23
AVOGADRO = 6.02214076e23


@dataclass(frozen=True)
class TrackingSettings:
    diameter: int = 11
    minmass: float = 100.0
    search_range: float = 5.0
    memory: int = 0

    def __post_init__(self) -> None:
        if self.diameter <= 0 or self.diameter % 2 == 0:
            raise ValueError("O diâmetro deve ser um inteiro ímpar positivo.")
        if not isfinite(self.minmass) or self.minmass <= 0:
            raise ValueError("A massa mínima deve ser positiva.")
        if not isfinite(self.search_range) or self.search_range <= 0:
            raise ValueError("O alcance de busca deve ser positivo.")
        if self.memory < 0:
            raise ValueError("A memória não pode ser negativa.")


@dataclass(frozen=True)
class VideoInfo:
    frame_count: int
    frame_shape: tuple[int, ...]
    frame_rate: float = 30.0


def inspect_video(video_path: Path) -> VideoInfo:
    """Abre o vídeo com PIMS e obtém metadados decodificando apenas o primeiro quadro."""
    frames = pims.open(str(video_path))
    try:
        frame_count = len(frames)
        if frame_count == 0:
            raise ValueError("O vídeo não contém quadros.")
        first_frame = frames[0]
        frame_rate = getattr(frames, "frame_rate", 30.0)
        if not isinstance(frame_rate, (int, float)) or not isfinite(frame_rate):
            frame_rate = 30.0
        if frame_rate <= 0:
            frame_rate = 30.0
        return VideoInfo(frame_count, tuple(first_frame.shape), float(frame_rate))
    finally:
        close = getattr(frames, "close", None)
        if callable(close):
            close()


def resolve_frame_range(
    start: float,
    end: float,
    unit: str,
    frame_rate: float,
    frame_count: int,
) -> tuple[int, int]:
    """Converte limites inclusivos de quadros 1-based ou segundos em índices."""
    start_value = float(start)
    end_value = float(end)
    if frame_count <= 0:
        raise ValueError("O vídeo não contém quadros.")
    if not isfinite(start_value) or not isfinite(end_value):
        raise ValueError("O início e o fim devem ser números finitos.")
    if start_value < 0 or end_value < start_value:
        raise ValueError("O intervalo deve ter início não negativo e fim após o início.")

    if unit == "Quadros":
        if not start_value.is_integer() or not end_value.is_integer():
            raise ValueError("Os limites do intervalo em quadros devem ser inteiros.")
        if start_value < 1 or end_value > frame_count:
            raise ValueError(
                f"Os quadros devem estar entre 1 e {frame_count}."
            )
        start_frame, end_frame = int(start_value) - 1, int(end_value) - 1
    elif unit == "Segundos":
        if not isfinite(frame_rate) or frame_rate <= 0:
            raise ValueError("A taxa de quadros do vídeo é inválida.")
        duration = (frame_count - 1) / frame_rate
        if end_value > duration:
            raise ValueError(
                f"O fim do intervalo excede a duração do vídeo ({duration:.3f} s)."
            )
        start_frame = round(start_value * frame_rate)
        end_frame = round(end_value * frame_rate)
    else:
        raise ValueError("A unidade do intervalo deve ser Quadros ou Segundos.")

    if start_frame >= frame_count or end_frame >= frame_count:
        raise ValueError(f"O intervalo excede os {frame_count} quadros do vídeo.")
    return start_frame, end_frame


def analyze_video(
    video_path: Path,
    settings: TrackingSettings,
    start_frame: int = 0,
    end_frame: int | None = None,
) -> pd.DataFrame:
    """Detecta partículas no intervalo inclusivo e associa quadros consecutivos."""
    frames = pims.open(str(video_path))
    try:
        frame_count = len(frames)
        if frame_count == 0:
            raise ValueError("O vídeo não contém quadros.")
        if end_frame is None:
            end_frame = frame_count - 1
        if start_frame < 0 or end_frame < start_frame or end_frame >= frame_count:
            raise ValueError(
                f"O intervalo deve estar entre 0 e {frame_count - 1}, "
                "com o fim após o início."
            )

        selected_frames = frames[start_frame : end_frame + 1]
        frame_rate = getattr(frames, "frame_rate", 30.0)
        if (
            not isinstance(frame_rate, (int, float))
            or not isfinite(frame_rate)
            or frame_rate <= 0
        ):
            frame_rate = 30.0
        processed_frames = 0

        def add_frame_timestamp(frame_number: int, features: pd.DataFrame) -> pd.DataFrame:
            nonlocal processed_frames
            frame = selected_frames[processed_frames]
            processed_frames += 1
            timestamp = getattr(frame, "metadata", {}).get("t")
            if not isinstance(timestamp, (int, float)) or not isfinite(timestamp):
                timestamp = frame_number / frame_rate
            features["time_s"] = float(timestamp)
            return features

        grayscale_frames = pims.as_gray(selected_frames)
        features = tp.batch(
            grayscale_frames,
            diameter=settings.diameter,
            minmass=settings.minmass,
            processes=1,
            after_locate=add_frame_timestamp,
        )
    finally:
        close = getattr(frames, "close", None)
        if callable(close):
            close()

    if features.empty:
        features["particle"] = pd.Series(dtype="int64")
        return features

    return tp.link_df(
        features,
        search_range=settings.search_range,
        memory=settings.memory,
    )


def calculate_physical_metrics(
    trajectories: pd.DataFrame,
    radius_nm: float,
    temperature_c: float,
    micrometers_per_pixel: float | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Calcula MSD, difusão e grandezas de Stokes–Einstein a partir das trajetórias."""
    radius_nm = float(radius_nm)
    temperature_c = float(temperature_c)
    if not isfinite(radius_nm) or radius_nm <= 0:
        raise ValueError("O raio hidrodinâmico deve ser positivo.")
    if not isfinite(temperature_c) or temperature_c <= -273.15:
        raise ValueError("A temperatura deve ser superior a -273,15 °C.")
    if micrometers_per_pixel is not None:
        micrometers_per_pixel = float(micrometers_per_pixel)
        if not isfinite(micrometers_per_pixel) or micrometers_per_pixel <= 0:
            raise ValueError("A calibração espacial deve ser positiva.")

    required_columns = {"frame", "particle", "x", "y"}
    missing_columns = required_columns.difference(trajectories.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Faltam colunas necessárias para os cálculos: {missing}.")
    if trajectories.empty:
        raise ValueError("Não há trajetórias para calcular.")

    if "time_s" in trajectories:
        working = trajectories.copy()
    else:
        working = trajectories.copy()
        working["time_s"] = working["frame"].astype(float)

    max_lag = max(1, int(working["frame"].max() - working["frame"].min()) // 4)
    lag_pairs: dict[int, list[tuple[float, float]]] = {}
    for _, particle_data in working.groupby("particle", sort=False):
        particle_data = particle_data.sort_values("frame")
        points = {
            int(row.frame): (float(row.x), float(row.y), float(row.time_s))
            for row in particle_data.itertuples(index=False)
        }
        frame_numbers = sorted(points)
        for lag in range(1, max_lag + 1):
            pairs = lag_pairs.setdefault(lag, [])
            for frame_number in frame_numbers:
                later = points.get(frame_number + lag)
                if later is None:
                    continue
                earlier = points[frame_number]
                elapsed = later[2] - earlier[2]
                if elapsed <= 0:
                    continue
                squared_displacement = (later[0] - earlier[0]) ** 2 + (
                    later[1] - earlier[1]
                ) ** 2
                pairs.append((elapsed, squared_displacement))

    msd_rows: list[dict[str, float | int]] = []
    for lag, pairs in sorted(lag_pairs.items()):
        if not pairs:
            continue
        elapsed_times, squared_displacements = zip(*pairs, strict=True)
        mean_msd_pixels = float(np.mean(squared_displacements))
        row: dict[str, float | int] = {
            "lag_frames": lag,
            "lag_time_s": float(np.mean(elapsed_times)),
            "pair_count": len(pairs),
            "msd_px2": mean_msd_pixels,
        }
        if micrometers_per_pixel is not None:
            row["msd_um2"] = mean_msd_pixels * micrometers_per_pixel**2
        msd_rows.append(row)

    msd_curve = pd.DataFrame(msd_rows)
    if msd_curve.empty:
        raise ValueError("Não há pares de posições suficientes para calcular o MSD.")

    distance_column = "msd_um2" if micrometers_per_pixel is not None else "msd_px2"
    fit_data = msd_curve[
        (msd_curve["lag_time_s"] > 0) & (msd_curve[distance_column] > 0)
    ]
    apparent_diffusion: float | None = None
    alpha: float | None = None
    fit_r_squared: float | None = None
    if len(fit_data) >= 2:
        times = fit_data["lag_time_s"].to_numpy(dtype=float)
        msd_values = fit_data[distance_column].to_numpy(dtype=float)
        slope, intercept = np.polyfit(times, msd_values, 1)
        apparent_diffusion = float(slope / 4)
        alpha = float(np.polyfit(np.log(times), np.log(msd_values), 1)[0])
        fitted_msd = slope * times + intercept
        residual_sum = float(np.sum((msd_values - fitted_msd) ** 2))
        total_sum = float(np.sum((msd_values - np.mean(msd_values)) ** 2))
        fit_r_squared = (
            1.0 - residual_sum / total_sum if total_sum > 0 else float("nan")
        )

    temperature_k = temperature_c + 273.15
    radius_m = radius_nm * 1e-9
    eta: float | None = None
    if alpha is None:
        regime = "não calculável: lags insuficientes"
    elif alpha < 0.8:
        regime = "subdifusão"
    elif alpha <= 1.2:
        regime = "difusão aproximadamente normal"
    else:
        regime = "superdifusão"

    viscosity_note = "Requer calibração espacial em µm/pixel."
    if micrometers_per_pixel is not None:
        if alpha is None or apparent_diffusion is None:
            viscosity_note = "Não estimada: são necessários pelo menos dois lags para o ajuste."
        elif abs(alpha - 1.0) <= 0.2 and apparent_diffusion > 0:
            diffusion_m2_s = apparent_diffusion * 1e-12
            eta = K_BOLTZMANN * temperature_k / (
                6 * np.pi * radius_m * diffusion_m2_s
            )
            viscosity_note = (
                "Inferida pela relação de Stokes–Einstein usando kB tabelado; "
                "interpretação válida para difusão aproximadamente normal."
            )
        else:
            viscosity_note = (
                "Não estimada: a relação de Stokes–Einstein simples requer "
                "difusão aproximadamente normal (α próximo de 1)."
            )

    diffusion_unit = "µm²/s" if micrometers_per_pixel is not None else "px²/s"
    summary_rows: list[dict[str, object]] = [
        {"Grandeza": "Raio hidrodinâmico informado", "Valor": radius_nm, "Unidade": "nm"},
        {"Grandeza": "Temperatura informada", "Valor": temperature_c, "Unidade": "°C"},
        {"Grandeza": "Temperatura absoluta", "Valor": temperature_k, "Unidade": "K"},
        {
            "Grandeza": "Calibração espacial",
            "Valor": micrometers_per_pixel if micrometers_per_pixel is not None else "não informada",
            "Unidade": "µm/px",
        },
        {"Grandeza": "MSD", "Valor": "ver curva MSD", "Unidade": "px² e/ou µm²"},
        {
            "Grandeza": "Coeficiente de difusão aparente",
            "Valor": apparent_diffusion if apparent_diffusion is not None else "não calculável",
            "Unidade": diffusion_unit,
        },
        {
            "Grandeza": "Expoente anômalo α",
            "Valor": alpha if alpha is not None else "não calculável",
            "Unidade": "adimensional",
        },
        {
            "Grandeza": "Regime de movimento",
            "Valor": regime,
            "Unidade": "",
        },
        {
            "Grandeza": "R² do ajuste linear MSD × tempo",
            "Valor": fit_r_squared if fit_r_squared is not None else "não calculável",
            "Unidade": "adimensional",
        },
        {"Grandeza": "Constante de Boltzmann (tabelada)", "Valor": K_BOLTZMANN, "Unidade": "J/K"},
        {"Grandeza": "Número de Avogadro (tabelado)", "Valor": AVOGADRO, "Unidade": "mol⁻¹"},
        {
            "Grandeza": "Origem de NA",
            "Valor": "constante tabelada; não medida neste ensaio",
            "Unidade": "",
        },
        {"Grandeza": "Viscosidade dinâmica inferida", "Valor": eta if eta is not None else "não calculada", "Unidade": "Pa·s"},
        {"Grandeza": "Observação sobre viscosidade", "Valor": viscosity_note, "Unidade": ""},
    ]
    if micrometers_per_pixel is None:
        summary_rows.append(
            {
                "Grandeza": "D e η físicos",
                "Valor": "requer calibração espacial em µm/pixel",
                "Unidade": "",
            }
        )
    return pd.DataFrame(summary_rows), msd_curve


def export_physical_report(
    trajectories: pd.DataFrame,
    output_path: Path,
    radius_nm: float,
    temperature_c: float,
    micrometers_per_pixel: float | None = None,
) -> None:
    """Calcula as grandezas e salva um CSV com resumo, entradas e curva de MSD."""
    summary, msd_curve = calculate_physical_metrics(
        trajectories,
        radius_nm,
        temperature_c,
        micrometers_per_pixel,
    )
    rows = [
        {
            "Seção": "Resumo",
            "Grandeza": row["Grandeza"],
            "Valor": row["Valor"],
            "Unidade": row["Unidade"],
        }
        for row in summary.to_dict(orient="records")
    ]
    for row in msd_curve.to_dict(orient="records"):
        rows.append(
            {
                "Seção": "Curva MSD",
                "Grandeza": "",
                "Valor": "",
                "Unidade": "",
                **row,
            }
        )
    pd.DataFrame(rows).to_csv(output_path, index=False, encoding="utf-8-sig")


def export_trajectory_plot(trajectories: pd.DataFrame, output_path: Path) -> None:
    """Gera e salva o gráfico das trajetórias detectadas usando trackpy."""
    if trajectories.empty:
        raise ValueError("Não há trajetórias para desenhar.")

    required_columns = {"frame", "particle", "x", "y"}
    missing_columns = required_columns.difference(trajectories.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Faltam colunas necessárias para o gráfico: {missing}.")

    figure = Figure(figsize=(8, 6))
    axes = figure.add_subplot(111)
    tp.plot_traj(trajectories, ax=axes)
    axes.set_title("Trajetórias das partículas")
    figure.tight_layout()
    figure.savefig(output_path, dpi=150, bbox_inches="tight")

import unittest
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, Mock, patch

import pandas as pd

from browniantrack.core.tracking import (
    TrackingSettings,
    analyze_video,
    calculate_physical_metrics,
    export_physical_report,
    export_trajectory_plot,
    inspect_video,
    resolve_frame_range,
)


class TrackingSettingsTests(unittest.TestCase):
    def test_accepts_default_settings(self) -> None:
        settings = TrackingSettings()
        self.assertEqual(settings.diameter, 11)
        self.assertEqual(settings.memory, 0)

    def test_rejects_even_diameter(self) -> None:
        with self.assertRaisesRegex(ValueError, "ímpar"):
            TrackingSettings(diameter=10)

    def test_rejects_non_positive_detection_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "massa mínima"):
            TrackingSettings(minmass=0)
        with self.assertRaisesRegex(ValueError, "alcance de busca"):
            TrackingSettings(search_range=0)
        with self.assertRaisesRegex(ValueError, "massa mínima"):
            TrackingSettings(minmass=float("nan"))

    def test_rejects_negative_memory(self) -> None:
        with self.assertRaisesRegex(ValueError, "memória"):
            TrackingSettings(memory=-1)


class FrameRangeTests(unittest.TestCase):
    def test_accepts_inclusive_frame_range(self) -> None:
        self.assertEqual(resolve_frame_range(12, 24, "Quadros", 30, 100), (11, 23))

    def test_converts_seconds_to_inclusive_frames(self) -> None:
        self.assertEqual(resolve_frame_range(1.0, 2.0, "Segundos", 30, 100), (30, 60))

    def test_rejects_reversed_or_out_of_bounds_ranges(self) -> None:
        with self.assertRaisesRegex(ValueError, "intervalo"):
            resolve_frame_range(20, 10, "Quadros", 30, 100)
        with self.assertRaisesRegex(ValueError, "entre 1 e 100"):
            resolve_frame_range(1, 101, "Quadros", 30, 100)
        with self.assertRaisesRegex(ValueError, "duração"):
            resolve_frame_range(0, 4, "Segundos", 30, 100)

    def test_requires_integer_frame_indices(self) -> None:
        with self.assertRaisesRegex(ValueError, "inteiros"):
            resolve_frame_range(1.5, 5, "Quadros", 30, 100)


class VideoInspectionTests(unittest.TestCase):
    def test_reads_video_metadata_with_pims_and_closes_reader(self) -> None:
        class FakeFrame:
            shape = (480, 640, 3)

        class FakeFrames:
            closed = False

            def __len__(self) -> int:
                return 12

            def __getitem__(self, index: int) -> FakeFrame:
                self.requested_index = index
                return FakeFrame()

            def close(self) -> None:
                self.closed = True

        frames = FakeFrames()
        with patch("browniantrack.core.tracking.pims.open", return_value=frames) as opener:
            info = inspect_video(Path("sample.mp4"))

        opener.assert_called_once_with("sample.mp4")
        self.assertEqual(info.frame_count, 12)
        self.assertEqual(info.frame_shape, (480, 640, 3))
        self.assertEqual(frames.requested_index, 0)
        self.assertTrue(frames.closed)

    def test_rejects_empty_video_and_closes_reader(self) -> None:
        class EmptyFrames:
            closed = False

            def __len__(self) -> int:
                return 0

            def close(self) -> None:
                self.closed = True

        frames = EmptyFrames()
        with patch("browniantrack.core.tracking.pims.open", return_value=frames):
            with self.assertRaisesRegex(ValueError, "não contém quadros"):
                inspect_video(Path("empty.mp4"))
        self.assertTrue(frames.closed)


class VideoAnalysisTests(unittest.TestCase):
    def test_analyzes_selected_inclusive_frame_range(self) -> None:
        frames = MagicMock()
        frames.__len__.return_value = 20
        selected_frames = MagicMock()
        selected_frames.__getitem__.return_value = Mock(metadata={"t": 2.0})
        frames.__getitem__.return_value = selected_frames
        grayscale_frames = Mock()
        expected = pd.DataFrame({"x": [10.0], "y": [12.0], "frame": [10]})
        linked = expected.assign(particle=0)

        def locate_batch(
            _frames: object,
            diameter: int,
            minmass: float,
            processes: int,
            after_locate: Callable[[int, pd.DataFrame], pd.DataFrame],
        ) -> pd.DataFrame:
            return after_locate(10, expected.copy())

        with (
            patch("browniantrack.core.tracking.pims.open", return_value=frames),
            patch(
                "browniantrack.core.tracking.pims.as_gray",
                return_value=grayscale_frames,
            ) as as_gray,
            patch(
                "browniantrack.core.tracking.tp.batch",
                side_effect=locate_batch,
            ) as batch,
            patch("browniantrack.core.tracking.tp.link_df", return_value=linked) as link_df,
        ):
            result = analyze_video(
                Path("sample.mp4"),
                TrackingSettings(),
                start_frame=10,
                end_frame=12,
            )

        frames.__getitem__.assert_called_once_with(slice(10, 13))
        as_gray.assert_called_once_with(selected_frames)
        batch.assert_called_once_with(
            grayscale_frames,
            diameter=11,
            minmass=100.0,
            processes=1,
            after_locate=batch.call_args.kwargs["after_locate"],
        )
        self.assertEqual(link_df.call_args.args[0]["time_s"].iloc[0], 2.0)
        link_df.assert_called_once()
        frames.close.assert_called_once_with()
        self.assertIs(result, linked)


class TrajectoryPlotTests(unittest.TestCase):
    def test_exports_trackpy_trajectory_plot(self) -> None:
        trajectories = pd.DataFrame(
            {
                "frame": [0, 1, 0, 1],
                "particle": [0, 0, 1, 1],
                "x": [10.0, 11.0, 20.0, 21.0],
                "y": [15.0, 16.0, 25.0, 26.0],
            }
        )
        with TemporaryDirectory() as directory:
            output_path = Path(directory) / "trajectories.png"
            export_trajectory_plot(trajectories, output_path)
            self.assertTrue(output_path.is_file())
            self.assertGreater(output_path.stat().st_size, 0)

    def test_rejects_empty_or_incomplete_trajectory_data(self) -> None:
        with self.assertRaisesRegex(ValueError, "Não há trajetórias"):
            export_trajectory_plot(pd.DataFrame(), Path("unused.png"))
        with self.assertRaisesRegex(ValueError, "Faltam colunas"):
            export_trajectory_plot(
                pd.DataFrame({"x": [1], "y": [2]}),
                Path("unused.png"),
            )


class PhysicalMetricsTests(unittest.TestCase):
    def setUp(self) -> None:
        rows = []
        trajectories = {
            0: [0, 1, 0, 1, 1, 0, 1, 1, 0, 1, 0, 1, 1],
            1: [0, 0, 1, 1, 0, 1, 1, 0, 1, 0, 1, 1, 0],
            2: [0, 1, 1, 0, 1, 1, 0, 1, 0, 1, 1, 0, 1],
        }
        for particle, steps in trajectories.items():
            x = 0.0
            for frame, step in enumerate(steps):
                if frame:
                    x += step * (1 if particle != 1 else -1)
                rows.append(
                    {
                        "frame": frame,
                        "particle": particle,
                        "x": x,
                        "y": 0.0,
                        "time_s": frame * 0.2,
                    }
                )
        self.trajectories = pd.DataFrame(rows)

    def test_computes_msd_and_keeps_physical_units_explicit(self) -> None:
        summary, msd = calculate_physical_metrics(
            self.trajectories,
            radius_nm=500,
            temperature_c=22,
        )
        self.assertIn("msd_px2", msd.columns)
        self.assertNotIn("msd_um2", msd.columns)
        self.assertEqual(int(msd.iloc[0]["lag_frames"]), 1)
        summary_values = dict(zip(summary["Grandeza"], summary["Valor"], strict=True))
        self.assertEqual(summary_values["Raio hidrodinâmico informado"], 500)
        self.assertEqual(summary_values["Temperatura informada"], 22)
        self.assertEqual(summary_values["Número de Avogadro (tabelado)"], 6.02214076e23)
        self.assertEqual(summary_values["Viscosidade dinâmica inferida"], "não calculada")

    def test_calculates_viscosity_when_spatial_calibration_is_provided(self) -> None:
        import numpy as np

        rng = np.random.default_rng(42)
        rows = []
        for particle in range(40):
            x = np.cumsum(rng.normal(0, 1, 100))
            y = np.cumsum(rng.normal(0, 1, 100))
            rows.extend(
                {
                    "frame": frame,
                    "particle": particle,
                    "x": x[frame],
                    "y": y[frame],
                    "time_s": frame * 0.1,
                }
                for frame in range(100)
            )
        trajectories = pd.DataFrame(rows)
        summary, msd = calculate_physical_metrics(
            trajectories,
            radius_nm=500,
            temperature_c=22,
            micrometers_per_pixel=0.1,
        )
        summary_values = dict(zip(summary["Grandeza"], summary["Valor"], strict=True))
        self.assertIn("msd_um2", msd.columns)
        self.assertAlmostEqual(float(summary_values["Expoente anômalo α"]), 1, delta=0.2)
        self.assertGreater(float(summary_values["Viscosidade dinâmica inferida"]), 0)
        self.assertEqual(
            summary_values["Regime de movimento"],
            "difusão aproximadamente normal",
        )

    def test_exports_summary_inputs_and_msd_curve(self) -> None:
        with TemporaryDirectory() as directory:
            output_path = Path(directory) / "physical.csv"
            export_physical_report(
                self.trajectories,
                output_path,
                radius_nm=500,
                temperature_c=22,
            )
            report = pd.read_csv(output_path)
        self.assertIn("Raio hidrodinâmico informado", report["Grandeza"].values)
        self.assertIn("Temperatura informada", report["Grandeza"].values)
        self.assertIn("Origem de NA", report["Grandeza"].values)
        self.assertIn("Curva MSD", report["Seção"].values)

    def test_rejects_invalid_physical_inputs(self) -> None:
        with self.assertRaisesRegex(ValueError, "raio"):
            calculate_physical_metrics(self.trajectories, 0, 22)
        with self.assertRaisesRegex(ValueError, "temperatura"):
            calculate_physical_metrics(self.trajectories, 500, -273.15)
        with self.assertRaisesRegex(ValueError, "calibração"):
            calculate_physical_metrics(self.trajectories, 500, 22, 0)


class PreviewTests(unittest.TestCase):
    def test_locates_features_on_pims_grayscale_frame(self) -> None:
        import numpy as np

        color_frame = np.zeros((20, 30, 3), dtype=np.uint8)
        grayscale_frame = np.zeros((20, 30), dtype=np.float64)
        features = pd.DataFrame({"x": [10.0], "y": [8.0]})
        with (
            patch(
                "browniantrack.core.video_preview.pims.as_gray",
                return_value=grayscale_frame,
            ) as as_gray,
            patch("browniantrack.core.video_preview.tp.locate", return_value=features) as locate,
        ):
            from browniantrack.core.video_preview import locate_frame

            gray, detected = locate_frame(color_frame, TrackingSettings(diameter=15, minmass=50))

        as_gray.assert_called_once_with(color_frame)
        locate.assert_called_once_with(grayscale_frame, diameter=15, minmass=50)
        self.assertIs(gray, grayscale_frame)
        self.assertIs(detected, features)


if __name__ == "__main__":
    unittest.main()

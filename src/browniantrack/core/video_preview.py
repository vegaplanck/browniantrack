import queue
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pims
import trackpy as tp

from browniantrack.core.tracking import TrackingSettings


@dataclass(frozen=True)
class PreviewRequest:
    frame_index: int
    settings: TrackingSettings


@dataclass(frozen=True)
class PreviewResult:
    frame_index: int
    color_frame: np.ndarray | None = None
    grayscale_frame: np.ndarray | None = None
    features: pd.DataFrame | None = None
    settings: TrackingSettings | None = None
    error: str | None = None


def locate_frame(
    frame: np.ndarray, settings: TrackingSettings
) -> tuple[np.ndarray, pd.DataFrame]:
    grayscale_frame = np.asarray(pims.as_gray(frame))
    features = tp.locate(
        grayscale_frame,
        diameter=settings.diameter,
        minmass=settings.minmass,
    )
    return grayscale_frame, features


class VideoPreviewWorker:
    """Lê e processa um quadro por vez fora do thread da interface."""

    def __init__(self, video_path: Path) -> None:
        self._video_path = video_path
        self._requests: queue.Queue[PreviewRequest | None] = queue.Queue()
        self.results: queue.Queue[PreviewResult] = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def request_frame(self, frame_index: int, settings: TrackingSettings) -> None:
        self._requests.put(PreviewRequest(frame_index, settings))

    def close(self) -> None:
        self._requests.put(None)

    def _run(self) -> None:
        frames = None
        try:
            frames = pims.open(str(self._video_path))
            while True:
                request = self._requests.get()
                if request is None:
                    return

                try:
                    color_frame = np.asarray(frames[request.frame_index])
                    grayscale_frame, features = locate_frame(
                        color_frame, request.settings
                    )
                    result = PreviewResult(
                        request.frame_index,
                        color_frame,
                        grayscale_frame,
                        features,
                        request.settings,
                    )
                except Exception as error:
                    result = PreviewResult(
                        request.frame_index,
                        settings=request.settings,
                        error=str(error),
                    )
                self.results.put(result)
        except Exception as error:
            self.results.put(PreviewResult(-1, error=str(error)))
        finally:
            close = getattr(frames, "close", None)
            if callable(close):
                close()

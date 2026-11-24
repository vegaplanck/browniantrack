import math
import re
import shutil
import subprocess
import sys
import tkinter as tk
from tkinter import font


_XFT_DPI_PATTERN = re.compile(
    r"^\s*Xft\.dpi\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*$",
    re.I,
)
_SANS_FAMILIES = (
    "Cantarell",
    "Noto Sans",
    "Liberation Sans",
    "DejaVu Sans",
    "Arial",
    "Helvetica",
)
_MONOSPACE_FAMILIES = (
    "Noto Sans Mono",
    "Liberation Mono",
    "DejaVu Sans Mono",
    "Monospace",
)


def _read_xft_dpi() -> float | None:
    if sys.platform != "linux" or shutil.which("xrdb") is None:
        return None

    try:
        result = subprocess.run(
            ["xrdb", "-query"],
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if result.returncode != 0:
        return None

    for line in result.stdout.splitlines():
        match = _XFT_DPI_PATTERN.match(line)
        if match is None:
            continue
        dpi = float(match.group(1))
        return dpi if math.isfinite(dpi) and dpi > 0 else None
    return None


def _available_family(root: tk.Tk, candidates: tuple[str, ...], fallback: str) -> str:
    available = {family.casefold(): family for family in font.families(root)}
    for candidate in candidates:
        family = available.get(candidate.casefold())
        if family is not None:
            return family
    return fallback


def _scale_named_fonts(
    root: tk.Tk,
    current_scaling: float,
    named_fonts: tuple[tuple[str, int], ...],
) -> None:
    default_font = font.nametofont("TkDefaultFont", root=root)
    default_family = default_font.actual()["family"]
    sans_family = _available_family(root, _SANS_FAMILIES, default_family)
    mono_family = _available_family(root, _MONOSPACE_FAMILIES, default_family)

    for name, original_size in named_fonts:
        named_font = font.nametofont(name, root=root)
        if original_size < 0:
            point_size = max(1, round(abs(original_size) / current_scaling))
        else:
            point_size = original_size
        family = mono_family if name == "TkFixedFont" else sans_family
        named_font.configure(family=family, size=point_size)


def configure_tk_scaling(root: tk.Tk) -> float:
    """Apply Linux Xft DPI to Tk and return the physical-pixel scale factor."""
    xft_dpi = _read_xft_dpi()
    if xft_dpi is None:
        return 1.0

    current_scaling = float(root.tk.call("tk", "scaling"))
    if not math.isfinite(current_scaling) or current_scaling <= 0:
        return 1.0

    named_fonts = tuple(
        (
            name,
            int(font.nametofont(name, root=root).cget("size")),
        )
        for name in font.names(root)
    )
    target_scaling = xft_dpi / 72
    scale_factor = target_scaling / current_scaling
    if not math.isfinite(scale_factor) or scale_factor <= 0:
        return 1.0
    if math.isclose(scale_factor, 1.0, rel_tol=0.01):
        return 1.0

    root.tk.call("tk", "scaling", target_scaling)
    _scale_named_fonts(root, current_scaling, named_fonts)
    return scale_factor

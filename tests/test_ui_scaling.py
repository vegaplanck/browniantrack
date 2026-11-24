import unittest
from unittest.mock import Mock, call, patch

from browniantrack.ui.scaling import configure_tk_scaling


class TkScalingTests(unittest.TestCase):
    def test_scales_tk_and_pixels_to_xft_dpi(self) -> None:
        root = Mock()
        root.tk.call.side_effect = [96 / 72, 192 / 72]
        with (
            patch("browniantrack.ui.scaling._read_xft_dpi", return_value=192),
            patch("browniantrack.ui.scaling.font.names", return_value=()),
            patch("browniantrack.ui.scaling._scale_named_fonts") as scale_fonts,
        ):
            scale_factor = configure_tk_scaling(root)

        self.assertAlmostEqual(scale_factor, 2)
        self.assertEqual(
            root.tk.call.call_args_list,
            [call("tk", "scaling"), call("tk", "scaling", 192 / 72)],
        )
        scale_fonts.assert_called_once_with(root, 96 / 72, ())

    def test_keeps_native_scaling_when_xft_dpi_is_unavailable(self) -> None:
        root = Mock()
        with patch("browniantrack.ui.scaling._read_xft_dpi", return_value=None):
            scale_factor = configure_tk_scaling(root)

        self.assertEqual(scale_factor, 1)
        root.tk.call.assert_not_called()

    def test_keeps_native_scaling_when_dpi_already_matches(self) -> None:
        root = Mock()
        root.tk.call.return_value = 96 / 72
        with (
            patch("browniantrack.ui.scaling._read_xft_dpi", return_value=96),
            patch("browniantrack.ui.scaling.font.names", return_value=()),
            patch("browniantrack.ui.scaling._scale_named_fonts") as scale_fonts,
        ):
            scale_factor = configure_tk_scaling(root)

        self.assertEqual(scale_factor, 1)
        root.tk.call.assert_called_once_with("tk", "scaling")
        scale_fonts.assert_not_called()


if __name__ == "__main__":
    unittest.main()

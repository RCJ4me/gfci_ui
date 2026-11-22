from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

import main  # noqa: E402
from preview_plot import PreviewSeries  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class StartupAndMemoryTests(unittest.TestCase):
    def test_startup_does_not_import_heavy_optional_modules(self):
        script = (
            "import sys, main; "
            "print(','.join(sorted(name for name in ("
            "'pandas','scipy','markdown','report_export','gfci_analysis'"
            ") if name in sys.modules)))"
        )
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        output = subprocess.check_output(
            [sys.executable, "-c", script],
            cwd=PROJECT_ROOT,
            env=env,
            text=True,
        ).strip()

        self.assertEqual(output, "")

    def test_windows_spec_uses_onedir_collect_mode(self):
        spec = (PROJECT_ROOT / "gfci_gui.spec").read_text(encoding="utf-8")
        windows_section = spec.split('elif sys.platform == "win32":', 1)[1]

        self.assertIn("exclude_binaries=True", windows_section)
        self.assertIn("collection = COLLECT", windows_section)

    def test_process_memory_is_available_on_current_platform(self):
        memory_mb = main.process_memory_mb()

        self.assertIsNotNone(memory_mb)
        self.assertGreater(memory_mb, 0.0)

    def test_release_interactive_data_clears_arrays_sources_and_combo(self):
        app = QApplication.instance() or QApplication([])
        window = main.MainWindow()
        time_ms = np.linspace(0.0, 100.0, 10000)
        window.preview_plot.set_series(
            PreviewSeries(
                time_ms=time_ms,
                amplitude=np.sin(time_ms),
                unit="mV",
                title="preview",
            )
        )
        window._plot_sources.append(
            main.PlotSource("source", "continuous", "/tmp/source.csv")
        )
        window.ui.combo_curve_image.addItem("source")
        window._release_interactive_data()

        self.assertFalse(window.preview_plot.has_data())
        self.assertIsNone(window.preview_plot.series)
        self.assertFalse(window.plot_view.has_data())
        self.assertEqual(window._plot_sources, [])
        self.assertEqual(window.ui.combo_curve_image.count(), 0)
        window.close()
        self.assertIsNotNone(app)

    def test_analysis_finished_clears_worker_reference(self):
        app = QApplication.instance() or QApplication([])
        window = main.MainWindow()
        window.worker = mock.Mock()

        window.on_finished(1, 0, 0)

        self.assertIsNone(window.worker)
        window.close()
        self.assertIsNotNone(app)


if __name__ == "__main__":
    unittest.main()

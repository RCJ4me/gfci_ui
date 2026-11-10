from __future__ import annotations

import math
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENGINE_ROOT = PROJECT_ROOT.parent / "gfci_analysis_refactored"
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(ENGINE_ROOT))

from PyQt6.QtGui import QIcon, QImage  # noqa: E402
from PyQt6.QtPdf import QPdfDocument  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import main  # noqa: E402
import report_export  # noqa: E402
from gfci_analysis.io.reader import parse_mso54_csv  # noqa: E402


MSO44_SINGLE_CHANNEL = """\
Model,MSO44
Waveform Type,ANALOG
Horizontal Units,s
Sample Interval,8.00000000e-07
Record Length,10000001
Zero Index,5000000
Vertical Units,A
ANALOG_Thumbnail,CH4_DECI
,
TIME,CH4
-4.00E+00,8.26562500e-03
-4.00E+00,3.28125000e-03
-4.00E+00,-5.68E-03
-4.00E+00,-1.13E-02
-4.00E+00,-1.18E-02
-4.00E+00,-6.92E-03
"""

MSO54_THREE_CHANNELS = """\
Model,MSO54
Channel,CH1,,Channel,CH2,,Channel,CH3
Vertical Units,V,,Vertical Units,V,,Vertical Units,V
Sample Interval,1.00000000e-01,,Sample Interval,1.00000000e-01,,Sample Interval,1.00000000e-01
Record Length,5,,Record Length,5,,Record Length,5
Zero Index,2.00000000,,Zero Index,2.00000000,,Zero Index,2.00000000
Labels,,,
TIME,CH1,CH2,CH3
0.0,1.0,2.0,3.0
0.1,1.1,2.1,3.1
0.2,1.2,2.2,3.2
0.3,1.3,2.3,3.3
0.4,1.4,2.4,3.4
"""


class OscilloscopeCompatibilityTests(unittest.TestCase):
    def _write_csv(
        self,
        directory: str,
        text: str,
        name: str = "capture.csv",
    ) -> Path:
        path = Path(directory) / name
        path.write_text(text, encoding="utf-8")
        return path

    def _write_image(self, directory: Path, name: str) -> Path:
        path = directory / name
        image = QImage(32, 18, QImage.Format.Format_RGB32)
        image.fill(0xFFFFFF)
        self.assertTrue(image.save(str(path)))
        return path

    def _write_waveform_csv(self, directory: Path) -> Path:
        sample_interval = 0.001
        sample_count = 512
        lines = [
            "Model,MSO54",
            "Channel,CH1",
            "Vertical Units,V",
            f"Sample Interval,{sample_interval}",
            f"Record Length,{sample_count}",
            "Zero Index,0",
            "Labels,,,",
            "TIME,CH1",
        ]
        for index in range(sample_count):
            time_sec = index * sample_interval
            value = (
                0.01 * math.sin(2 * math.pi * 60 * time_sec)
                + 0.002 * math.sin(2 * math.pi * 180 * time_sec)
            )
            lines.append(f"{time_sec:.8f},{value:.10f}")
        path = directory / "capture.csv"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_mso44_ch4_thumbnail_uses_full_metadata_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_csv(directory, MSO44_SINGLE_CHANNEL)
            data = parse_mso54_csv(str(path))

        self.assertEqual(data.channel_names(), ["ch4"])
        self.assertEqual(data.value_unit, "A")
        self.assertEqual(len(data.time_sec), 6)
        self.assertAlmostEqual(data.time_sec[0], 0.0)
        self.assertAlmostEqual(data.time_sec[-1], 8.0)
        self.assertAlmostEqual(data.sample_interval, 1.6)

    def test_mso54_three_voltage_channels_regression(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_csv(directory, MSO54_THREE_CHANNELS)
            data = parse_mso54_csv(str(path))

        self.assertEqual(data.channel_names(), ["ch1", "ch2", "ch3"])
        self.assertEqual(data.value_unit, "V")
        self.assertAlmostEqual(data.sample_interval, 0.1)
        self.assertAlmostEqual(data.time_sec[-1], 0.4)

    def test_csv_structure_reads_mso44_header_and_unit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_csv(directory, MSO44_SINGLE_CHANNEL)
            channels, units = main.read_csv_structure(str(path))

        self.assertEqual(channels, ["CH4"])
        self.assertEqual(units, {"A"})

    def test_csv_duration_and_encoding_failure_are_handled(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_csv(directory, MSO54_THREE_CHANNELS)
            self.assertAlmostEqual(main.read_csv_duration(str(path)), 0.4)
            without_record_length = MSO54_THREE_CHANNELS.replace(
                "Record Length,5,,Record Length,5,,Record Length,5\n",
                "",
            )
            fallback_path = self._write_csv(
                directory,
                without_record_length,
                "fallback.csv",
            )
            self.assertAlmostEqual(main.read_csv_duration(str(fallback_path)), 0.4)

        with mock.patch("builtins.open", side_effect=LookupError):
            self.assertEqual(main.read_csv_structure("broken.csv"), ([], set()))

    def test_single_file_with_mixed_units_is_rejected(self):
        mixed_units = MSO44_SINGLE_CHANNEL.replace(
            "Vertical Units,A",
            "Vertical Units,A,V",
        )
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_csv(directory, mixed_units)
            with self.assertRaisesRegex(ValueError, "Mixed vertical units"):
                parse_mso54_csv(str(path))

    def test_channel_combo_tracks_loaded_file_and_clears(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_csv(directory, MSO44_SINGLE_CHANNEL)
            window = main.MainWindow()
            window.ui.list_files.addItem(str(path))
            window._refresh_channels()

            self.assertEqual(window.ui.combo_channel.currentText(), "CH4")
            self.assertEqual(
                window.ui.lbl_overlimit.text(),
                "Base Over-limit Threshold (mA)",
            )

            window.ui.list_files.clear()
            window._refresh_channels()

            self.assertEqual(window.ui.combo_channel.count(), 0)
            self.assertEqual(
                window.ui.lbl_overlimit.text(),
                "Base Over-limit Threshold (mV)",
            )
            window.close()
        self.assertIsNotNone(app)

    def test_main_layout_uses_39_61_ratio_and_three_result_tabs(self):
        app = QApplication.instance() or QApplication([])
        window = main.MainWindow()
        window.resize(936, 757)
        window.show()
        app.processEvents()

        labels = [
            window.ui.tab_results.tabText(index)
            for index in range(window.ui.tab_results.count())
        ]
        self.assertEqual(labels, ["Curve Plot", "Test Report", "Log"])
        self.assertEqual(window.ui.mainLayout.stretch(0), 39)
        self.assertEqual(window.ui.mainLayout.stretch(1), 61)
        self.assertEqual(window.ui.groupBox_input.minimumWidth(), 320)

        left_width = window.ui.groupBox_input.width()
        right_width = window.ui.tab_results.width()
        ratio = left_width / (left_width + right_width)
        self.assertAlmostEqual(ratio, 0.39, delta=0.01)

        window.close()
        self.assertIsNotNone(app)

    def test_bundled_windows_icon_contains_taskbar_sizes(self):
        app = QApplication.instance() or QApplication([])
        icon = QIcon(str(PROJECT_ROOT / "assets" / "torchdragon.ico"))
        sizes = {
            (size.width(), size.height())
            for size in icon.availableSizes()
        }

        self.assertFalse(icon.isNull())
        self.assertLessEqual(
            {(16, 16), (32, 32), (48, 48), (256, 256)},
            sizes,
        )
        self.assertIsNotNone(app)

    def test_windows_app_id_is_set_explicitly(self):
        import ctypes

        shell32 = mock.Mock()
        set_app_id = shell32.SetCurrentProcessExplicitAppUserModelID
        set_app_id.return_value = 0
        with mock.patch.object(
            main.sys,
            "platform",
            "win32",
        ), mock.patch.object(
            ctypes,
            "WinDLL",
            create=True,
            return_value=shell32,
        ):
            configured = main.configure_windows_app_id()

        self.assertTrue(configured)
        set_app_id.assert_called_once_with(main.APP_USER_MODEL_ID)

    def test_windows_native_taskbar_icon_uses_window_handle(self):
        import ctypes

        user32 = mock.Mock()
        load_image = user32.LoadImageW
        load_image.return_value = 1234
        send_message = user32.SendMessageW
        fake_window = mock.Mock()
        fake_window.winId.return_value = 5678

        with tempfile.TemporaryDirectory() as directory:
            icon_path = Path(directory) / "app.ico"
            icon_path.write_bytes(b"ico")
            with mock.patch.object(
                main.sys,
                "platform",
                "win32",
            ), mock.patch.object(
                ctypes,
                "WinDLL",
                create=True,
                return_value=user32,
            ):
                applied = main.apply_windows_taskbar_icon(
                    fake_window,
                    icon_path,
                )

        self.assertTrue(applied)
        load_image.assert_called_once_with(
            None,
            str(icon_path),
            main.IMAGE_ICON,
            0,
            0,
            main.LR_LOADFROMFILE | main.LR_DEFAULTSIZE,
        )
        self.assertEqual(
            send_message.call_args_list,
            [
                mock.call(5678, main.WM_SETICON, main.ICON_SMALL, 1234),
                mock.call(5678, main.WM_SETICON, main.ICON_BIG, 1234),
            ],
        )
        self.assertEqual(fake_window._windows_taskbar_icon, 1234)

    def test_curve_gallery_accumulates_current_run_and_opens_report_folder(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            window = main.MainWindow()
            self.assertFalse(window.ui.btn_open_export_folder.isEnabled())
            self.assertEqual(window.ui.tab_results.tabText(0), "Curve Plot")
            self.assertEqual(window.ui.tab_results.tabText(1), "Test Report")
            self.assertEqual(window.ui.tab_results.tabText(2), "Log")

            first_images = [
                self._write_image(root, name)
                for name in (
                    "Continuous Plot first.png",
                    "CH3_Plot_first_3.000s_3.032s.png",
                    "FFT Raw RMS Signal first.png",
                    "FFT Post Letgo RMS Signal first.png",
                )
            ]
            first_report = root / "first" / "Summary_Report.md"
            first_report.parent.mkdir()
            first_report.write_text("# First report", encoding="utf-8")

            window.on_file_done(
                "first.csv",
                *(str(path) for path in first_images),
                str(first_report),
                "# First report",
            )

            combo = window.ui.combo_curve_image
            self.assertEqual(combo.count(), 4)
            self.assertEqual(
                [combo.itemText(index) for index in range(combo.count())],
                [path.name for path in first_images],
            )
            self.assertEqual(combo.currentIndex(), 3)
            self.assertEqual(combo.currentData(), str(first_images[3]))
            self.assertTrue(window.ui.btn_open_export_folder.isEnabled())

            second_images = [
                self._write_image(root, name.replace("first", "second"))
                for name in (
                    "Continuous Plot first.png",
                    "CH3_Plot_first_3.000s_3.032s.png",
                    "FFT Raw RMS Signal first.png",
                    "FFT Post Letgo RMS Signal first.png",
                )
            ]
            second_report = root / "second" / "Summary_Report.md"
            second_report.parent.mkdir()
            second_report.write_text("# Second report", encoding="utf-8")

            window.on_file_done(
                "second.csv",
                *(str(path) for path in second_images),
                str(second_report),
                "# Second report",
            )

            self.assertEqual(combo.count(), 8)
            self.assertEqual(combo.currentIndex(), 7)
            self.assertEqual(combo.currentData(), str(second_images[3]))
            combo.setCurrentIndex(0)
            self.assertEqual(combo.currentData(), str(first_images[0]))

            with mock.patch.object(
                main.QDesktopServices,
                "openUrl",
                return_value=True,
            ) as open_url:
                window.open_export_folder()
            opened_url = open_url.call_args.args[0]
            self.assertEqual(
                Path(opened_url.toLocalFile()),
                second_report.parent.resolve(),
            )

            window._reset_curve_gallery()
            self.assertEqual(combo.count(), 0)
            self.assertEqual(window._curve_images, [])

            single_image = self._write_image(
                root,
                "FFT Post Letgo RMS Signal single.png",
            )
            single_report = root / "single" / "Summary_Report.md"
            single_report.parent.mkdir()
            single_report.write_text("# Single report", encoding="utf-8")
            window.on_file_done(
                "single.csv",
                "",
                "",
                "",
                str(single_image),
                str(single_report),
                "# Single report",
            )
            self.assertEqual(combo.count(), 1)
            self.assertEqual(combo.currentIndex(), 0)
            self.assertIsNotNone(window.ui.view_curve._pixmap)
            window.close()
        self.assertIsNotNone(app)

    def test_worker_skips_file_without_selected_channel(self):
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_csv(directory, MSO44_SINGLE_CHANNEL)
            worker = main.AnalysisWorker(
                [str(path)],
                {
                    "time_start": 3.0,
                    "time_end": 3.032,
                    "fft_min": 40,
                    "fft_max": 100000,
                    "channel": "ch3",
                    "overlimit": 3.0,
                    "picture_format": 0,
                    "output_dir": directory,
                },
            )
            logs = []
            outcomes = []
            worker.log.connect(logs.append)
            worker.finished_ok.connect(
                lambda success, failed, skipped: outcomes.append(
                    (success, failed, skipped)
                )
            )

            worker.run()

        self.assertEqual(outcomes, [(0, 0, 1)])
        self.assertTrue(any("Skipped" in message for message in logs))

    def test_run_analysis_blocks_mixed_voltage_and_current_files(self):
        app = QApplication.instance() or QApplication([])
        voltage_capture = MSO44_SINGLE_CHANNEL.replace(
            "Vertical Units,A",
            "Vertical Units,V",
        )
        with tempfile.TemporaryDirectory() as directory:
            current_path = self._write_csv(
                directory, MSO44_SINGLE_CHANNEL, "current.csv"
            )
            voltage_path = self._write_csv(
                directory, voltage_capture, "voltage.csv"
            )
            window = main.MainWindow()
            window.ui.list_files.addItem(str(current_path))
            window.ui.list_files.addItem(str(voltage_path))
            window._refresh_channels()

            with mock.patch.object(main.QMessageBox, "warning") as warning:
                window.run_analysis()

            warning.assert_called_once()
            self.assertIsNone(window.worker)
            window.close()
        self.assertIsNotNone(app)

    def test_run_analysis_blocks_time_window_beyond_each_csv_duration(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            first_path = self._write_csv(
                directory,
                MSO54_THREE_CHANNELS,
                "first.csv",
            )
            second_path = self._write_csv(
                directory,
                MSO54_THREE_CHANNELS,
                "second.csv",
            )
            window = main.MainWindow()
            window.ui.list_files.addItem(str(first_path))
            window.ui.list_files.addItem(str(second_path))
            window._refresh_channels()
            window.ui.spin_time_start.setValue(0.3)
            window.ui.spin_time_end.setValue(0.5)

            with mock.patch.object(main.QMessageBox, "warning") as warning:
                window.run_analysis()

            warning.assert_called_once()
            title, message = warning.call_args.args[1:3]
            self.assertEqual(title, "Time Window Out of Range")
            self.assertIn("first.csv: data duration 0.400000 s", message)
            self.assertIn("second.csv: data duration 0.400000 s", message)
            self.assertIn("Analysis was not started.", message)
            self.assertIsNone(window.worker)
            window.close()
        self.assertIsNotNone(app)

    def test_report_pdf_matches_markdown_name_and_overwrites(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            markdown_path = root / "Summary_Report_LCSD_GFCI.md"
            markdown_path.write_text(
                "# Custom Report\n\n| Channel | Value |\n"
                "|:--|--:|\n| **CH1** | 1.000 |\n",
                encoding="utf-8",
            )

            pdf_path = report_export.export_markdown_to_pdf(markdown_path)
            first_pdf = pdf_path.read_bytes()

            self.assertEqual(
                report_export.pdf_path_for_markdown(markdown_path),
                root / "Summary_Report_LCSD_GFCI.pdf",
            )
            self.assertEqual(pdf_path, root / "Summary_Report_LCSD_GFCI.pdf")
            self.assertEqual(pdf_path.parent, markdown_path.parent)
            self.assertEqual(pdf_path.stem, markdown_path.stem)
            self.assertTrue(first_pdf.startswith(b"%PDF-"))
            self.assertGreater(len(first_pdf), 0)

            with markdown_path.open("a", encoding="utf-8") as report:
                report.write(
                    "\n# Appended Report Section\n\n"
                    + "Appended report body. " * 2000
                )
            overwritten_path = report_export.export_markdown_to_pdf(
                markdown_path
            )
            second_pdf = overwritten_path.read_bytes()

            self.assertEqual(overwritten_path, pdf_path)
            self.assertTrue(second_pdf.startswith(b"%PDF-"))
            self.assertNotEqual(second_pdf, first_pdf)
            page_counts = re.findall(rb"/Count\s+(\d+)", second_pdf)
            self.assertTrue(page_counts)
            self.assertGreater(int(page_counts[0]), 1)
            self.assertEqual(list(root.glob("*.pdf")), [pdf_path])
        self.assertIsNotNone(app)

    def test_report_pdf_handles_missing_input_and_write_failure(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = root / "Missing Report.md"
            with self.assertRaises(FileNotFoundError):
                report_export.export_markdown_to_pdf(missing)

            markdown_path = root / "Custom Report.md"
            original_markdown = "# Kept Report\n\nMarkdown remains."
            markdown_path.write_text(original_markdown, encoding="utf-8")
            with mock.patch.object(
                report_export,
                "_write_pdf",
                side_effect=OSError("disk full"),
            ):
                with self.assertRaises(report_export.ReportExportError):
                    report_export.export_markdown_to_pdf(markdown_path)

            self.assertEqual(
                markdown_path.read_text(encoding="utf-8"),
                original_markdown,
            )
            self.assertFalse((root / "Custom Report.pdf").exists())
        self.assertIsNotNone(app)

    def test_report_pdf_embeds_images_from_the_report_directory(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image_path = self._write_image(root, "curve.png")
            markdown_path = root / "Report.md"
            markdown_path.write_text(
                f"# Image Report\n\n![Curve]({image_path.as_uri()})\n",
                encoding="utf-8",
            )

            html_text = report_export.render_report_html(
                markdown_path.read_text(encoding="utf-8"),
                root,
                max_image_width_px=320,
                max_image_height_px=320,
            )
            pdf_path = report_export.export_markdown_to_pdf(markdown_path)
            pdf_bytes = pdf_path.read_bytes()

        self.assertIn(f'<base href="{root.resolve().as_uri()}/">', html_text)
        self.assertIn(
            f'<img alt="Curve" src="{image_path.as_uri()}" '
            'width="320" height="180">',
            html_text,
        )
        self.assertIn(b"/Subtype /Image", pdf_bytes)
        self.assertIsNotNone(app)

    def test_report_preview_omits_images_and_page_breaks(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image_path = self._write_image(root, "curve.png")
            markdown_text = (
                "# Preview Report\n\n"
                "**Test conclusion:** "
                '<span style="color: #15803d;">PASS</span>\n\n'
                f"![Curve]({image_path.as_uri()})\n\n"
                '<div class="pdf-page-break" '
                'style="page-break-before: always;"></div>\n\n'
                "## Next Section\n\nReport data remains."
            )

            pdf_html = report_export.render_report_html(
                markdown_text,
                root,
            )
            preview_html = report_export.render_report_html(
                markdown_text,
                root,
                include_images=False,
                include_page_breaks=False,
            )

        self.assertIn("<img", pdf_html)
        self.assertIn("pdf-page-break", pdf_html)
        self.assertNotIn("<img", preview_html)
        self.assertNotIn("pdf-page-break", preview_html)
        self.assertIn("Test conclusion", preview_html)
        self.assertIn("PASS", preview_html)
        self.assertIn("Report data remains.", preview_html)
        self.assertIsNotNone(app)

    def test_pdf_image_limits_preserve_aspect_ratio_inside_a4(self):
        max_width, max_height = report_export.pdf_image_size_limits()

        self.assertLess(max_width, 703)
        self.assertEqual(
            report_export._scaled_image_dimensions(
                4000,
                2000,
                max_width,
                max_height,
            ),
            (max_width, round(max_width / 2)),
        )
        self.assertEqual(
            report_export._scaled_image_dimensions(
                1000,
                4000,
                max_width,
                max_height,
            ),
            (round(max_height / 4), max_height),
        )

    def test_worker_callback_exports_pdf_and_removes_markdown(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = self._write_waveform_csv(root)
            output_dir = root / "export"
            window = main.MainWindow()
            worker = main.AnalysisWorker(
                [str(source_path)],
                {
                    "time_start": 0.2,
                    "time_end": 0.4,
                    "fft_min": 40,
                    "fft_max": 250,
                    "channel": "ch1",
                    "overlimit": 3.5,
                    "picture_format": 0,
                    "output_dir": str(output_dir),
                },
                window,
            )
            callbacks = []
            outcomes = []
            worker.file_done.connect(lambda *args: callbacks.append(args))
            worker.finished_ok.connect(
                lambda success, failed, skipped: outcomes.append(
                    (success, failed, skipped)
                )
            )

            worker.run()
            self.assertEqual(outcomes, [(1, 0, 0)])
            self.assertEqual(len(callbacks), 1)

            window.on_file_done(*callbacks[0])
            report_path = Path(callbacks[0][5])
            pdf_path = report_path.with_suffix(".pdf")
            expected_dir = output_dir / source_path.stem

            self.assertEqual(report_path.parent, expected_dir)
            self.assertEqual(report_path.name, "Summary_Report_LCSD_GFCI.md")
            self.assertFalse(report_path.exists())
            self.assertTrue(pdf_path.is_file())
            pdf_bytes = pdf_path.read_bytes()
            self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
            self.assertGreater(pdf_path.stat().st_size, 0)
            self.assertGreaterEqual(pdf_bytes.count(b"/Subtype /Image"), 4)
            page_counts = re.findall(rb"/Count\s+(\d+)", pdf_bytes)
            self.assertIn(b"4", page_counts)
            pdf_document = QPdfDocument(None)
            pdf_document.load(str(pdf_path))
            self.assertEqual(pdf_document.pageCount(), 4)
            page_texts = [
                pdf_document.getAllText(index).text()
                for index in range(pdf_document.pageCount())
            ]
            pdf_document.close()
            self.assertIn("Full Time Window Statistics", page_texts[0])
            self.assertNotIn(
                "Time Window Statistics",
                page_texts[0].replace("Full Time Window Statistics", ""),
            )
            self.assertIn("0.200 s-0.400 s Time Window Statistics", page_texts[1])
            self.assertIn("FFT RMS Value Analysis (CH1 raw)", page_texts[2])
            self.assertIn(
                "FFT RMS Value Analysis (CH1 post-letgo)",
                page_texts[3],
            )
            self.assertIn("Test conclusion:", page_texts[0])
            self.assertIn("Test conclusion:", page_texts[1])
            self.assertNotIn("Test conclusion:", page_texts[2])
            self.assertNotIn("Test conclusion:", page_texts[3])
            self.assertEqual(window._current_report_path, str(pdf_path))
            self.assertIn(
                "Markdown removed",
                window.ui.txt_log.toPlainText(),
            )
            self.assertIn(
                "GFCI Interoperability Test Report",
                window.ui.txt_report.toPlainText(),
            )
            self.assertIn(
                "Test conclusion:",
                window.ui.txt_report.toPlainText(),
            )
            self.assertNotIn("<img", window.ui.txt_report.toHtml().lower())
            self.assertNotIn(
                "pdf-page-break",
                window.ui.txt_report.toHtml(),
            )
            self.assertTrue(window.ui.btn_open_export_folder.isEnabled())
            self.assertEqual(window.ui.tab_results.tabText(1), "Test Report")

            with mock.patch.object(
                main.QDesktopServices,
                "openUrl",
                return_value=True,
            ) as open_url:
                window.open_export_folder()
            self.assertEqual(
                Path(open_url.call_args.args[0].toLocalFile()),
                expected_dir.resolve(),
            )
            window.close()
        self.assertIsNotNone(app)

    def test_pdf_failure_keeps_markdown_and_does_not_block_callback(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report_path = root / "Summary_Report_LCSD_GFCI.md"
            report_path.write_text(
                "# Test Report\n\nMarkdown remains.",
                encoding="utf-8",
            )
            window = main.MainWindow()

            with mock.patch.object(
                main,
                "export_markdown_to_pdf",
                side_effect=OSError("disk full"),
            ), mock.patch.object(
                window,
                "_show_export_warning",
            ) as show_warning:
                window.on_file_done(
                    "sample.csv",
                    "",
                    "",
                    "",
                    "",
                    str(report_path),
                    "# Test Report\n\nMarkdown remains.",
                )

            show_warning.assert_called_once()
            self.assertTrue(report_path.is_file())
            self.assertEqual(window._current_report_path, str(report_path))
            self.assertTrue(window.ui.btn_open_export_folder.isEnabled())
            self.assertIn(
                "PDF export failed",
                window.ui.txt_log.toPlainText(),
            )

            missing_report = root / "Missing Report.md"
            with mock.patch.object(
                window,
                "_show_export_warning",
            ) as missing_warning:
                window.on_file_done(
                    "missing.csv",
                    "",
                    "",
                    "",
                    "",
                    str(missing_report),
                    "",
                )

            missing_warning.assert_called_once()
            self.assertFalse(missing_report.exists())
            self.assertFalse(window.ui.btn_open_export_folder.isEnabled())
            window.close()
        self.assertIsNotNone(app)

    def test_actual_tek002_has_data_in_default_window(self):
        path = PROJECT_ROOT / "raw_data" / "Tek002.csv"
        if not path.is_file():
            self.skipTest("raw_data/Tek002.csv is not available")

        data = parse_mso54_csv(str(path))

        self.assertEqual(data.channel_names(), ["ch4"])
        self.assertEqual(data.value_unit, "A")
        self.assertAlmostEqual(data.time_sec[-1], 8.0, places=5)
        self.assertTrue(((data.time_sec >= 3.0) & (data.time_sec <= 3.032)).any())


if __name__ == "__main__":
    unittest.main()

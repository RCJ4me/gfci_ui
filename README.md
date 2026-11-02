# GFCI Oscilloscope Data Analysis Tool - PyQt6 GUI

A non-programmer-friendly desktop GUI for `gfci_analysis` (UL101 Sec.6 GFCI interoperability test analysis).

The analysis engine lives in the sibling repository `../gfci_analysis_refactored`
(package `gfci_analysis`). The GUI imports it from there; if a `gfci_analysis/`
package is placed inside this folder it takes precedence, which makes it easy to
try out engine edits locally before syncing them back.

The reader supports Tektronix MSO44 and MSO54 CSV exports, including
single-channel captures such as `CH4` and decimated thumbnail exports. Channel
names and vertical units are read from each source CSV rather than assumed from
the previous three-channel data format.

## Directory Structure

```
gfci_gui/
|-- window.ui        # Qt Designer project file (edit repeatedly)
|-- window_ui.py     # Python UI code generated from window.ui (do not edit by hand)
|-- main.py          # Main program: signals, file selection, background analysis thread
|-- image_view.py    # Zoomable / pannable image view used by the plot tabs
|-- requirements.txt # Dependency list
`-- README.md
```

## Run

> **Python version:** use a standalone CPython 3.10-3.12 (the repo pins 3.11 via
> `.python-version`). Do **not** build the environment on top of an Anaconda
> interpreter: Anaconda ships its own Qt6 DLLs, and PyQt6 then fails to load
> with `ImportError: DLL load failed while importing QtWidgets`. Python 3.14 is
> also unsupported because the numpy/scipy wheels for it are not yet reliable.

```bash
# 1. Install dependencies (recommended: uv)
uv sync

# 2. Launch the GUI
uv run python main.py
```

Alternatively, with a plain virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## Build standalone applications

The project includes cross-platform PyInstaller configuration for building a
macOS `.app` on macOS and a single-file Windows `.exe` on Windows. Python does
not need to be installed on the target computer.

See [PACKAGING.md](PACKAGING.md) for prerequisites, build commands, signing
notes, and troubleshooting.

> The program calls `gfci_analysis.pipeline.run_pipeline` from
> `../gfci_analysis_refactored` (or from a `gfci_analysis/` package inside this
> folder when one is present). Make sure numpy / pandas / scipy / matplotlib are
> installed. `markdown` is used by the GUI to render the report tab as a Markdown
> preview.

## Usage

1. **Add CSV**: Click "Add CSV" to select one or more Tektronix MSO44 or MSO54 export files.
2. **Set parameters**: choose a channel populated from the loaded CSV headers (for example, `CH4`), the time range, FFT frequency range, base over-limit threshold, image format, and output directory. The threshold label follows the source unit: `mV` for voltage channels and `mA` for current channels. The analysis engine scales the threshold by frequency before comparing FFT peaks.
3. **Run analysis**: Click "Run Analysis". The right-hand tabs show the time-domain plot, FFT plot, a rendered Markdown report, and the log.
4. Output files (PNG/SVG, CSV, Markdown report) are saved below the "Output Directory" in a subdirectory named after each source CSV, for example `Output Directory/SD_heat_120F_COMPRESSORON_000_ALL/`.

The channel list is rebuilt whenever files are added, removed, or cleared. If
multiple files have different channel sets, the selected channel is applied only
to files that contain it; the other files are skipped and reported in the log.
Files using voltage (`V`) and current (`A`) must be analyzed in separate runs so
one threshold value always has one physical meaning.

When `Record Length` and `Sample Interval` show that a CSV is a decimated
thumbnail export, the reader uses the metadata record duration and actual row
count to calculate the effective sample interval. This keeps the three-second
analysis window meaningful for MSO44 captures such as `Tek002.csv`.

While a run is in progress the progress bar advances through the individual pipeline
stages (reading the CSV, Let-go filtering, each plot, each CSV export, the FFT
analysis, the report) rather than jumping once per file, and the status bar names
the step that is currently running. The version number and the author are shown in
the bottom-left corner of the window.

### Plot tabs

Each plot tab has a small toolbar above the picture:

| Control | Action |
| --- | --- |
| `-` | Zoom out (one step, 1.25x) |
| `+` | Zoom in (one step, 1.25x) |
| `Fit` | Scale the picture so its width matches the window, leaving a small margin |

A freshly generated plot is fitted to the window width automatically, and stays
fitted when the window is resized. After you zoom in the picture keeps its manual
scale, and you can drag it with the left mouse button to move around; press `Fit`
to snap back to the window width.

## Editing the UI with Qt Designer

This project keeps `window.ui`, which can be opened directly with Qt Designer:

```bash
# Open the designer
designer window.ui

# or on macOS right-click window.ui -> Open With -> Qt Designer
```

After saving changes, regenerate `window_ui.py`:

```bash
pyuic6 -o window_ui.py window.ui
```

> Note: `window_ui.py` is auto-generated; do not edit it by hand. Put all logic in `main.py`.

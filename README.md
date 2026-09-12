# GFCI Oscilloscope Data Analysis Tool - PyQt6 GUI

A non-programmer-friendly desktop GUI for `gfci_analysis` (UL101 Sec.6 GFCI interoperability test analysis).

The analysis engine lives in the sibling repository `../gfci_analysis_refactored`
(package `gfci_analysis`). The GUI imports it from there; if a `gfci_analysis/`
package is placed inside this folder it takes precedence, which makes it easy to
try out engine edits locally before syncing them back.

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

```bash
# 1. Install dependencies (recommended: uv or venv)
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Launch the GUI
python main.py
```

> The program calls `gfci_analysis.pipeline.run_pipeline` from
> `../gfci_analysis_refactored` (or from a `gfci_analysis/` package inside this
> folder when one is present). Make sure numpy / pandas / scipy / matplotlib are
> installed. `markdown` is used by the GUI to render the report tab as a Markdown
> preview.

## Usage

1. **Add CSV**: Click "Add CSV" to select one or more MSO54 oscilloscope export files.
2. **Set parameters**: analysis channel (CH1/CH2/CH3, filled from the CSV headers), time range, FFT frequency range, over-limit threshold (mV), image format, output directory.
3. **Run analysis**: Click "Run Analysis". The right-hand tabs show the time-domain plot, FFT plot, a rendered Markdown report, and the log.
4. Output files (PNG/SVG, CSV, Markdown report) are saved to the "Output Directory".

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

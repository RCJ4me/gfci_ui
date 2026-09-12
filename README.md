# GFCI Oscilloscope Data Analysis Tool - PyQt6 GUI

A non-programmer-friendly desktop GUI for `gfci_analysis` (UL101 Sec.6 GFCI interoperability test analysis).

The analysis engine ships inside this project as the `gfci_analysis/` package, so the
GUI runs on its own. A sibling `../gfci_analysis_refactored` directory is also
accepted: when present it is used as a fallback, otherwise the bundled engine is used.

## Directory Structure

```
gfci_gui/
|-- gfci_analysis/   # analysis engine bundled with the GUI
|-- window.ui        # Qt Designer project file (edit repeatedly)
|-- window_ui.py     # Python UI code generated from window.ui (do not edit by hand)
|-- main.py          # Main program: signals, file selection, background analysis thread
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

> The program calls `gfci_analysis.pipeline.run_pipeline` from the bundled engine
> (or from `../gfci_analysis_refactored` when that directory exists). Make sure
> numpy / pandas / scipy / matplotlib are installed. `markdown` is used by the GUI
> to render the report tab as a Markdown preview.

## Usage

1. **Add CSV**: Click "Add CSV" to select one or more MSO54 oscilloscope export files.
2. **Set parameters**: analysis channel (CH1/CH2/CH3, filled from the CSV headers), time range, FFT frequency range, over-limit threshold (mV), image format, output directory.
3. **Run analysis**: Click "Run Analysis". The right-hand tabs show the time-domain plot, FFT plot, a rendered Markdown report, and the log.
4. Output files (PNG/SVG, CSV, Markdown report) are saved to the "Output Directory".

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

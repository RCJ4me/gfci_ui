# -*- coding: utf-8 -*-
"""Build the GFCI Analyzer standalone application with PyInstaller.

This script is invoked by ``build_windows.bat`` and ``build_macos.command``.
It locates the ``gfci_analysis`` engine, points PyInstaller at ``gfci_gui.spec``
and forwards a few convenience options (app name, icon, engine path).

Usage:
    uv run --extra build python scripts/build_app.py [options]

Options:
    --engine-path PATH   Directory that contains the ``gfci_analysis`` package.
                         Defaults to ``../gfci_analysis_refactored`` next to the
                         project, then ``vendor/gfci_analysis_refactored``.
    --app-name NAME      Product name shown in the window / file name.
    --icon PATH          ``.ico`` on Windows, ``.icns`` on macOS.
    --clean              Remove the PyInstaller ``build``/``dist`` caches first.
    --noconfirm          Overwrite the output directory without asking.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SPEC_FILE = PROJECT_ROOT / "gfci_gui.spec"
DEFAULT_ICON = PROJECT_ROOT / "assets" / "torchdragon.ico"

# Candidate locations for the analysis engine, in priority order.
DEFAULT_ENGINE_CANDIDATES = [
    PROJECT_ROOT.parent / "gfci_analysis_refactored",
    PROJECT_ROOT / "vendor" / "gfci_analysis_refactored",
]


def find_engine(explicit: str | None) -> Path:
    """Return the directory that contains the ``gfci_analysis`` package."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    candidates.extend(DEFAULT_ENGINE_CANDIDATES)

    for candidate in candidates:
        root = candidate.resolve()
        if (root / "gfci_analysis" / "__init__.py").is_file():
            return root

    searched = "\n  ".join(str(c) for c in candidates)
    raise SystemExit(
        "Could not find the gfci_analysis package. Looked in:\n  "
        f"{searched}\n"
        "Pass --engine-path pointing at the directory that contains "
        "gfci_analysis/__init__.py."
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-path", default=None)
    parser.add_argument("--app-name", default=None)
    parser.add_argument("--icon", default=None)
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--noconfirm", action="store_true")
    return parser.parse_args(argv)


def convert_ico_to_icns(source: Path, output: Path) -> Path:
    """Convert an ICO file into a complete macOS iconset using Apple tools."""
    for command in ("sips", "iconutil"):
        if shutil.which(command) is None:
            raise SystemExit(
                f"Required macOS icon tool not found: {command}. "
                "Install the Xcode Command Line Tools with "
                "`xcode-select --install`."
            )

    output.parent.mkdir(parents=True, exist_ok=True)
    icon_sizes = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }

    with tempfile.TemporaryDirectory(
        prefix=f"{source.stem}-",
        dir=output.parent,
    ) as temporary:
        iconset = Path(temporary) / f"{source.stem}.iconset"
        iconset.mkdir()
        for filename, size in icon_sizes.items():
            subprocess.run(
                [
                    "sips",
                    "-s",
                    "format",
                    "png",
                    "-z",
                    str(size),
                    str(size),
                    str(source),
                    "--out",
                    str(iconset / filename),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        subprocess.run(
            [
                "iconutil",
                "--convert",
                "icns",
                "--output",
                str(output),
                str(iconset),
            ],
            check=True,
        )
    return output


def resolve_icon(explicit: str | None) -> Path | None:
    """Use the requested icon, or the bundled default, as the app icon."""
    source = Path(explicit).expanduser() if explicit else DEFAULT_ICON
    source = source.resolve()
    if not source.is_file():
        if explicit:
            raise SystemExit(f"Icon not found: {source}")
        return None

    if sys.platform != "darwin":
        return source
    if source.suffix.lower() == ".icns":
        return source
    if source.suffix.lower() != ".ico":
        raise SystemExit(
            f"Unsupported macOS icon format: {source.suffix or '(none)'}. "
            "Use an .ico or .icns file."
        )

    output = PROJECT_ROOT / "build" / "icons" / f"{source.stem}.icns"
    print(f"Converting app icon: {source} -> {output}")
    return convert_ico_to_icns(source, output)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    if not SPEC_FILE.is_file():
        raise SystemExit(f"Spec file not found: {SPEC_FILE}")

    engine_root = find_engine(args.engine_path)
    print(f"Using analysis engine: {engine_root}")

    if args.clean:
        for name in ("build", "dist"):
            target = PROJECT_ROOT / name
            if target.exists():
                print(f"Removing {target}")
                shutil.rmtree(target, ignore_errors=True)

    icon = resolve_icon(args.icon)

    env = os.environ.copy()
    env["GFCI_ANALYSIS_ROOT"] = str(engine_root)
    if args.app_name:
        env["GFCI_APP_NAME"] = args.app_name
    if icon:
        env["GFCI_APP_ICON"] = str(icon)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        str(SPEC_FILE),
        "--distpath",
        str(PROJECT_ROOT / "dist"),
        "--workpath",
        str(PROJECT_ROOT / "build"),
    ]
    if args.noconfirm:
        cmd.append("--noconfirm")

    print("Running:", " ".join(cmd))
    return subprocess.call(cmd, cwd=str(PROJECT_ROOT), env=env)


if __name__ == "__main__":
    raise SystemExit(main())

#!/bin/zsh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

uv sync --extra build
uv run --extra build python scripts/build_app.py "$@"

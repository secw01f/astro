#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "Checking Python environment..."
if ! command -v python3 &> /dev/null; then
  echo "python3 could not be found. Install Python first."
  exit 1
fi

echo "Starting Docker services..."
docker compose up -d --build

echo "Installing CLI..."
pushd client > /dev/null
CLI_MODE=""
if command -v pipx &> /dev/null; then
  pipx install --editable . --force
  CLI_MODE="pipx"
else
  echo "pipx not found; using a project virtualenv at client/.venv."
  echo "Install pipx (e.g. brew install pipx) for a global 'astro' on your PATH."
  python3 -m venv .venv
  # `python -m pip` works like pip/pip3 and avoids PEP 668 on system Python
  ./.venv/bin/python -m pip install -U pip
  ./.venv/bin/python -m pip install -e .
  CLI_MODE="venv"
fi
popd > /dev/null

echo ""
echo "Everything is ready:"
echo "   API: http://localhost:8000"
if [ "$CLI_MODE" = "pipx" ]; then
  echo "   CLI: astro (installed with pipx). Ensure ~/.local/bin is on your PATH."
else
  echo "   CLI: add client/.venv/bin to PATH for this shell, then run astro:"
  echo "        export PATH=\"$SCRIPT_DIR/client/.venv/bin:\$PATH\""
fi

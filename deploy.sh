#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "Checking Python environment..."
if ! command -v python3 &> /dev/null; then
  echo "python3 could not be found. Install Python first."
  exit 1
fi

echo "Ensuring secrets are configured in .env..."
python3 - <<'PY'
import base64
import os
import pathlib
import secrets

env_path = pathlib.Path(".env")
example_path = pathlib.Path(".env.example")

if not env_path.exists():
    if example_path.exists():
        env_path.write_text(example_path.read_text())
        print("  Created .env from .env.example")
    else:
        env_path.write_text("")
        print("  Created empty .env")

lines = env_path.read_text().splitlines()
values = {}
for line in lines:
    if "=" in line and not line.lstrip().startswith("#"):
        k, _, v = line.partition("=")
        values[k.strip()] = v.strip()


def set_key(key, value):
    global lines
    replaced = False
    new_lines = []
    for line in lines:
        if "=" in line and not line.lstrip().startswith("#") and line.split("=", 1)[0].strip() == key:
            new_lines.append(f"{key}={value}")
            replaced = True
        else:
            new_lines.append(line)
    if not replaced:
        new_lines.append(f"{key}={value}")
    lines = new_lines


def is_valid_fernet(value):
    try:
        return len(base64.urlsafe_b64decode(value.encode())) == 32
    except Exception:
        return False


secret_key = values.get("SECRET_KEY", "")
if secret_key in ("", "supersecretkey") or len(secret_key) < 64:
    set_key("SECRET_KEY", secrets.token_urlsafe(48))
    print("  Generated a new SECRET_KEY")
else:
    print("  SECRET_KEY already set")

credential_key = values.get("CREDENTIAL_ENCRYPTION_KEY", "")
if not is_valid_fernet(credential_key):
    # A Fernet key is 32 random bytes, url-safe base64 encoded.
    set_key("CREDENTIAL_ENCRYPTION_KEY", base64.urlsafe_b64encode(os.urandom(32)).decode())
    print("  Generated a new CREDENTIAL_ENCRYPTION_KEY")
else:
    print("  CREDENTIAL_ENCRYPTION_KEY already set")

env_path.write_text("\n".join(lines) + "\n")
PY

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

echo "Checking for stack bootstrap user file..."
if docker compose exec -T api sh -c 'test -f /api/stack_user.json'; then
  echo "To retrieve the stack user details, run: docker compose exec -T api sh -c 'cat /api/stack_user.json'"
else
  echo "stack_user.json not found in api container (it may be consumed already)."
fi

echo ""
echo "Configure the CLI (URL, login, and permanent account):"
if [ "$CLI_MODE" = "pipx" ]; then
  echo "   astro init"
else
  echo "   $SCRIPT_DIR/client/.venv/bin/astro init"
fi
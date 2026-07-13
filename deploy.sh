#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "Checking Python environment..."
if ! command -v python3 &> /dev/null; then
  echo "python3 could not be found. Install Python first."
  exit 1
fi

if [ ! -f .env ]; then
  echo "Generating .env with strong local secrets..."
  umask 077
  python3 - <<'PY'
import secrets
from pathlib import Path

postgres_user = "astro"
postgres_db = "astro"
postgres_password = secrets.token_urlsafe(32)
redis_password = secrets.token_urlsafe(32)

env = f"""JWT_SECRET_KEY={secrets.token_urlsafe(48)}
CREDENTIAL_ENCRYPTION_KEY={secrets.token_urlsafe(48)}
TOOLS_HMAC_SECRET={secrets.token_urlsafe(48)}
DEFAULT_TOOLS_BASE_URL=http://tools:7001
POSTGRES_USER={postgres_user}
POSTGRES_PASSWORD={postgres_password}
POSTGRES_DB={postgres_db}
DB_URL=postgresql+asyncpg://{postgres_user}:{postgres_password}@db:5432/{postgres_db}
REDIS_PASSWORD={redis_password}
REDIS_URL=redis://:{redis_password}@redis:6379
LLM_LIMITER_ENABLED=false
LLM_TOKEN_LIMIT_PER_MINUTE=30000
LLM_LIMITER_POLL_INTERVAL_MS=200
LLM_LIMITER_DEFAULT_OUTPUT_TOKENS=1024
LLM_LIMITER_MAX_WAIT_SECONDS=60
LLM_PROMPT_CACHE_ENABLED=false
LLM_PROMPT_CACHE_TTL_SECONDS=300
MEMORY_RECALL_MAX_ITEMS=5
MEMORY_LIST_MAX_ITEMS=10
MEMORY_ITEM_MAX_CHARS=400
TOOL_OUTPUT_MAX_CHARS=2000
MAX_UPLOAD_BYTES=10485760
OUTBOUND_ALLOWLIST=
DEFAULT_EXP_MINUTES=30
ENV=dev
"""
Path(".env").write_text(env)
Path(".env").chmod(0o600)
PY
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

echo "Checking for stack bootstrap user file..."
if docker compose exec -T api sh -c 'test -f /api/stack_user.json'; then
  echo "Bootstrap credentials exist in the api container."
  echo "Reveal them locally only when ready to complete first login:"
  echo "   docker compose exec -T api sh -c 'cat /api/stack_user.json'"
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

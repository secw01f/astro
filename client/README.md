# Astro CLI

CLI client for interacting with the Astro backend.

This package is a normal [PEP 517](https://peps.python.org/pep-0517/) project: you can install it with **pipx**, **pip**, or **pip3** as long as you avoid installing into a **PEP 668** “externally managed” system Python (use a virtual environment or pipx).

## Install with pipx (recommended for a global `astro` command)

From this directory (`client/`):

```bash
pipx install --editable .
```

To refresh after pulling changes:

```bash
pipx install --editable . --force
```

On Linux and macOS, ensure `~/.local/bin` is on your `PATH` (pipx’s default). On Windows, pipx usually adds `%USERPROFILE%\.local\bin`; if `astro` is not found, run `pipx ensurepath` and open a new terminal.

## First-time setup

After the API is running (for example via `./deploy.sh` from the repo root):

```bash
astro init
```

The wizard saves `~/.astro/config.json`, checks that the API is reachable, logs in with the one-time `stack` credentials from deploy, then walks you through creating a permanent user and setting a password. Use `astro config show` to inspect settings later.

## Install with pip or pip3 (virtual environment)

On macOS/Homebrew Python, `pip install` / `pip3 install` into the system interpreter is often blocked. Use a venv and **`python -m pip`** (works the same whether you usually type `pip` or `pip3`):

```bash
cd client
python3 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -e .
export PATH="$(pwd)/.venv/bin:$PATH"
astro --help
```

Or activate the venv first, then use `pip` or `pip3` interchangeably:

```bash
source .venv/bin/activate
python -m pip install -e .
# or: pip install -e .
# or: pip3 install -e .
```

## Windows

The CLI install steps are the same idea; only paths and the Python command differ.

**Python:** Install from [python.org](https://www.python.org/downloads/) or the Microsoft Store, and check **“Add python.exe to PATH”** in the installer. You can use `py -3` (launcher) or `python` in a terminal.

**pipx** (PowerShell or Command Prompt, from the `client` folder):

```powershell
cd path\to\astro\client
pipx install --editable .
pipx ensurepath
```

Close and reopen the terminal, then run `astro`.

**venv + pip** (no pipx):

```powershell
cd path\to\astro\client
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -e .
$env:Path = "$PWD\.venv\Scripts;$env:Path"
astro --help
```

Or activate the venv first:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

If PowerShell blocks activation, run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

**Repo `deploy.sh`:** That script is Bash. On Windows use **Git Bash**, **WSL**, or run the same steps by hand: `docker compose up -d --build` from the repo root, then install the CLI with pipx or venv as above.

## Install from a git checkout (subdirectory)

If the repo layout keeps the package under `client/`:

```bash
pipx install --editable "git+https://example.com/your/astro.git#subdirectory=client"
# or with pip in a venv:
python3 -m venv .venv
.venv/bin/python -m pip install "git+https://example.com/your/astro.git#subdirectory=client"
```

Replace the URL with your repository.

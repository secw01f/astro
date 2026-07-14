# ASTRO

**A**gentic **S**ecurity **T**eam for **R**esourceful **O**ptimization
```
      ___           ___           ___           ___           ___     
     /\  \         /\  \         /\  \         /\  \         /\  \    
    /::\  \       /::\  \        \:\  \       /::\  \       /::\  \   
   /:/\:\  \     /:/\ \  \        \:\  \     /:/\:\  \     /:/\:\  \  
  /::\~\:\  \   _\:\~\ \  \       /::\  \   /::\~\:\  \   /:/  \:\  \ 
 /:/\:\ \:\__\ /\ \:\ \ \__\     /:/\:\__\ /:/\:\ \:\__\ /:/__/ \:\__\
 \/__\:\/:/  / \:\ \:\ \/__/    /:/  \/__/ \/_|::\/:/  / \:\  \ /:/  /
      \::/  /   \:\ \:\__\     /:/  /         |:|::/  /   \:\  /:/  / 
      /:/  /     \:\/:/  /     \/__/          |:|\/__/     \:\/:/  /  
     /:/  /       \::/  /                     |:|  |        \::/  /   
     \/__/         \/__/                       \|__|         \/__/    

______________________________________________________________________

```

---

> **ASTRO turns AI agents into an extension of the security engineer.**

Most AI in security stops at analyzing output.  
ASTRO goes further—agents **use memory, documentation, and real tools** to execute workflows the way engineers actually work.

---

## What ASTRO Does

ASTRO is an **agentic execution layer for security workflows**.

It enables agents to:

- **Build context** from prior findings (memory)
- **Apply knowledge** from documentation and past analysis
- **Execute real tools** via MCP/API abstractions
- **Iterate like an engineer** through investigation loops

> This isn’t just AI summarizing results—  
> **it’s AI doing security work.**

---

## The Core Idea

Security work is a loop:

1. **Recall context** (What have I seen before?)
2. **Research & reason** (What does this mean?)
3. **Execute tools** (Validate, explore, exploit)

ASTRO replicates this loop.

---

## Why ASTRO is Different

Most systems:
- Ingest scan results
- Summarize findings
- Generate reports

ASTRO:
- **operates tools**
- **chains workflows**
- **maintains context across runs**

> **Agents don’t just read output—they work the problem.**

---

## Architecture

```mermaid
flowchart LR
    subgraph client["Your machine"]
        CLI["astro CLI"]
    end

    subgraph compose["Docker Compose"]
        API["FastAPI :8000\n(ASTRO API)"]
        DB["PostgreSQL\n+ pgvector"]
        Tools["Tools service\n:7001"]
    end

    CLI -->|HTTP| API
    API -->|SQL| DB
    API -->|tool calls| Tools
```

**Data flow:** CLI talks to the API over HTTP. The API persists state in PostgreSQL (with pgvector) and runs agent tool calls against the tools service.

### Components

| Component | Role |
|-----------|------|
| **api** | Agent orchestration, workflow execution, LLM coordination, DB migrations |
| **db** | Persistent memory + vector context (pgvector) |
| **tools** | MCP/API-exposed tooling for agent execution |
| **redis** | Message broker/result backend for Celery |
| **celery** | Background worker that executes scheduled stack runs |
| **celery-beat** | Scheduler that dispatches due stack schedules |
| **cli** | Local interface to run workflows and interact with agents |

---

## How It Works

1. Tools are exposed via **MCP or API interfaces**
2. Agents can invoke them like **functions**
3. Memory + documentation provide **context**
4. Workflows emerge as **execution loops**, not scripts

> ASTRO separates **how tools are used** from **where they run**  
> while keeping execution grounded in real environments.

---

## Custom toolsets

The bundled `tools/` service ships with the core stack. To publish and host your own tool namespaces outside that deployment, start from the **[astro-toolset-template](https://github.com/secw01f/astro-toolset-template)** repository.

The template follows the same layout as ASTRO’s `tools/` package:

| Path | Description |
|------|-------------|
| `tools/api.py` | FastAPI app, JWT middleware, router registration |
| `tools/src/<namespace>/` | One package per namespace (e.g. `dns`, `web`) |
| `tools/src/<namespace>/tools.py` | Tool definitions and registry |
| `tools/src/<namespace>/__init__.py` | `APIRouter` with `GET /tools` and `POST /exec` |

Each namespace is mounted at `http://<host>:7001/<namespace>` and exposes the same list/exec contract agents expect from the bundled tools service.

**Authentication:** External toolsets use **Bearer JWT** (HS256, signed with `JWT_SECRET` on the tool host). Register the toolset in ASTRO with auth required, auth type **bearer**, and the JWT as the credential token. ASTRO sends `Authorization: Bearer <token>` on tool calls. The bundled `astro/tools` service uses internal HMAC signing instead—do not mix the two models on the same host without understanding the difference.

**Typical workflow:**

1. Copy `tools/src/example/` to a new namespace in the template and define tools with the `@tool(...)` decorator.
2. Wire the router in `tools/api.py` (protected prefix + `include_router`).
3. Run locally or via Docker Compose (default port **7001**).
4. Register the toolset URL in ASTRO (CLI or API), e.g. `http://your-host:7001/<namespace>`.

For JWT issuance, namespace setup, and run instructions, see the [template README](https://github.com/secw01f/astro-toolset-template).

---

## Quick Start (LOCAL DEPLOYMENT)

From the repository root:

```bash
chmod +x deploy.sh
./deploy.sh
```

This will:

1. Create `.env` from `.env.example` if missing, and generate secure values for any
   secrets that aren't set yet (`SECRET_KEY` and `CREDENTIAL_ENCRYPTION_KEY`).
2. Build and start the services:
   - API (runs database migrations on startup)
   - Tools service
   - Database (PostgreSQL + pgvector)
   - Redis, Celery worker, and Celery beat (scheduled runs)
3. Install the CLI via **pipx** or local **venv**

### Secrets

`deploy.sh` generates these automatically, but you can set them yourself in `.env`:

- **`SECRET_KEY`** — signs JWTs. Can be rotated freely.
  ```bash
  python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
  ```
- **`CREDENTIAL_ENCRYPTION_KEY`** — encrypts stored credentials (a Fernet key). Rotating
  it invalidates existing credentials unless you re-encrypt first:
  ```bash
  python3 -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
  # To rotate, from the api container:
  #   python -m src.scripts.reencrypt_credentials --old-key <OLD_KEY>
  ```

---

### After startup

- API → http://localhost:8000  
- CLI → `astro init` then `astro --help`

`./deploy.sh` prints the command for obtaining the credentials for the default `stack` user. Run `astro init` to set the API URL, log in, create your permanent account, and set your password in one flow.

---

## Configuration

### Backend

Copy:

```bash
cp .env.example .env
```

Update values like:

- `DB_URL`
- `DEFAULT_TOOLS_BASE_URL`

---

### Database migrations

The schema is managed with **Alembic** (`api/migrations/`). The `api` container runs
`alembic upgrade head` on startup (see `api/entrypoint.sh`), so migrations are applied
automatically and Celery waits for the API to become healthy before starting.

To add a schema change:

```bash
# 1. Edit the SQLModel models in api/src/db/models.py
# 2. Generate a migration (from the api container)
docker compose exec api alembic revision --autogenerate -m "describe change"
# 3. Review the generated file in api/migrations/versions/, then commit it
```

---

### Upgrading an existing deployment

Instances deployed before this release built their schema directly from the SQLModel
metadata (no `alembic_version` table) and encrypted credentials with a key derived from
`SECRET_KEY`. Two things need attention when upgrading; do both **before** exposing the
new version to traffic, and back up the database first.

**1. Schema.** The baseline migration is a full-schema snapshot with existence guards, so
you do **not** need to `alembic stamp` anything. When the `api` container starts it runs
`alembic upgrade head`, which creates only the objects your database is missing (the new
`stack_schedule*` tables and the `message` uniqueness constraint) and leaves existing
tables untouched.

> If the `message` table already contains duplicate `(stack_id, position)` rows, the
> `uq_message_stack_position` constraint can't be created and the migration will fail.
> De-duplicate those rows first, then restart the `api` container.

**2. Credentials.** Stored credentials were previously encrypted with a key derived from
`SECRET_KEY`; they must be re-encrypted with the new `CREDENTIAL_ENCRYPTION_KEY` or they
will fail to decrypt. Derive the legacy key from your existing `SECRET_KEY`, then run the
re-encryption script (idempotent, safe to re-run):

```bash
# Derive the old key from the SECRET_KEY the credentials were encrypted with
# (run in the container so it reads the same SECRET_KEY from .env):
OLD_KEY=$(docker compose exec -T api python -c 'import base64, os; s = os.environ["SECRET_KEY"].encode(); print(base64.urlsafe_b64encode(s[:32].ljust(32, b"0")).decode())')

# Re-encrypt every credential to CREDENTIAL_ENCRYPTION_KEY (the new-key default):
docker compose exec api python -m src.scripts.reencrypt_credentials --old-key "$OLD_KEY"
```

Set `CREDENTIAL_ENCRYPTION_KEY` in `.env` to a stable value before upgrading (`deploy.sh`
generates one if it's empty — pin it so it doesn't change on the next deploy).

---

### CLI

Interactive setup (recommended on first install):

```bash
astro init
```

Non-interactive (URL only):

```bash
astro init --url http://localhost:8000 --skip-login -y
```

View or change settings later:

```bash
astro config show
astro config url http://localhost:8000
```

Environment variables override the config file:

- `ASTRO_API_URL`
- `ASTRO_API_TOKEN`

---

## CLI Overview

| Area | Examples |
|------|----------|
| Setup | `astro init` |
| Config | `astro config show`, `astro config url` |
| Auth | `astro auth login` |
| Agents | `astro agent list` |
| Tools | `astro tool list` |
| LLMs | `astro llm list` |
| Stacks | `astro stacks list`, `astro stacks exec` |
| Scheduled runs | `astro stacks schedule create`, `astro stacks schedule runs`, `astro stacks schedule run` |
| Docs | `astro docs` |

![cli-screenshot](img/astro-screenshot.png)

---

## Project Layout

| Path | Description |
|------|-------------|
| `api/` | Core backend, orchestration, agent logic |
| `client/` | CLI interface (`astro`) |
| `tools/` | Tool execution service |
| `docker-compose.yaml` | Runtime services |

---

## Use Cases

- Vulnerability triage and prioritization
- Offensive security workflows (recon → validation → exploitation)
- Detection and response investigations
- Security automation with real tool execution

---

## Philosophy

ASTRO is built on a simple belief:

> **AI should not replace security engineers.  
> It should extend how they already work.**

---

## License

MIT — see [LICENSE](LICENSE)

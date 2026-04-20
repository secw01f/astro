# ASTRO

**A**gentic **S**ecurity **T**eam for **R**esourceful **O**ptimization

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

```
  ┌──────────────────┐          HTTP           ┌─────────────────────────────────────────┐
  │  astro CLI       │  ───────────────────►   │  FastAPI  :8000                         │
  │  (your machine)  │                         │  (ASTRO API — Docker Compose)           │
  └──────────────────┘                         │       │                    │            │
                                               │       │ SQL                │ tool calls │
                                               │       ▼                    ▼            │
                                               │  PostgreSQL            Tools service    │
                                               │  + pgvector            :7001            │
                                               └─────────────────────────────────────────┘
```

**Data flow:** CLI talks to the API over HTTP. The API persists state in PostgreSQL (with pgvector) and runs agent tool calls against the tools service.

### Components

| Component | Role |
|-----------|------|
| **api** | Agent orchestration, workflow execution, LLM coordination |
| **db** | Persistent memory + vector context (pgvector) |
| **tools** | MCP/API-exposed tooling for agent execution |
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

## Quick Start

From the repository root:

```bash
chmod +x deploy.sh
./deploy.sh
```

This will:

1. Build and start:
   - API
   - Tools service
   - Database
2. Install the CLI via **pipx** or local **venv**

---

### After startup

- API → http://localhost:8000  
- CLI → `astro --help`

> On first run, default credentials are generated—check API logs.

---

## Configuration

### Backend

Copy:

```bash
cp .env.example .env
```

Update values like:

- `DB_URL`
- `SECRET_KEY`
- `DEFAULT_TOOLS_BASE_URL`

---

### CLI

```bash
astro config
```

Or use environment variables:

- `ASTRO_API_URL`
- `ASTRO_API_TOKEN`

---

## CLI Overview

| Area | Examples |
|------|----------|
| Config | `astro config url` |
| Auth | `astro auth login` |
| Agents | `astro agent list` |
| Tools | `astro tool list` |
| LLMs | `astro llm list` |
| Docs | `astro docs` |

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

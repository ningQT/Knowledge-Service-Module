<div align="center">

# KSM — Knowledge Service Module

**Local-first knowledge infrastructure for AI systems, built on Obsidian Vault standard.**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green.svg)](https://fastapi.tiangolo.com/)
[![React 19](https://img.shields.io/badge/React-19-61DAFB.svg)](https://react.dev/)

[English](README.md) | [中文](README.zh-CN.md)

</div>

---

## What is KSM?

KSM is a local-first knowledge service module for AI business systems. It uses Obsidian Vault as the underlying knowledge carrier, processing raw materials into traceable, searchable, and organized structured knowledge nodes through standard directories, frontmatter metadata, Wikilinks, and SQLite indexing.

### Core Capabilities

| Capability | Description |
|------------|-------------|
| **Instance Management** | Create and manage isolated knowledge base instances with standard vault directory structure |
| **Knowledge Writing** | Process Markdown documents into source notes, knowledge cards, and knowledge maps |
| **Async Ingestion** | SSE-powered 8-step pipeline with real-time progress tracking |
| **Relationship Organization** | Parse and index knowledge relationships (source_trace, extracted_from, concept_overlap, etc.) |
| **Structured Search** | Intent-aware search returning core_hits, related_cards, source_notes, and maps |
| **Knowledge Graph** | Interactive visualization with React Flow, supporting 3-layer filtering |
| **Web Console** | Browser-based UI with Dashboard, Graph View, Ingest, Search, Note Detail, and Settings |
| **Local-First** | All data stored locally in filesystem and SQLite — easy to debug, migrate, and review |

### Tech Stack

| Layer | Technologies |
|-------|-------------|
| **Backend** | Python 3.11+ / FastAPI / SQLite (FTS5) / Local filesystem |
| **Frontend** | React 19 / TypeScript / Vite / Tailwind CSS / shadcn/ui / Zustand / React Flow |

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- An LLM API key (OpenAI, Anthropic, or compatible)

### 1. Clone & Setup Backend

```bash
git clone https://github.com/yourname/ksm.git
cd ksm

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Start Backend

```bash
uvicorn app.api.app:create_app --factory --host 127.0.0.1 --port 8900
```

### 3. Configure LLM

Open http://127.0.0.1:8900/settings in the Web console and configure your LLM provider (API key, model, endpoint).

### 4. Start Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 in your browser.

---

## Docker Deployment

```bash
docker compose up -d --build
```

See [docs/production-deployment.md](docs/production-deployment.md) for production configuration, backup, and rollback procedures.

---

## API Overview

| Category | Endpoints |
|----------|-----------|
| **Instances** | `POST/GET /api/v1/instances` |
| **Ingestion** | `POST /api/v1/instances/{id}/ingest[/async]` |
| **Search** | `POST /api/v1/search` |
| **Graph** | `GET /api/v1/instances/{id}/graph` |
| **Settings** | `GET/PUT /api/v1/settings/llm` |

Interactive docs (when running): http://127.0.0.1:8900/docs

---

## Web Console

| Page | Path | Description |
|------|------|-------------|
| Dashboard | `/` | Instance list with statistics |
| Graph View | `/graph` | Knowledge graph visualization |
| Ingest | `/ingest` | Document upload with SSE progress |
| Search | `/search` | Structured knowledge search |
| Note Detail | `/note/:path` | Markdown rendering with metadata |
| Settings | `/settings` | LLM configuration management |

Supports light/dark theme.

---

## Configuration

LLM settings are managed via the Web console at `/settings` and stored in the database.

Key environment variables:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `KSM_DATA_DIR` | No | `./data/vaults` | Data storage directory |
| `KSM_PORT` | No | `8900` | HTTP port |
| `KSM_ENABLE_DOCS` | No | `true` | Enable `/docs` endpoint |

See [docs/production-deployment.md](docs/production-deployment.md) for the complete list.

---

## Testing

```bash
# All tests
python -m pytest -q

# Unit tests only
pytest tests/unit/ -v

# Integration tests
pytest tests/integration/ -v

# With coverage
pytest tests/ --cov=app --cov-report=term-missing
```

---

## Project Structure

```
ksm/
├── app/                    # Python backend
│   ├── api/                # FastAPI routes & dependencies
│   ├── core/               # Business services
│   ├── llm/                # LLM client & prompts
│   ├── pipeline/           # Search pipeline
│   ├── storage/            # SQLite + FTS5
│   └── template/           # Vault templates
├── frontend/               # React frontend
│   └── src/
│       ├── components/     # UI components
│       ├── pages/          # Page components
│       ├── services/       # API calls
│       └── stores/         # Zustand state
├── configs/                # Strategy configs
├── templates/              # Vault templates
└── tests/                  # Test suite
```

---

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.

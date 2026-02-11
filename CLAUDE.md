# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Resophy is an open-source paper reading and management platform built with Flask + vanilla HTML/JS/CSS. It provides AI-powered paper translation, interpretation, daily arXiv recommendations, and Zotero import. The project is transitioning from a single-user file-based system to a multi-user Docker-deployed architecture with MySQL.

## Commands

```bash
# Install dependencies (uv required)
uv venv && source .venv/bin/activate
uv pip install -e ".[local]"          # local end only (no AI server deps)
uv pip install -e ".[server]"         # with MinerU/vLLM AI server deps

# Run the application
python app.py --papers-dir ./papers --host 0.0.0.0 --port 7191
python app.py --debug                 # with debug mode

# Docker (connects to 1panel-network with existing MySQL/Redis/Flarum)
docker compose up --build
docker compose up -d                  # detached

# Database (MySQL 8.4 via 1panel Docker)
# Init schema: deploy/init.sql against the `resophy` database
# Flarum users table: flarum_users in flarum DB (bcrypt $2y$ passwords)
```

No test suite exists yet.

## Architecture

### Data Flow (Current - Single User, File-Based)

```
app.py (Flask entry)
  ├── init_app()          → sets up UPLOAD_FOLDER, config JSON files, SearchIndex
  ├── register_routes()   → wires all route modules with dependencies via closures
  └── __main__            → parse args, init, register, rebuild search index, run
```

Each route module follows the **dependency injection pattern**: `register_*_routes(app, *, dep1=..., dep2=...)` receives all dependencies as keyword arguments. Routes never import globals directly; they capture injected callables via closures.

### Data Flow (In Progress - Multi-User, MySQL)

```
resophy/config.py   → loads env vars (DB_HOST, FLARUM_*, SECRET_KEY, etc.)
resophy/db.py       → MySQL connection pools (Resophy DB + Flarum DB read-only)
deploy/init.sql     → schema: papers, user_papers, user_categories, user_settings, ...
```

The multi-user design splits data into a **shared layer** (papers table with PDF dedup by content_hash, shared AI analysis results) and a **per-user layer** (user_papers for notes/categories/starred, user_settings, user_reading_history).

### Core Module (`resophy/core/`)

- **`Paper`** (dataclass in `base_paper.py`): ~40-field model with `from_dict`/`to_dict` serialization, status tracking for translation/analysis tasks, and read-time accumulation. All field normalization happens in `_normalize_fields()`.
- **`PaperStore`** (singleton in `paper_store.py`): Thread-safe in-memory registry with dual indexing by `paper_id` and `category_id`. Uses `RLock` for concurrency. Merges filesystem-loaded data with cached state, preserving in-flight task statuses.
- **`SearchIndex`** (`search_index.py`): SQLite FTS5 full-text search with WAL mode. Handles Chinese via LIKE fallback (FTS5 doesn't support CJK well). Self-repairs corrupted FTS5 indexes automatically.

### Route Registration Pattern

All route modules in `resophy/routes/` use this pattern:
```python
def register_*_routes(app: Flask, *, get_categories, save_paper_metadata, ...):
    @app.route("/api/...")
    def api_something():
        # uses injected deps via closure
```

Dependencies are `functools.partial`-bound in `app.py` after `init_app()` sets directory paths.

### Paper Storage (Current)

Papers are stored as **PDF + sibling JSON** pairs in category subdirectories under `papers/`:
```
papers/
  categories.json              # tree structure
  Research/
    Topic A/
      paper_name.pdf           # original PDF
      paper_name.json          # Paper metadata (same fields as Paper dataclass)
      paper_name.zh.dual.pdf   # AI translation output
      outputs/
        paper_name/vlm/result.md  # AI interpretation output
```

### AI Task Execution

Translation and analysis run as **background threads** managed by `threading.Lock`-protected task dictionaries in `app.py`. Task functions are in `resophy/tools/agent_tools/`. They invoke external processes (BabelDOC for translation, MinerU CLI for PDF-to-MD, then OpenAI-compatible LLM for interpretation).

### Key Integration Points

- **Flarum Auth** (in progress): Users authenticate via Flarum REST API (`POST /api/token`) or direct MySQL bcrypt verification. Flarum runs on MySQL 8.4 in the same Docker network (`1panel-network`).
- **MinerU**: PDF parsing via local CLI (`magic-pdf`) or cloud API (`resophy/tools/basic_tools/mineru_api_client.py`).
- **LLM**: OpenAI-compatible API (configurable base_url/model/key in agentic settings).
- **arXiv**: Daily paper fetching with LLM-powered categorization via `resophy/tools/basic_tools/daily_arxiv.py`.

## Conventions

- Route modules use `Protocol` classes to type-hint injected callable dependencies.
- All `from __future__ import annotations` for deferred type evaluation.
- Paper metadata serialization always goes through `Paper.from_dict()` / `Paper.to_dict()`.
- Thread-safe access patterns: `RLock` for `PaperStore`, `threading.Lock` for task dicts, `threading.RLock` for `SearchIndex`.
- Config files (JSON) live alongside papers in `UPLOAD_FOLDER` (papers directory).
- The `paper_store` singleton is imported directly: `from resophy.core.paper_store import paper_store`.

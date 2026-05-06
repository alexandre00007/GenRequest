# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run development server
python manage.py runserver

# Database migrations
python manage.py makemigrations
python manage.py migrate

# Run all tests
python manage.py test generator

# Run a single test
python manage.py test generator.tests.ExecuteQueryTest.test_all_authors

# Create a superuser for /admin
python manage.py createsuperuser
```

## Environment

Copy `.env.example` to `.env` and set values before running. The app reads `SECRET_KEY`, `DEBUG`, and `ALLOWED_HOSTS` from environment variables; defaults are development-only. Ollama must be running locally with `llama3.1:8b` pulled — the model name is set via `OLLAMA_MODEL` in [generator/views.py](generator/views.py).

The project runs on **Python 3.8**. Do not use `list[str]` / `dict[str, int]` generic syntax in type hints — use `from typing import List, Dict` or leave annotations unparameterised.

## Architecture

**GenRequest** is a single-page Django app that translates natural language (French) into Django ORM queries using a local LLM via Ollama, then executes those queries live against the running database.

### Request flow

1. User submits a French description in the browser form
2. `stream_query_generation` (POST `/stream-generation/`) calls `generate_project_schema_context()` to auto-inspect all live Django models, builds a system prompt with that schema context, then streams the LLM response back as SSE (`text/event-stream`)
3. The generated ORM code is displayed with Prism.js syntax highlighting
4. User clicks "Execute" → `execute_generated_query` (POST `/execute-query/`) preprocesses the code (strips imports, prints, comments), runs it via `eval()`/`exec()`, then serialises the result into columns/rows
5. Results are rendered as an HTML table

### Key files

- [generator/generator/executor.py](generator/generator/executor.py) — `generate_project_schema_context()` introspects all non-Django-internal models at runtime via `apps.get_models()`. Result is `@lru_cache`d for the lifetime of the process — cache is not invalidated by migrations applied after startup.
- [generator/views.py](generator/views.py) — all three views plus `_preprocess()` (strips import/print/comment lines from generated code) and `_extract_result()` (handles QuerySet, int, dict, list-of-dicts, list-of-tuples).
- [generator/models.py](generator/models.py) — `DatabaseSchema` (not wired to the current UI, reserved for future multi-schema support), `QueryHistory` (every generation persisted), `Author`/`Book` (demo models for testing queries).

### Security model for `execute_generated_query`

AI-generated code is run via `eval()`/`exec()`. Three layers:
1. **String blocklist** (`_BLOCKED_PATTERNS`) — rejects the request before execution if dangerous tokens appear (`__import__`, `os.`, `subprocess`, etc.).
2. **Restricted `__builtins__`** — replaced with a minimal whitelist; `__import__` and all I/O are unavailable at eval time.
3. **Pre-injected ORM context** (`_ORM_CONTEXT`) — common helpers (`Q`, `F`, `Count`, `Avg`, etc.) are injected directly so the LLM doesn't need import statements, which would fail under the restricted builtins.

### Frontend

Single template at [generator/templates/generator/index.html](generator/templates/generator/index.html). No JS framework — uses the Fetch API with `ReadableStream` for SSE parsing. Styling via water.css CDN.

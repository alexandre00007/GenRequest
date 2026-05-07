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

**GenRequest** is a Django app that translates natural language (French) into Django ORM queries using a local LLM via Ollama, executes those queries live against the database, then lets the user chat about the results in a persistent multi-turn conversation.

### Request flow

1. User submits a French description → `stream_query_generation` (POST `/stream-generation/`) builds a system prompt with the live schema context and streams LLM output back as SSE
2. Generated code is displayed with Prism.js syntax highlighting
3. User clicks Execute → `execute_generated_query` (POST `/execute-query/`) preprocesses and runs the code, returns columns/rows as JSON
4. Results appear in a table; the chat zone unlocks
5. User chats via `chat_with_data` (POST `/chat/`) — each message carries the full conversation history and all previously executed result sets as context; the LLM can suggest new ORM queries inline
6. New code blocks in chat responses have their own Execute button; running them appends results to the shared data context for all future turns

### Key files

- [generator/generator/executor.py](generator/generator/executor.py) — `generate_project_schema_context(selected_models=None)` introspects all non-Django-internal models. Accepts an optional tuple of model names to filter the context. Dict-cached per unique filter key; restart after migrations to clear. Also exports `get_all_project_models()` for the model-picker API.
- [generator/views.py](generator/views.py) — all views plus the pipeline helpers described below.
- [generator/models.py](generator/models.py) — `DatabaseSchema` (wired to schema selector in UI via `models_filter` field), `QueryHistory` (every generation persisted with timing), `ChatSession`/`ChatMessage` (persistent chat sessions), `Author`/`Book` (demo models with verbose names and help_text).

### Code execution pipeline (`execute_generated_query`)

Generated code goes through several transforms before `exec()`/`eval()`:

1. **`_preprocess(code)`** — strips import, print, comment, and markdown fence lines while preserving indentation (required for `for`/`if` blocks).
2. **`models.` normalisation** — `re.sub(r'\bmodels?\.', '', code)` silently rewrites `models.Author` → `Author` to recover from a common LLM hallucination.
3. **`_find_result_expr(code)`** — uses `ast.parse` to find what to `eval` after `exec`. Last bare expression → eval it directly (handles multi-line chained calls). Last assignment → eval the variable name. Control-flow block last → walk back to the last assignment.
4. **`exec()` + `eval()`** — run in a restricted context: `_SAFE_BUILTINS` whitelist, `_ORM_CONTEXT` pre-injected (no `__import__` needed).
5. **`_extract_result(queryset)`** — materialises the queryset with `list()` first, then branches on item type: `dict` (ValuesQuerySet), `tuple` (ValuesListQuerySet), or model instance (regular QuerySet).

### Execution context

Everything listed below is pre-injected — generated code must never import anything:

- **Models** — all non-internal app models by class name (`Author`, `Book`, etc.)
- **ORM helpers** — `Q`, `F`, `Count`, `Sum`, `Avg`, `Max`, `Min`, `Value`, `Case`, `When`, `Subquery`, `OuterRef`, `Coalesce`, `Concat`, `Length`, `Lower`, `Upper`
- **Python stdlib** — `chain`, `groupby`, `combinations`, `defaultdict`, `Counter`, `sorted`, `reversed`, `zip`, `map`, `filter`, `min`, `max`, `sum`, `any`, `all`, `isinstance`

### Security model

1. **String blocklist** (`_BLOCKED_PATTERNS`) — rejects before execution if dangerous tokens appear (`__import__`, `os.`, `subprocess`, `eval(`, etc.).
2. **Restricted `__builtins__`** (`_SAFE_BUILTINS`) — whitelist only; no I/O, no `__import__`.
3. **Model-name validation** — request rejected if no known model name appears in the query.

### Chat (`chat_with_data`)

Uses `ollama.chat()` (multi-turn messages array) instead of `ollama.generate()`. Each request sends the last 10 conversation turns and up to 5 most recent result sets (capped at 50 rows each) as context. The LLM is instructed to wrap any new ORM code in ` ```python ``` ` blocks; the frontend parses those after the stream ends and attaches Execute buttons.

### Frontend

Single template at [generator/templates/generator/index.html](generator/templates/generator/index.html). No JS framework. Custom dark design system (CSS custom properties, Inter + JetBrains Mono, no external CSS framework). Key client-side state:

- `state.history` — `[{role, content}]` sent to `/chat/` on every message (last 10 turns)
- `state.dataContext` — `[{query, columns, rows}]` accumulated from every execution
- `state.selectedModels` — `[]` means all models; non-empty array filters scope for generation, schema context, and chat
- `state.sessionId` / `state.sessionName` — tracks the active persistent session

Enter in the chat textarea sends without Shift. Prism.js re-highlights code blocks after each streamed assistant message is finalised.

### New features (2026-05-07)

**Model picker** — Collapsible chip bar above the generation form. Fetches all non-internal models from `GET /api/models/`. Selecting chips narrows the LLM's schema context and the generation prompt to only those models. All chips selected = no filter (passes empty string to backend).

**Multi-schema / project support** — `DatabaseSchema` now has a `models_filter` TextField (comma-separated model names). When a schema is selected from the dropdown, its filter is applied to the model picker automatically. Schemas are created via `/admin`.

**Export CSV** — Client-side (no server round-trip). "⬇ Export CSV" button appears on the main result table and on every inline result bubble in chat. Downloads a UTF-8 BOM CSV.

**Persistent chat sessions** — Sessions panel in the sidebar. Saving writes `ChatSession` + `ChatMessage` rows to the DB, including the full conversation history, all data contexts, and selected model scope. Loading a session fully restores the UI state. New API endpoints:
- `GET  /api/models/` → list of all project models
- `GET  /sessions/` → list recent sessions
- `POST /sessions/save/` → create or update a session (JSON body)
- `GET  /sessions/<id>/` → load a session
- `POST /sessions/<id>/delete/` → delete a session

**Verbose names + help_text on models** — `Author`, `Book`, and all internal models (`DatabaseSchema`, `QueryHistory`, `ChatSession`, `ChatMessage`) have `verbose_name`, `verbose_name_plural`, `help_text` on their fields. `generate_project_schema_context()` now emits these in the LLM prompt so the model understands business meaning beyond field names.

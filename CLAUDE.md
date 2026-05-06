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

- [generator/generator/executor.py](generator/generator/executor.py) — `generate_project_schema_context()` introspects all non-Django-internal models via `apps.get_models()`. `@lru_cache`d for the process lifetime — restart the server after migrations.
- [generator/views.py](generator/views.py) — all views plus the pipeline helpers described below.
- [generator/models.py](generator/models.py) — `DatabaseSchema` (reserved, not wired to UI), `QueryHistory` (every generation persisted with timing), `Author`/`Book` (demo models).

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

Single template at [generator/templates/generator/index.html](generator/templates/generator/index.html). No JS framework. Key client-side state:

- `state.history` — `[{role, content}]` sent to `/chat/` on every message (last 10 turns)
- `state.dataContext` — `[{query, columns, rows}]` accumulated from every execution

Enter in the chat textarea sends without Shift. Prism.js re-highlights code blocks after each streamed assistant message is finalised.

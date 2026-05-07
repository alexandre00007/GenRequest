# Building a Local AI-Powered Django ORM Studio — From Natural Language to Live Data

> Ask a question in plain French. Get executable Django ORM code. Execute it. Then chat with your data — all running 100% locally, no API keys required.

---

## The Problem

Every Django developer has been there: you need a quick data check — "how many users signed up last week with at least one order?" — and instead of a 10-second answer, you spend five minutes constructing a QuerySet, running the shell, formatting the output. If you're not the one who wrote the models, add another five minutes for `models.py` archaeology.

This project — **GenRequest** — solves that. You describe what you want in natural language, a local LLM generates the ORM code, the app executes it live against your database, and then you can *talk* to the results: ask follow-up questions, request new queries, and build up a shared context the LLM keeps referring to throughout the conversation.

Everything runs locally. The LLM is served by [Ollama](https://ollama.ai). No data leaves your machine.

---

## Stack

- **Django 4.2** — the app itself, SQLite in dev
- **Ollama + llama3.1:8b** — local LLM inference
- **Python 3.8**
- No frontend framework — vanilla JS with the Fetch API

---

## Architecture Overview

The app has three main phases that chain together:

```
Natural language prompt
        ↓
  [LLM via Ollama]       ← streamed SSE response
        ↓
  Generated ORM code
        ↓
  [Execution pipeline]   ← preprocess → normalize → AST → exec/eval
        ↓
  Results (columns + rows)
        ↓
  [Multi-turn chat]      ← ollama.chat() with full context
```

---

## Part 1 — The RAG Layer: Auto-Synced Schema Context

The first clever piece is `generate_project_schema_context()` in `generator/generator/executor.py`. Every time the LLM is called, it receives a live description of every model in the project — fields, types, and foreign key relationships — introspected directly from the running Django app:

```python
from functools import lru_cache
from django.apps import apps
from django.db.models.fields.related import ForeignKey, ManyToManyField

_EXCLUDED_APP_LABELS = {'auth', 'contenttypes', 'sessions', 'admin'}

@lru_cache(maxsize=1)
def generate_project_schema_context() -> str:
    lines = ["Voici la structure exacte et exclusive des modèles Django disponibles :\n"]

    for model in apps.get_models():
        if model._meta.app_label in _EXCLUDED_APP_LABELS:
            continue

        lines.append(f"Modèle: {model.__name__}")
        lines.append("Champs disponibles :")

        for field in model._meta.get_fields():
            if not hasattr(field, 'verbose_name'):
                continue
            field_type = field.get_internal_type()
            if isinstance(field, ForeignKey):
                target = field.remote_field.model.__name__
                lines.append(f"  - {field.name} ({field_type}) -> Clé étrangère vers '{target}'")
            elif isinstance(field, ManyToManyField):
                target = field.remote_field.model.__name__
                lines.append(f"  - {field.name} ({field_type}) -> ManyToMany avec '{target}'")
            else:
                lines.append(f"  - {field.name} ({field_type})")
        lines.append("")

    return "\n".join(lines)
```

The `@lru_cache(maxsize=1)` means this only runs once per process lifetime. The result looks like:

```
Modèle: Author
Champs disponibles :
  - id (AutoField)
  - name (CharField)

Modèle: Book
Champs disponibles :
  - id (AutoField)
  - title (CharField)
  - author (ForeignKey) -> Clé étrangère vers 'Author'
```

This string goes verbatim into the system prompt. The LLM never hallucinates field names that don't exist — because it's only told about fields that *do* exist.

---

## Part 2 — Streaming ORM Generation

Generation uses `ollama.generate()` with `stream=True` and sends chunks as [Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events):

```python
def stream_query_generation(request):
    dynamic_schema_context = generate_project_schema_context()

    model_names = ", ".join(
        m.__name__ for m in apps.get_models()
        if m._meta.app_label not in {'auth', 'contenttypes', 'sessions', 'admin'}
    )

    system_instruction = (
        "Tu es un générateur de code Django ORM. Ton unique rôle est de produire du code Python exécutable.\n"
        f"{dynamic_schema_context}\n"
        "CONTEXTE D'EXÉCUTION — ces noms sont déjà disponibles, n'importe rien :\n"
        f"- Modèles : {model_names}\n"
        "- Helpers ORM : Q, F, Count, Sum, Avg, Max, Min, Value, Case, When, Subquery, OuterRef, Coalesce\n"
        "- Python : chain, groupby, combinations, defaultdict, Counter, sorted, zip, map, filter, any, all\n\n"
        "RÈGLES ABSOLUES :\n"
        "1. Renvoie UNIQUEMENT du code Python exécutable. Aucune phrase, aucune explication.\n"
        "2. Interdit : commentaires, imports, print(), markdown (```), texte en langage naturel.\n"
        "3. Référence les modèles directement par leur nom. Jamais model.Author ou models.Author.\n"
        "4. Relations ForeignKey : syntaxe double underscore (ex: author__name).\n"
        "5. La dernière ligne doit être l'expression finale à évaluer."
    )

    def event_stream():
        start_time = time.time()
        full_response = ""
        response_stream = ollama.generate(
            model='llama3.1:8b',
            prompt=f"{system_instruction}\n\nDemande utilisateur : {user_prompt}",
            stream=True,
        )
        for chunk in response_stream:
            text_chunk = chunk['response']
            full_response += text_chunk
            yield f"data: {json.dumps({'text': text_chunk})}\n\n"

        duration = round(time.time() - start_time, 2)
        QueryHistory.objects.create(
            prompt_utilisateur=user_prompt,
            requete_generee=full_response.strip(),
            query_type=query_type,
            execution_time=duration,
        )
        yield f"data: {json.dumps({'status': 'DONE', 'duration': duration})}\n\n"

    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'  # disable Nginx buffering
    return response
```

The frontend reads this stream with the Fetch API's `ReadableStream`:

```javascript
const resp = await fetch("/stream-generation/", { method: 'POST', body: formData });
const reader = resp.body.getReader();
const dec = new TextDecoder('utf-8');
let buf = '';

while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const lines = buf.split('\n\n');
    buf = lines.pop();
    for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const data = JSON.parse(line.slice(6));
        if (data.text) {
            outputCode.textContent += data.text;
            Prism.highlightElement(outputCode); // syntax highlight as it streams
        }
        if (data.status === 'DONE') {
            metricsDiv.textContent = `Généré en ${data.duration}s via LLM local.`;
        }
    }
}
```

The code appears token by token with live syntax highlighting. It feels fast even on a CPU-only machine because the user sees progress immediately.

---

## Part 3 — The Execution Pipeline

This is the most technically interesting part. We can't just `eval()` whatever the LLM returns — it generates imports (which require `__import__`), print statements, markdown fences, comments, and sometimes hallucinates `models.Author` instead of `Author`. We need a hardened pipeline.

### Step 1: Preprocessing

```python
_IMPORT_RE = re.compile(r'^\s*(import |from \S+ import )')
_PRINT_RE  = re.compile(r'^\s*print\s*\(')
_COMMENT_RE = re.compile(r'^\s*#')
_FENCE_RE  = re.compile(r'^\s*```')

def _preprocess(code: str) -> list:
    result = []
    for line in code.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if (_IMPORT_RE.match(stripped) or _PRINT_RE.match(stripped)
                or _COMMENT_RE.match(stripped) or _FENCE_RE.match(stripped)):
            continue
        result.append(line.rstrip())  # preserve leading whitespace for for/if blocks
    return result
```

Critical detail: we strip *content* but preserve *indentation*. An early version used `line.strip()` and completely broke `for` loops — their bodies lost their indent and Python raised `expected an indented block`.

### Step 2: Normalize LLM Hallucinations

```python
preprocessed = re.sub(r'\bmodels?\.', '', preprocessed)
```

One line. `\b` ensures `some_models.whatever` is untouched. This silently fixes `models.Author` → `Author` without stopping the user with an error.

### Step 3: Find the Result Expression with the AST

Naive approaches — "take the last line", "split on assignments" — break on multi-line chained queries like:

```python
Author.objects.annotate(
    nb_books=Count('book')
).values('name', 'nb_books')
```

The solution is to use Python's `ast` module:

```python
def _find_result_expr(code: str) -> str:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    if not tree.body:
        return None

    src_lines = code.splitlines()
    last = tree.body[-1]

    if isinstance(last, ast.Expr):
        # Multi-line expression: slice the exact source lines
        chunk = src_lines[last.lineno - 1:last.end_lineno]
        indent = len(chunk[0]) - len(chunk[0].lstrip())
        return '\n'.join(l[indent:] for l in chunk)

    # Walk back for the last assignment (handles for-loop patterns)
    for stmt in reversed(tree.body):
        if isinstance(stmt, ast.Assign) and isinstance(stmt.targets[-1], ast.Name):
            return stmt.targets[-1].id

    return None
```

This correctly handles three patterns:

| Generated code | Result expression |
|---|---|
| `Author.objects.all()` | `Author.objects.all()` |
| `result = Author.objects.annotate(…)` | `result` |
| `books = []; for a in Author…; books` | `books` (last assignment) |

### Step 4: Secure exec() + eval()

```python
_ORM_CONTEXT = {
    'Q': Q, 'F': F, 'Count': Count, 'Sum': Sum, 'Avg': Avg,
    'Max': Max, 'Min': Min, 'Value': Value, 'Subquery': Subquery,
    'OuterRef': OuterRef, 'Case': Case, 'When': When,
    # stdlib — no import needed
    'chain': chain, 'groupby': groupby, 'Counter': Counter, 'defaultdict': defaultdict,
    # ... etc
}

_SAFE_BUILTINS = {
    'str': str, 'int': int, 'list': list, 'dict': dict, 'set': set,
    'len': len, 'sorted': sorted, 'zip': zip, 'map': map, 'filter': filter,
    'min': min, 'max': max, 'sum': sum, 'any': any, 'all': all,
    'isinstance': isinstance, 'getattr': getattr,
    # notably absent: __import__, open, eval, exec, compile
}

context_globals = {model.__name__: model for model in apps.get_models()}
context_globals.update(_ORM_CONTEXT)
context_globals['__builtins__'] = _SAFE_BUILTINS

exec(preprocessed, context_globals)
queryset = eval(result_expr, context_globals)
```

Three security layers:
1. **String blocklist** — reject before exec if `__import__`, `os.`, `subprocess`, `eval(` etc. are present
2. **Restricted `__builtins__`** — no I/O, no import, no introspection escape hatches
3. **Model-name validation** — reject if no known model class name appears in the query

### Step 5: Adaptive Result Extraction

A `ValuesQuerySet` (from `.values()`) has `hasattr(qs, 'model') == True` — but iterating it yields `dict` objects, not model instances. The old code assumed `.model` always meant instances and called `getattr(dict_obj, 'id')`, raising `KeyError: 'id'`.

The fix: materialise with `list()` first, then branch on what you actually got:

```python
def _extract_result(queryset):
    if hasattr(queryset, 'model'):
        items = list(queryset)
        if not items:
            return [f.name for f in queryset.model._meta.fields], []

        first = items[0]

        if isinstance(first, dict):            # .values()
            cols = list(first.keys())
            return cols, [[str(item.get(k, '')) for k in cols] for item in items]

        if isinstance(first, (list, tuple)):   # .values_list()
            cols = [f'col_{i+1}' for i in range(len(first))]
            return cols, [[str(v) for v in row] for row in items]

        # regular model instances
        columns = [f.name for f in queryset.model._meta.fields]
        rows = []
        for obj in items:
            row = []
            for field in columns:
                val = getattr(obj, field)
                if hasattr(val, 'pk'):
                    val = f"{val.__class__.__name__} (ID: {val.pk})"
                row.append(str(val) if val is not None else "")
            rows.append(row)
        return columns, rows

    if isinstance(queryset, int):
        return ['Résultat / Compte'], [[str(queryset)]]

    if isinstance(queryset, dict):
        cols = list(queryset.keys())
        return cols, [[str(queryset[k]) for k in cols]]

    if isinstance(queryset, (list, tuple)) and queryset:
        first = queryset[0]
        if isinstance(first, dict):
            cols = list(first.keys())
            return cols, [[str(item.get(k, '')) for k in cols] for item in queryset]
        if isinstance(first, (list, tuple)):
            cols = [f'col_{i+1}' for i in range(len(first))]
            return cols, [[str(v) for v in row] for row in queryset]

    return ['Données'], [[str(queryset)]]
```

---

## Part 4 — The Chat Layer

After the first execution the UI unlocks a chat zone. Every message is sent to `chat_with_data`, which uses `ollama.chat()` — the multi-turn API that accepts a messages array:

```python
def chat_with_data(request):
    history = json.loads(request.POST.get("history", "[]"))
    data_context = json.loads(request.POST.get("data_context", "[]"))

    schema_context = generate_project_schema_context()

    # Format executed results as plain tables for the LLM
    data_sections = []
    for i, ctx in enumerate(data_context[-5:]):  # cap at 5 most recent result sets
        label = ctx.get("query", f"Résultat {i + 1}")
        header = " | ".join(ctx["columns"])
        rows_str = "\n".join(" | ".join(row) for row in ctx["rows"][:50])
        data_sections.append(f"[{label}]\n{header}\n{'-' * len(header)}\n{rows_str}")

    system_content = (
        "Tu es un assistant expert Django ORM et analyse de données.\n\n"
        f"SCHÉMA DES MODÈLES :\n{schema_context}\n\n"
        f"DONNÉES DISPONIBLES :\n{chr(10).join(data_sections)}\n\n"
        "RÈGLES :\n"
        "- Réponds en français, de façon concise et précise.\n"
        "- Appuie-toi sur les données disponibles.\n"
        "- Si tu proposes du code Django ORM, entoure-le de ```python ... ```.\n"
        "- Si une question nécessite des données absentes, propose une requête ORM."
    )

    messages = [{"role": "system", "content": system_content}]
    for msg in history[-10:]:   # cap at 10 turns to control context size
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": message})

    def event_stream():
        stream = ollama.chat(model='llama3.1:8b', messages=messages, stream=True)
        for chunk in stream:
            yield f"data: {json.dumps({'text': chunk['message']['content']})}\n\n"
        yield f"data: {json.dumps({'status': 'DONE'})}\n\n"

    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    return response
```

Key design choices:
- **Last 5 result sets, 50 rows each** — keeps the context window from exploding on large datasets
- **Last 10 conversation turns** — enough for coherent follow-ups without ballooning the prompt
- **`ollama.chat()` instead of `ollama.generate()`** — the messages array keeps conversation state server-side; the client just appends new turns

### Inline Code Blocks in Chat

When the LLM suggests a new query in chat, the response contains a ` ```python ``` ` block. The frontend parses these *after* the stream ends and attaches an Execute button:

```javascript
function renderAssistantContent(text) {
    const root = document.createElement('div');
    const parts = text.split(/(```python[\s\S]*?```)/g);

    parts.forEach(part => {
        if (part.startsWith('```python')) {
            const code = part.replace(/^```python\n?/, '').replace(/\n?```$/, '').trim();
            const wrap = document.createElement('div');
            wrap.innerHTML = `<pre><code class="language-python">${esc(code)}</code></pre>`;
            const btn = document.createElement('button');
            btn.textContent = '⚡ Exécuter dans Django';
            btn.addEventListener('click', () => executeChatCode(code, btn));
            wrap.appendChild(btn);
            root.appendChild(wrap);
        } else {
            part.trim().split('\n').forEach(line => {
                if (!line.trim()) return;
                const p = document.createElement('p');
                p.textContent = line;
                root.appendChild(p);
            });
        }
    });
    return root;
}
```

Clicking Execute posts to the same `/execute-query/` endpoint, appends the results as a new chat bubble, and pushes them into `state.dataContext` so the LLM references them in all future turns.

---

## Part 5 — Client State Management

The entire frontend state lives in two arrays:

```javascript
const state = {
    history: [],     // [{role, content}] — sent to /chat/ on every message
    dataContext: [], // [{query, columns, rows}] — all executed results
};
```

After each execution, `state.dataContext` grows:

```javascript
// In the execute-btn handler, after a successful execution:
state.dataContext.push({
    query: code.substring(0, 80),
    columns: data.columns,
    rows: data.rows,
});
document.getElementById('chat-zone').style.display = 'block';
```

After each chat turn, `state.history` grows:

```javascript
state.history.push({ role: 'user', content: text });
// ... stream response ...
state.history.push({ role: 'assistant', content: fullText });
```

Both are serialised to JSON and sent with every chat request. The LLM always has full context.

---

## Models

```python
class QueryHistory(models.Model):
    schema = models.ForeignKey(DatabaseSchema, on_delete=models.SET_NULL, null=True)
    prompt_utilisateur = models.TextField()
    requete_generee = models.TextField(blank=True, null=True)
    query_type = models.CharField(max_length=50)
    execution_time = models.FloatField(null=True)
    is_helpful = models.BooleanField(null=True)  # thumbs up/down feedback
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
```

Every generation is persisted — duration, the prompt, and the generated code. The sidebar shows the last 10. The `is_helpful` field feeds back into the voting endpoint (`/vote/<id>/`).

---

## Running It

```bash
# 1. Pull the model
ollama pull llama3.1:8b

# 2. Clone and install
git clone https://github.com/alexandre00007/GenRequest.git
cd GenRequest
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Edit .env: set SECRET_KEY at minimum

# 4. Migrate and run
python manage.py migrate
python manage.py runserver
```

Open `http://127.0.0.1:8000`. Describe what you want. Execute. Chat.

---

## What I Learned

**Prompt engineering beats post-processing — but you need both.** The system prompt tells the LLM what's available and what's forbidden. But LLMs are probabilistic: they'll still occasionally write `models.Author`. The `re.sub(r'\bmodels?\.', '', code)` normalization is the silent safety net.

**`ast.parse` is the right tool for understanding generated code.** Regex on Python source is fragile. The AST tells you exactly what the last statement *is* — expression, assignment, or control flow — and gives you line numbers to slice the original source for multi-line expressions.

**Preserve indentation when preprocessing.** Every line-based preprocessor that calls `line.strip()` will break any generated code that uses `for`, `if`, or `with` blocks. Strip the *content* of unwanted lines, not the whitespace of the ones you keep.

**Materialise querysets before inspecting them.** `ValuesQuerySet` has a `.model` attribute but yields dicts. Calling `list(queryset)` first and branching on `isinstance(first, dict)` is the only reliable way to handle all queryset variants uniformly.

**SSE + StreamingHttpResponse is surprisingly straightforward in Django.** No WebSockets, no Channels, no async — just a generator function yielding `data: ...\n\n` lines. Disable Nginx buffering with `X-Accel-Buffering: no` and it works end-to-end.

---

## What's Next

- **Multi-schema support** — `DatabaseSchema` is already in the models; wiring it to the UI would let you switch between projects
- **Model picker** — instead of injecting the entire schema, let the user select which models are in scope for this session
- **Export** — download results as CSV directly from the table
- **Persistent chat sessions** — store conversation history in the DB so you can resume where you left off

- Note: To make your studio truly elite, add verbose names and help_text to your Django models. Your LLM can read these attributes to understand the business meaning of a field, not just its technical name.
---

*The full source is on GitHub: [alexandre00007/GenRequest](https://github.com/alexandre00007/GenRequest)*

*Stack: Django 4.2 · Ollama · llama3.1:8b · Python 3.8 · SQLite · vanilla JS*

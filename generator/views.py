import ast
import re
import time
import json
from collections import defaultdict, Counter
from itertools import chain, groupby, combinations
import ollama
from django.shortcuts import render, get_object_or_404
from django.http import StreamingHttpResponse, JsonResponse
from django.apps import apps
from django.db.models import (
    Q, F, Count, Sum, Avg, Max, Min, Value,
    Subquery, OuterRef, Case, When,
    IntegerField, CharField, FloatField, TextField,
)
from django.db.models.functions import Coalesce, Concat, Length, Lower, Upper

from .models import DatabaseSchema, QueryHistory
from .generator.executor import generate_project_schema_context


_BLOCKED_PATTERNS = [
    '__import__', '__builtins__', 'open(', 'os.', 'sys.',
    'subprocess', 'eval(', 'exec(', 'compile(', 'globals(', 'locals(',
]

# Pre-injected into every eval context — no imports needed in generated code.
_ORM_CONTEXT = {
    # Django ORM
    'Q': Q, 'F': F, 'Count': Count, 'Sum': Sum, 'Avg': Avg,
    'Max': Max, 'Min': Min, 'Value': Value, 'Subquery': Subquery,
    'OuterRef': OuterRef, 'Case': Case, 'When': When,
    'IntegerField': IntegerField, 'CharField': CharField,
    'FloatField': FloatField, 'TextField': TextField,
    'Coalesce': Coalesce, 'Concat': Concat,
    'Length': Length, 'Lower': Lower, 'Upper': Upper,
    # Python stdlib
    'chain': chain, 'groupby': groupby, 'combinations': combinations,
    'defaultdict': defaultdict, 'Counter': Counter,
}

_SAFE_BUILTINS = {
    'str': str, 'int': int, 'float': float, 'bool': bool,
    'list': list, 'dict': dict, 'tuple': tuple, 'set': set,
    'len': len, 'range': range, 'round': round,
    'sorted': sorted, 'reversed': reversed,
    'enumerate': enumerate, 'zip': zip, 'map': map, 'filter': filter,
    'min': min, 'max': max, 'sum': sum, 'abs': abs,
    'any': any, 'all': all,
    'isinstance': isinstance, 'hasattr': hasattr, 'getattr': getattr,
}

OLLAMA_MODEL = 'llama3.1:8b'

_IMPORT_RE = re.compile(r'^\s*(import |from \S+ import )')
_PRINT_RE = re.compile(r'^\s*print\s*\(')
_COMMENT_RE = re.compile(r'^\s*#')
_FENCE_RE = re.compile(r'^\s*```')
def _preprocess(code: str) -> list:
    """Strip import/print/comment/fence lines. Preserves indentation."""
    result = []
    for line in code.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if (_IMPORT_RE.match(stripped)
                or _PRINT_RE.match(stripped)
                or _COMMENT_RE.match(stripped)
                or _FENCE_RE.match(stripped)):
            continue
        result.append(line.rstrip())
    return result


def _find_result_expr(code: str) -> str:
    """
    Parse the preprocessed code with the AST and return the string to eval
    after exec()-ing the full block.

    - Last statement is a bare expression  → return its source (handles multi-line chains)
    - Last statement is an assignment      → return the target variable name
    - Last statement is a control-flow block → walk back to the last assignment
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    if not tree.body:
        return None

    src_lines = code.splitlines()
    last = tree.body[-1]

    if isinstance(last, ast.Expr):
        # Slice out the exact source lines for this expression (handles chained calls)
        chunk = src_lines[last.lineno - 1:last.end_lineno]
        indent = len(chunk[0]) - len(chunk[0].lstrip())
        return '\n'.join(l[indent:] for l in chunk)

    # Walk back for the last simple assignment (x = ...)
    for stmt in reversed(tree.body):
        if isinstance(stmt, ast.Assign) and isinstance(stmt.targets[-1], ast.Name):
            return stmt.targets[-1].id

    return None


def _extract_result(queryset):
    """Convert any queryset/value returned by eval into (columns, rows)."""
    if hasattr(queryset, 'model'):
        # Materialise once so we can inspect what the items actually are.
        # ValuesQuerySet yields dicts, ValuesListQuerySet yields tuples,
        # regular QuerySet yields model instances — each needs different handling.
        items = list(queryset)
        if not items:
            return [f.name for f in queryset.model._meta.fields], []

        first = items[0]

        if isinstance(first, dict):
            # .values() or .values().annotate(...)
            cols = list(first.keys())
            return cols, [[str(item.get(k, '')) for k in cols] for item in items]

        if isinstance(first, (list, tuple)):
            # .values_list()
            cols = [f'col_{i + 1}' for i in range(len(first))]
            return cols, [[str(v) for v in row] for row in items]

        # Regular model instances
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

    if isinstance(queryset, (list, tuple)):
        if not queryset:
            return ['Résultat'], []
        first = queryset[0]
        if isinstance(first, dict):
            cols = list(first.keys())
            return cols, [[str(item.get(k, '')) for k in cols] for item in queryset]
        if isinstance(first, (list, tuple)):
            cols = [f'col_{i + 1}' for i in range(len(first))]
            return cols, [[str(v) for v in row] for row in queryset]
        return ['Données'], [[str(item)] for item in queryset]

    return ['Données'], [[str(queryset)]]


def index(request):
    schemas = DatabaseSchema.objects.filter(is_active=True)
    history = QueryHistory.objects.all()[:10]
    return render(request, "generator/index.html", {
        "schemas": schemas,
        "history": history,
    })


def stream_query_generation(request):
    if request.method != "POST":
        return StreamingHttpResponse("Méthode non autorisée", status=405)

    user_prompt = request.POST.get("user_prompt", "").strip()
    if not user_prompt:
        return StreamingHttpResponse("Prompt vide.", status=400)

    query_type = request.POST.get("query_type", "Django ORM")
    dynamic_schema_context = generate_project_schema_context()

    model_names = ", ".join(
        m.__name__ for m in apps.get_models()
        if m._meta.app_label not in {'auth', 'contenttypes', 'sessions', 'admin'}
    )
    orm_helpers = "Q, F, Count, Sum, Avg, Max, Min, Value, Case, When, Subquery, OuterRef, Coalesce"

    system_instruction = (
        "Tu es un générateur de code Django ORM. Ton unique rôle est de produire du code Python exécutable.\n"
        f"{dynamic_schema_context}\n"
        "CONTEXTE D'EXÉCUTION — ces noms sont déjà disponibles, n'importe rien :\n"
        f"- Modèles : {model_names}\n"
        f"- Helpers ORM : {orm_helpers}\n"
        "- Python : chain, groupby, combinations, defaultdict, Counter, sorted, reversed, zip, map, filter, min, max, sum, any, all, isinstance\n\n"
        "RÈGLES ABSOLUES — toute violation rend la réponse inutilisable :\n"
        "1. Renvoie UNIQUEMENT du code Python exécutable. Aucune phrase, aucune explication.\n"
        "2. Interdit : commentaires (#...), imports, print(), markdown (```), texte en langage naturel.\n"
        "3. Référence les modèles directement par leur nom (ex: Author, Book). Jamais model.Author ou models.Author.\n"
        "4. Utilise UNIQUEMENT les modèles et champs listés ci-dessus. N'invente rien.\n"
        "5. Relations ForeignKey : syntaxe double underscore (ex: author__name).\n"
        "6. Si plusieurs lignes sont nécessaires, utilise des variables intermédiaires. La dernière ligne doit être l'expression finale à évaluer."
    )

    def event_stream():
        start_time = time.time()
        full_response = ""

        try:
            response_stream = ollama.generate(
                model=OLLAMA_MODEL,
                prompt=f"{system_instruction}\n\nDemande utilisateur : {user_prompt}",
                stream=True,
            )

            for chunk in response_stream:
                text_chunk = chunk['response']
                full_response += text_chunk
                yield f"data: {json.dumps({'text': text_chunk})}\n\n"

            duration = round(time.time() - start_time, 2)

            QueryHistory.objects.create(
                schema=None,
                prompt_utilisateur=user_prompt,
                requete_generee=full_response.strip(),
                query_type=query_type,
                execution_time=duration,
            )

            yield f"data: {json.dumps({'status': 'DONE', 'duration': duration})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response


def vote_query(request, query_id):
    if request.method != "POST":
        return JsonResponse({"status": "invalid_method"}, status=400)
    query = get_object_or_404(QueryHistory, id=query_id)
    value = request.POST.get("vote")
    query.is_helpful = (value == "up")
    query.save()
    return JsonResponse({"status": "success"})


def execute_generated_query(request):
    if request.method != "POST":
        return JsonResponse({"error": "Méthode non autorisée"}, status=405)

    orm_query = request.POST.get("sql_query", "").strip()
    if not orm_query:
        return JsonResponse({"error": "La requête ORM est vide."}, status=400)

    for pattern in _BLOCKED_PATTERNS:
        if pattern in orm_query:
            return JsonResponse(
                {"error": f"Requête refusée : motif interdit détecté ({pattern})."},
                status=400,
            )

    try:
        all_models = apps.get_models()
        context_globals = {model.__name__: model for model in all_models}
        context_globals.update(_ORM_CONTEXT)
        context_globals['__builtins__'] = _SAFE_BUILTINS

        model_names = {m.__name__ for m in all_models}
        if not any(name in orm_query for name in model_names):
            return JsonResponse(
                {"error": "Validation échouée : aucun modèle valide détecté dans la requête."},
                status=400,
            )

        preprocessed = "\n".join(_preprocess(orm_query))
        if not preprocessed.strip():
            return JsonResponse({"error": "Requête vide après nettoyage."}, status=400)

        # Normalize LLM hallucinations: models.Author → Author, model.Author → Author
        preprocessed = re.sub(r'\bmodels?\.', '', preprocessed)

        result_expr = _find_result_expr(preprocessed)
        if not result_expr:
            return JsonResponse({"error": "Impossible de déterminer l'expression résultat."}, status=400)

        exec(preprocessed, context_globals)
        queryset = eval(result_expr, context_globals)
        columns, rows = _extract_result(queryset)

        return JsonResponse({
            "status": "success",
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
        })

    except Exception as e:
        return JsonResponse(
            {"error": f"Erreur d'exécution ORM : {str(e)}"},
            status=400,
        )


def chat_with_data(request):
    """Multi-turn chat grounded in schema context and all previously executed results."""
    if request.method != "POST":
        return StreamingHttpResponse("Méthode non autorisée", status=405)

    message = request.POST.get("message", "").strip()
    if not message:
        return StreamingHttpResponse("Message vide.", status=400)

    try:
        history = json.loads(request.POST.get("history", "[]"))
        data_context = json.loads(request.POST.get("data_context", "[]"))
    except json.JSONDecodeError:
        return StreamingHttpResponse("Données invalides.", status=400)

    schema_context = generate_project_schema_context()

    data_sections = []
    for i, ctx in enumerate(data_context[-5:]):  # cap at last 5 result sets
        label = ctx.get("query", f"Résultat {i + 1}")
        header = " | ".join(ctx["columns"])
        rows_str = "\n".join(" | ".join(row) for row in ctx["rows"][:50])
        data_sections.append(f"[{label}]\n{header}\n{'-' * max(len(header), 1)}\n{rows_str}")

    data_str = "\n\n".join(data_sections) if data_sections else "Aucune donnée exécutée pour l'instant."

    system_content = (
        "Tu es un assistant expert Django ORM et analyse de données.\n\n"
        f"SCHÉMA DES MODÈLES :\n{schema_context}\n\n"
        f"DONNÉES DISPONIBLES (résultats des requêtes exécutées) :\n{data_str}\n\n"
        "RÈGLES :\n"
        "- Réponds en français, de façon concise et précise.\n"
        "- Appuie-toi sur les données disponibles. Ne génère pas de données fictives.\n"
        "- Si tu proposes du code Django ORM, entoure-le de ```python ... ``` pour qu'il soit exécutable directement.\n"
        "- Si une question nécessite des données absentes, propose une requête ORM à exécuter."
    )

    messages = [{"role": "system", "content": system_content}]
    for msg in history[-10:]:  # cap conversation context at last 10 turns
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": message})

    def event_stream():
        try:
            stream = ollama.chat(model=OLLAMA_MODEL, messages=messages, stream=True)
            for chunk in stream:
                text = chunk["message"]["content"]
                yield f"data: {json.dumps({'text': text})}\n\n"
            yield f"data: {json.dumps({'status': 'DONE'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response

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

from .models import DatabaseSchema, QueryHistory, ChatSession, ChatMessage
from .generator.executor import generate_project_schema_context, get_all_project_models


_BLOCKED_PATTERNS = [
    '__import__', '__builtins__', 'open(', 'os.', 'sys.',
    'subprocess', 'eval(', 'exec(', 'compile(', 'globals(', 'locals(',
]

_ORM_CONTEXT = {
    'Q': Q, 'F': F, 'Count': Count, 'Sum': Sum, 'Avg': Avg,
    'Max': Max, 'Min': Min, 'Value': Value, 'Subquery': Subquery,
    'OuterRef': OuterRef, 'Case': Case, 'When': When,
    'IntegerField': IntegerField, 'CharField': CharField,
    'FloatField': FloatField, 'TextField': TextField,
    'Coalesce': Coalesce, 'Concat': Concat,
    'Length': Length, 'Lower': Lower, 'Upper': Upper,
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
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None

    if not tree.body:
        return None

    src_lines = code.splitlines()
    last = tree.body[-1]

    if isinstance(last, ast.Expr):
        chunk = src_lines[last.lineno - 1:last.end_lineno]
        indent = len(chunk[0]) - len(chunk[0].lstrip())
        return '\n'.join(l[indent:] for l in chunk)

    for stmt in reversed(tree.body):
        if isinstance(stmt, ast.Assign) and isinstance(stmt.targets[-1], ast.Name):
            return stmt.targets[-1].id

    return None


def _extract_result(queryset):
    if hasattr(queryset, 'model'):
        items = list(queryset)
        if not items:
            return [f.name for f in queryset.model._meta.fields], []

        first = items[0]

        if isinstance(first, dict):
            cols = list(first.keys())
            return cols, [[str(item.get(k, '')) for k in cols] for item in items]

        if isinstance(first, (list, tuple)):
            cols = [f'col_{i + 1}' for i in range(len(first))]
            return cols, [[str(v) for v in row] for row in items]

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


def _parse_selected_models(raw):
    if not raw or not raw.strip():
        return None
    names = tuple(m.strip() for m in raw.split(',') if m.strip())
    return names if names else None


# ── Page ─────────────────────────────────────────────────────────────────────

def index(request):
    schemas = DatabaseSchema.objects.filter(is_active=True)
    history = QueryHistory.objects.all()[:10]
    return render(request, "generator/index.html", {
        "schemas": schemas,
        "history": history,
    })


# ── API: models list ──────────────────────────────────────────────────────────

def list_project_models(request):
    return JsonResponse({'models': get_all_project_models()})


# ── Generation ────────────────────────────────────────────────────────────────

def stream_query_generation(request):
    if request.method != "POST":
        return StreamingHttpResponse("Méthode non autorisée", status=405)

    user_prompt = request.POST.get("user_prompt", "").strip()
    if not user_prompt:
        return StreamingHttpResponse("Prompt vide.", status=400)

    query_type = request.POST.get("query_type", "Django ORM")
    selected_models_tuple = _parse_selected_models(request.POST.get("selected_models", ""))

    dynamic_schema_context = generate_project_schema_context(selected_models_tuple)

    all_models_list = apps.get_models()
    excluded = {'auth', 'contenttypes', 'sessions', 'admin'}
    if selected_models_tuple:
        in_scope = [m for m in all_models_list if m.__name__ in selected_models_tuple]
    else:
        in_scope = [m for m in all_models_list if m._meta.app_label not in excluded]

    model_names = ", ".join(m.__name__ for m in in_scope)
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


# ── Execution ─────────────────────────────────────────────────────────────────

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


# ── Chat ──────────────────────────────────────────────────────────────────────

def chat_with_data(request):
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

    selected_models_tuple = _parse_selected_models(request.POST.get("selected_models", ""))
    schema_context = generate_project_schema_context(selected_models_tuple)

    data_sections = []
    for i, ctx in enumerate(data_context[-5:]):
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
    for msg in history[-10:]:
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


# ── Sessions ──────────────────────────────────────────────────────────────────

def list_chat_sessions(request):
    sessions = ChatSession.objects.prefetch_related('messages').all()[:20]
    return JsonResponse({
        'sessions': [
            {
                'id': s.id,
                'name': s.name,
                'updated_at': s.updated_at.strftime('%d/%m %H:%M'),
                'message_count': s.messages.count(),
            }
            for s in sessions
        ]
    })


def save_chat_session(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    session_id = data.get('session_id')
    name = (data.get('name') or 'Session sans nom').strip() or 'Session sans nom'
    history = data.get('history', [])
    data_context = data.get('data_context', [])
    selected_models = data.get('selected_models', [])

    session = None
    if session_id:
        try:
            session = ChatSession.objects.get(id=session_id)
            session.name = name
            session.selected_models = ','.join(selected_models)
            session.data_context = json.dumps(data_context)
            session.save()
            session.messages.all().delete()
        except ChatSession.DoesNotExist:
            session = None

    if session is None:
        session = ChatSession.objects.create(
            name=name,
            selected_models=','.join(selected_models),
            data_context=json.dumps(data_context),
        )

    for msg in history:
        ChatMessage.objects.create(
            session=session,
            role=msg.get('role', 'user'),
            content=msg.get('content', ''),
        )

    return JsonResponse({'status': 'saved', 'session_id': session.id, 'name': session.name})


def load_chat_session(request, session_id):
    try:
        session = ChatSession.objects.prefetch_related('messages').get(id=session_id)
    except ChatSession.DoesNotExist:
        return JsonResponse({'error': 'Session introuvable'}, status=404)

    history = [{'role': m.role, 'content': m.content} for m in session.messages.all()]

    try:
        data_context = json.loads(session.data_context)
    except json.JSONDecodeError:
        data_context = []

    selected_models = [m for m in session.selected_models.split(',') if m.strip()]

    return JsonResponse({
        'session_id': session.id,
        'name': session.name,
        'history': history,
        'data_context': data_context,
        'selected_models': selected_models,
    })


def delete_chat_session(request, session_id):
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)
    try:
        ChatSession.objects.get(id=session_id).delete()
        return JsonResponse({'status': 'deleted'})
    except ChatSession.DoesNotExist:
        return JsonResponse({'error': 'Session introuvable'}, status=404)


# ── Auto-fix ──────────────────────────────────────────────────────────────

def stream_fix_query(request):
    """
    When executed ORM code raises an error, stream a corrected version back.
    Receives: failed_code, error_message, user_prompt, selected_models.
    """
    if request.method != "POST":
        return StreamingHttpResponse("Méthode non autorisée", status=405)

    failed_code = request.POST.get("failed_code", "").strip()
    error_message = request.POST.get("error_message", "").strip()
    user_prompt = request.POST.get("user_prompt", "").strip()

    if not failed_code or not error_message:
        return StreamingHttpResponse("Code ou erreur manquant.", status=400)

    selected_models_tuple = _parse_selected_models(request.POST.get("selected_models", ""))
    schema_context = generate_project_schema_context(selected_models_tuple)

    all_models_list = apps.get_models()
    excluded = {'auth', 'contenttypes', 'sessions', 'admin'}
    if selected_models_tuple:
        in_scope = [m for m in all_models_list if m.__name__ in selected_models_tuple]
    else:
        in_scope = [m for m in all_models_list if m._meta.app_label not in excluded]
    model_names = ", ".join(m.__name__ for m in in_scope)

    fix_prompt = (
        "Tu es un correcteur de code Django ORM. Le code ci-dessous a échoué — analyse l'erreur et renvoie le code corrigé.\n\n"
        f"SCHÉMA EXACT DES MODÈLES (utilise UNIQUEMENT ces noms) :\n{schema_context}\n"
        f"MODÈLES DISPONIBLES : {model_names}\n\n"
        f"CODE ÉCHOUÉ :\n{failed_code}\n\n"
        f"MESSAGE D'ERREUR : {error_message}\n\n"
        f"DEMANDE ORIGINALE : {user_prompt}\n\n"
        "ANALYSE DE L'ERREUR :\n"
        "- 'Cannot resolve keyword X' → X n'existe pas ; utilise le nom exact du champ ou du reverse accessor listé dans le schéma\n"
        "- 'invalid literal' ou mauvaise valeur de choice → utilise les valeurs entre crochets [valeurs: ...] listées dans le schéma\n"
        "- AttributeError sur un objet → vérifie que l'expression finale renvoie bien un QuerySet ou une valeur\n\n"
        "RÈGLES ABSOLUES :\n"
        "1. Renvoie UNIQUEMENT le code Python corrigé. Aucune explication, aucun commentaire.\n"
        "2. Interdit : imports, print(), markdown (```).\n"
        "3. Utilise UNIQUEMENT les noms de champs et accessors exacts listés dans le schéma ci-dessus.\n"
        "4. La dernière ligne doit être l'expression à évaluer (QuerySet, agrégat, etc.)."
    )

    def event_stream():
        try:
            stream = ollama.generate(model=OLLAMA_MODEL, prompt=fix_prompt, stream=True)
            for chunk in stream:
                text = chunk['response']
                yield f"data: {json.dumps({'text': text})}\n\n"
            yield f"data: {json.dumps({'status': 'DONE'})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    response = StreamingHttpResponse(event_stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response

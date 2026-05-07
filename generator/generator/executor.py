from django.apps import apps
from django.db.models.fields.related import (
    ForeignKey, ManyToManyField, ManyToOneRel, ManyToManyRel, OneToOneRel,
)

_EXCLUDED_APP_LABELS = {'auth', 'contenttypes', 'sessions', 'admin'}

# Dict-based cache keyed by selected_models tuple (or None for all).
# Invalidated by restarting the server after migrations (same as before).
_schema_cache = {}


def generate_project_schema_context(selected_models=None) -> str:
    """
    Returns a structured LLM-context string describing available Django models.
    selected_models: tuple of model class names to include, or None for all.
    Includes verbose_name, help_text, choices, and reverse relation accessors
    so the LLM has everything it needs to avoid hallucinating field/related names.
    """
    cache_key = selected_models
    if cache_key in _schema_cache:
        return _schema_cache[cache_key]

    lines = ["Voici la structure exacte et exclusive des modèles Django disponibles :\n"]

    for model in apps.get_models():
        if model._meta.app_label in _EXCLUDED_APP_LABELS:
            continue
        if selected_models and model.__name__ not in selected_models:
            continue

        verbose_name = str(model._meta.verbose_name or model.__name__)
        lines.append(f"Modèle: {model.__name__} (nom métier: {verbose_name})")
        lines.append("Champs disponibles :")

        for field in model._meta.get_fields():
            # ── Reverse relations (ForeignKey/M2M defined on the OTHER model) ──
            if isinstance(field, (ManyToOneRel, OneToOneRel)):
                accessor = field.get_accessor_name()
                source = field.related_model.__name__
                lines.append(f"  - {accessor} (reverse FK depuis {source}) ← utiliser pour filter({accessor}__champ=val)")
                continue
            if isinstance(field, ManyToManyRel):
                accessor = field.get_accessor_name()
                source = field.related_model.__name__
                lines.append(f"  - {accessor} (reverse M2M depuis {source})")
                continue

            if not hasattr(field, 'verbose_name'):
                continue

            field_type = field.get_internal_type()
            v_name = str(getattr(field, 'verbose_name', field.name))
            help_txt = str(getattr(field, 'help_text', '') or '')

            annotation = ''
            if v_name and v_name != field.name:
                annotation = f' — "{v_name}"'
            if help_txt:
                annotation += f' ({help_txt})'

            # Expose choices values so the LLM uses the exact DB value
            choices = getattr(field, 'choices', None)
            if choices:
                vals = ', '.join(f"'{k}'" for k, _ in choices)
                annotation += f' [valeurs: {vals}]'

            if isinstance(field, ForeignKey):
                target = field.remote_field.model.__name__
                lines.append(f"  - {field.name} (ForeignKey) -> '{target}'{annotation}")
            elif isinstance(field, ManyToManyField):
                target = field.remote_field.model.__name__
                lines.append(f"  - {field.name} (ManyToManyField) -> '{target}'{annotation}")
            else:
                lines.append(f"  - {field.name} ({field_type}){annotation}")

        lines.append("")

    result = "\n".join(lines)
    _schema_cache[cache_key] = result
    return result


def get_all_project_models():
    """Return a list of model info dicts for all non-internal models."""
    result = []
    for model in apps.get_models():
        if model._meta.app_label in _EXCLUDED_APP_LABELS:
            continue
        result.append({
            'name': model.__name__,
            'app': model._meta.app_label,
            'verbose': str(model._meta.verbose_name_plural or model.__name__),
        })
    return result

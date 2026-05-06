from functools import lru_cache
from django.apps import apps
from django.db.models.fields.related import ForeignKey, ManyToManyField

_EXCLUDED_APP_LABELS = {'auth', 'contenttypes', 'sessions', 'admin'}


@lru_cache(maxsize=1)
def generate_project_schema_context() -> str:
    """
    Introspects all project models once and returns a structured string
    describing the schema for use as LLM context.
    """
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

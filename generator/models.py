from django.db import models
from django.contrib.auth.models import User

class DatabaseSchema(models.Model):
    """Stocke la structure de la base de données pour nourrir le contexte du LLM."""
    name = models.CharField(max_length=100, unique=True, verbose_name="Nom du projet / BDD")
    dialect = models.CharField(
        max_length=50, 
        choices=[('PostgreSQL', 'PostgreSQL'), ('MySQL', 'MySQL'), ('SQLite', 'SQLite'), ('MongoDB', 'MongoDB'), ('Django ORM', 'Django ORM')],
        default='PostgreSQL'
    )
    schema_definition = models.TextField(
        help_text="Collez ici le DDL (CREATE TABLE...) ou la description des tables et types."
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.dialect})"

class QueryHistory(models.Model):
    """Enregistre l'historique des interactions et permet le feedback."""
    schema = models.ForeignKey(DatabaseSchema, on_delete=models.SET_NULL, null=True, blank=True)
    prompt_utilisateur = models.TextField()
    requete_generee = models.TextField(blank=True, null=True)
    query_type = models.CharField(max_length=50) # SQL, Django ORM, etc.
    execution_time = models.FloatField(help_text="Temps de réponse de l'IA en secondes", null=True, blank=True)
    is_helpful = models.BooleanField(null=True, blank=True, verbose_name="Utile ?")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Requête {self.query_type} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"
    
class Author(models.Model):
    name = models.CharField(max_length=100)
    def __str__(self):
        return self.name

class Book(models.Model):
    title = models.CharField(max_length=200)
    # Each Book belongs to one Author, but an Author can have many Books
    author = models.ForeignKey(Author, on_delete=models.CASCADE)
    def __str__(self):
        return self.title
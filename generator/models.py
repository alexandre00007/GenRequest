from django.db import models


class DatabaseSchema(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name="Nom du projet / BDD")
    dialect = models.CharField(
        max_length=50,
        choices=[('PostgreSQL', 'PostgreSQL'), ('MySQL', 'MySQL'), ('SQLite', 'SQLite'), ('MongoDB', 'MongoDB'), ('Django ORM', 'Django ORM')],
        default='Django ORM',
    )
    schema_definition = models.TextField(
        blank=True, default='',
        help_text="Description optionnelle du projet / DDL.",
    )
    models_filter = models.TextField(
        blank=True, default='',
        verbose_name="Filtrer les modèles",
        help_text="Noms des modèles à inclure (séparés par virgule). Vide = tous les modèles.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Schéma / Projet"
        verbose_name_plural = "Schémas / Projets"

    def __str__(self):
        return f"{self.name} ({self.dialect})"


class QueryHistory(models.Model):
    schema = models.ForeignKey(DatabaseSchema, on_delete=models.SET_NULL, null=True, blank=True)
    prompt_utilisateur = models.TextField()
    requete_generee = models.TextField(blank=True, null=True)
    query_type = models.CharField(max_length=50)
    execution_time = models.FloatField(help_text="Temps de réponse de l'IA en secondes", null=True, blank=True)
    is_helpful = models.BooleanField(null=True, blank=True, verbose_name="Utile ?")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Historique de requête"
        verbose_name_plural = "Historique des requêtes"

    def __str__(self):
        return f"Requête {self.query_type} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"


class ChatSession(models.Model):
    name = models.CharField(
        max_length=200,
        verbose_name="Nom de session",
        help_text="Nom descriptif pour retrouver cette session",
    )
    selected_models = models.TextField(
        blank=True, default='',
        verbose_name="Modèles sélectionnés",
        help_text="Noms des modèles Django en scope, séparés par virgule",
    )
    data_context = models.TextField(
        blank=True, default='[]',
        verbose_name="Contexte de données",
        help_text="Résultats des requêtes exécutées (JSON)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        verbose_name = "Session de chat"
        verbose_name_plural = "Sessions de chat"

    def __str__(self):
        return f"{self.name} ({self.updated_at.strftime('%Y-%m-%d %H:%M')})"


class ChatMessage(models.Model):
    ROLE_CHOICES = [('user', 'Utilisateur'), ('assistant', 'Assistant')]
    session = models.ForeignKey(ChatSession, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, verbose_name="Rôle")
    content = models.TextField(verbose_name="Contenu")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = "Message de chat"
        verbose_name_plural = "Messages de chat"

    def __str__(self):
        return f"{self.role} @ {self.created_at.strftime('%H:%M:%S')}"


class Author(models.Model):
    name = models.CharField(
        max_length=100,
        verbose_name="Nom complet",
        help_text="Nom et prénom de l'auteur",
    )

    class Meta:
        verbose_name = "Auteur"
        verbose_name_plural = "Auteurs"

    def __str__(self):
        return self.name


class Book(models.Model):
    title = models.CharField(
        max_length=200,
        verbose_name="Titre",
        help_text="Titre complet du livre",
    )
    author = models.ForeignKey(
        Author,
        on_delete=models.CASCADE,
        verbose_name="Auteur",
        help_text="Auteur principal du livre",
    )

    class Meta:
        verbose_name = "Livre"
        verbose_name_plural = "Livres"

    def __str__(self):
        return self.title

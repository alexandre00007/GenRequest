from django.db import models


class Categorie(models.Model):
    nom = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Nom de la catégorie",
        help_text="Famille de produits (ex: Électronique, Mobilier, Textile)",
    )
    description = models.TextField(
        blank=True, default='',
        verbose_name="Description",
        help_text="Description commerciale de la catégorie",
    )

    class Meta:
        verbose_name = "Catégorie"
        verbose_name_plural = "Catégories"
        ordering = ['nom']

    def __str__(self):
        return self.nom


class Produit(models.Model):
    reference = models.CharField(
        max_length=20,
        unique=True,
        verbose_name="Référence produit",
        help_text="Code SKU interne (ex: ELEC-001)",
    )
    nom = models.CharField(
        max_length=200,
        verbose_name="Nom du produit",
        help_text="Désignation commerciale complète",
    )
    categorie = models.ForeignKey(
        Categorie,
        on_delete=models.PROTECT,
        related_name='produits',
        verbose_name="Catégorie",
        help_text="Famille à laquelle appartient ce produit",
    )
    prix_unitaire = models.DecimalField(
        max_digits=10, decimal_places=2,
        verbose_name="Prix unitaire HT (€)",
        help_text="Prix de vente hors taxes en euros",
    )
    cout_achat = models.DecimalField(
        max_digits=10, decimal_places=2,
        verbose_name="Coût d'achat HT (€)",
        help_text="Prix de revient pour calculer la marge brute",
    )
    stock = models.IntegerField(
        default=0,
        verbose_name="Stock disponible",
        help_text="Nombre d'unités en stock au moment de la requête",
    )
    actif = models.BooleanField(
        default=True,
        verbose_name="Produit actif",
        help_text="False = produit arrêté, ne plus proposer à la vente",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Produit"
        verbose_name_plural = "Produits"
        ordering = ['categorie', 'nom']

    def __str__(self):
        return f"{self.reference} — {self.nom}"


class Region(models.Model):
    nom = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Région",
        help_text="Région administrative française (ex: Île-de-France, Auvergne-Rhône-Alpes)",
    )
    code = models.CharField(
        max_length=10,
        unique=True,
        verbose_name="Code région",
        help_text="Code court utilisé en interne (ex: IDF, ARA)",
    )

    class Meta:
        verbose_name = "Région"
        verbose_name_plural = "Régions"
        ordering = ['nom']

    def __str__(self):
        return self.nom


class Vendeur(models.Model):
    nom = models.CharField(
        max_length=100,
        verbose_name="Nom",
        help_text="Nom de famille du commercial",
    )
    prenom = models.CharField(
        max_length=100,
        verbose_name="Prénom",
        help_text="Prénom du commercial",
    )
    email = models.EmailField(
        unique=True,
        verbose_name="Email professionnel",
    )
    region = models.ForeignKey(
        Region,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='vendeurs',
        verbose_name="Région assignée",
        help_text="Zone géographique de prospection du commercial",
    )
    objectif_mensuel = models.DecimalField(
        max_digits=10, decimal_places=2,
        verbose_name="Objectif mensuel (€)",
        help_text="Chiffre d'affaires HT mensuel cible du commercial",
    )
    date_embauche = models.DateField(
        verbose_name="Date d'embauche",
    )
    actif = models.BooleanField(
        default=True,
        verbose_name="Actif",
        help_text="False = commercial parti ou suspendu",
    )

    class Meta:
        verbose_name = "Vendeur"
        verbose_name_plural = "Vendeurs"
        ordering = ['nom', 'prenom']

    def __str__(self):
        return f"{self.prenom} {self.nom}"


class Client(models.Model):
    SEGMENT_CHOICES = [
        ('B2C',    'Particulier (B2C)'),
        ('PME',    'PME (B2B)'),
        ('GRAND',  'Grand compte'),
        ('PUBLIC', 'Secteur public'),
    ]

    nom = models.CharField(
        max_length=200,
        verbose_name="Nom / Raison sociale",
        help_text="Nom du client particulier ou raison sociale de l'entreprise",
    )
    email = models.EmailField(
        unique=True,
        verbose_name="Email",
    )
    telephone = models.CharField(
        max_length=20, blank=True, default='',
        verbose_name="Téléphone",
    )
    ville = models.CharField(
        max_length=100,
        verbose_name="Ville",
    )
    region = models.ForeignKey(
        Region,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='clients',
        verbose_name="Région",
        help_text="Région administrative du client — utile pour l'analyse géographique",
    )
    segment = models.CharField(
        max_length=10,
        choices=SEGMENT_CHOICES,
        default='B2C',
        verbose_name="Segment client",
        help_text="Catégorie commerciale : B2C = particulier, PME = entreprise, GRAND = key account, PUBLIC = administration",
    )
    chiffre_affaires_cumul = models.DecimalField(
        max_digits=12, decimal_places=2,
        default=0,
        verbose_name="CA cumulé (€)",
        help_text="Chiffre d'affaires total généré depuis la création du compte",
    )
    date_creation = models.DateField(
        verbose_name="Date de création du compte",
    )
    vendeur_attitré = models.ForeignKey(
        Vendeur,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='clients',
        verbose_name="Commercial attitré",
        help_text="Vendeur responsable de ce compte client",
    )

    class Meta:
        verbose_name = "Client"
        verbose_name_plural = "Clients"
        ordering = ['nom']

    def __str__(self):
        return f"{self.nom} ({self.segment})"


class Commande(models.Model):
    STATUT_CHOICES = [
        ('BROUILLON',  'Brouillon'),
        ('CONFIRMEE',  'Confirmée'),
        ('EXPEDIEE',   'Expédiée'),
        ('LIVREE',     'Livrée'),
        ('ANNULEE',    'Annulée'),
    ]
    PAIEMENT_CHOICES = [
        ('CB',        'Carte bancaire'),
        ('VIREMENT',  'Virement bancaire'),
        ('CHEQUE',    'Chèque'),
        ('ESPECES',   'Espèces'),
    ]

    numero = models.CharField(
        max_length=20,
        unique=True,
        verbose_name="Numéro de commande",
        help_text="Identifiant unique (ex: CMD-2024-00042)",
    )
    client = models.ForeignKey(
        Client,
        on_delete=models.PROTECT,
        related_name='commandes',
        verbose_name="Client",
    )
    vendeur = models.ForeignKey(
        Vendeur,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='commandes',
        verbose_name="Commercial",
        help_text="Vendeur ayant saisi la commande ; null si vente en ligne directe",
    )
    date_commande = models.DateField(
        verbose_name="Date de commande",
    )
    date_livraison_prevue = models.DateField(
        null=True, blank=True,
        verbose_name="Date de livraison prévue",
    )
    statut = models.CharField(
        max_length=12,
        choices=STATUT_CHOICES,
        default='CONFIRMEE',
        verbose_name="Statut",
        help_text="État actuel de la commande dans le cycle de vie",
    )
    mode_paiement = models.CharField(
        max_length=10,
        choices=PAIEMENT_CHOICES,
        default='CB',
        verbose_name="Mode de paiement",
    )
    remise_globale = models.DecimalField(
        max_digits=5, decimal_places=2,
        default=0,
        verbose_name="Remise globale (%)",
        help_text="Remise commerciale appliquée sur le total de la commande (0–100)",
    )
    note = models.TextField(
        blank=True, default='',
        verbose_name="Note interne",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Commande"
        verbose_name_plural = "Commandes"
        ordering = ['-date_commande']

    def __str__(self):
        return f"{self.numero} — {self.client}"

    @property
    def montant_ht(self):
        total = sum(l.montant_ht for l in self.lignes.all())
        return total * (1 - self.remise_globale / 100)


class LigneCommande(models.Model):
    commande = models.ForeignKey(
        Commande,
        on_delete=models.CASCADE,
        related_name='lignes',
        verbose_name="Commande",
    )
    produit = models.ForeignKey(
        Produit,
        on_delete=models.PROTECT,
        related_name='lignes_vente',
        verbose_name="Produit",
    )
    quantite = models.PositiveIntegerField(
        verbose_name="Quantité",
        help_text="Nombre d'unités commandées",
    )
    prix_unitaire_ht = models.DecimalField(
        max_digits=10, decimal_places=2,
        verbose_name="Prix unitaire HT (€)",
        help_text="Prix au moment de la commande, peut différer du tarif actuel",
    )
    remise_ligne = models.DecimalField(
        max_digits=5, decimal_places=2,
        default=0,
        verbose_name="Remise ligne (%)",
        help_text="Remise spécifique à cette ligne (0–100)",
    )

    class Meta:
        verbose_name = "Ligne de commande"
        verbose_name_plural = "Lignes de commande"

    def __str__(self):
        return f"{self.commande.numero} × {self.produit.reference} ×{self.quantite}"

    @property
    def montant_ht(self):
        return self.quantite * self.prix_unitaire_ht * (1 - self.remise_ligne / 100)


class Retour(models.Model):
    MOTIF_CHOICES = [
        ('DEFAUT',    'Produit défectueux'),
        ('ERREUR',    'Erreur de commande'),
        ('INSATISF',  'Insatisfaction client'),
        ('DOUBLON',   'Commande en doublon'),
        ('DELAI',     'Délai de livraison dépassé'),
        ('AUTRE',     'Autre'),
    ]

    commande = models.ForeignKey(
        Commande,
        on_delete=models.PROTECT,
        related_name='retours',
        verbose_name="Commande d'origine",
    )
    date_retour = models.DateField(
        verbose_name="Date du retour",
    )
    motif = models.CharField(
        max_length=10,
        choices=MOTIF_CHOICES,
        verbose_name="Motif du retour",
        help_text="Raison principale du retour client",
    )
    montant_rembourse = models.DecimalField(
        max_digits=10, decimal_places=2,
        verbose_name="Montant remboursé HT (€)",
        help_text="Montant effectivement crédité au client",
    )
    traite = models.BooleanField(
        default=False,
        verbose_name="Traité",
        help_text="True = remboursement émis et validé",
    )

    class Meta:
        verbose_name = "Retour"
        verbose_name_plural = "Retours"
        ordering = ['-date_retour']

    def __str__(self):
        return f"Retour {self.commande.numero} — {self.motif}"

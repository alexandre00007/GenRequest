"""
Génère 18 mois de données de ventes réalistes pour l'app Vente.
Usage : python manage.py seed_ventes [--clear]
"""
import random
import decimal
from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from Vente.models import (
    Categorie, Produit, Region, Vendeur, Client,
    Commande, LigneCommande, Retour,
)

# ── Données de référence ──────────────────────────────────────────────────

REGIONS = [
    ("Île-de-France",           "IDF"),
    ("Auvergne-Rhône-Alpes",    "ARA"),
    ("Provence-Alpes-Côte d'Azur", "PACA"),
    ("Nouvelle-Aquitaine",      "NAQ"),
    ("Occitanie",               "OCC"),
    ("Hauts-de-France",         "HDF"),
    ("Grand Est",               "GRE"),
    ("Bretagne",                "BRE"),
    ("Normandie",               "NOR"),
    ("Pays de la Loire",        "PDL"),
]

VILLES_PAR_REGION = {
    "IDF":  ["Paris", "Versailles", "Boulogne-Billancourt", "Montreuil", "Créteil"],
    "ARA":  ["Lyon", "Grenoble", "Clermont-Ferrand", "Annecy", "Chambéry"],
    "PACA": ["Marseille", "Nice", "Toulon", "Aix-en-Provence", "Avignon"],
    "NAQ":  ["Bordeaux", "Limoges", "Poitiers", "La Rochelle", "Pau"],
    "OCC":  ["Toulouse", "Montpellier", "Nîmes", "Perpignan", "Albi"],
    "HDF":  ["Lille", "Amiens", "Valenciennes", "Roubaix", "Dunkerque"],
    "GRE":  ["Strasbourg", "Metz", "Nancy", "Reims", "Mulhouse"],
    "BRE":  ["Rennes", "Brest", "Nantes", "Lorient", "Vannes"],
    "NOR":  ["Rouen", "Caen", "Le Havre", "Cherbourg", "Évreux"],
    "PDL":  ["Nantes", "Le Mans", "Angers", "Saint-Nazaire", "Laval"],
}

CATEGORIES_PRODUITS = [
    ("Électronique",   "ELEC", [
        ("Laptop Ultrabook 14\"",    "1299.00", "680.00"),
        ("Laptop Gaming 15\"",       "1799.00", "980.00"),
        ("Tablette 10\"",            "449.00",  "210.00"),
        ("Smartphone Pro",           "899.00",  "420.00"),
        ("Casque Bluetooth",         "149.00",  "55.00"),
        ("Écran 27\" 4K",            "399.00",  "195.00"),
        ("Clavier mécanique",        "129.00",  "42.00"),
        ("Souris ergonomique",       "79.00",   "22.00"),
    ]),
    ("Mobilier Bureau", "MOBU", [
        ("Bureau assis-debout",      "689.00",  "290.00"),
        ("Fauteuil ergonomique",     "449.00",  "185.00"),
        ("Caisson 3 tiroirs",        "189.00",  "75.00"),
        ("Étagère modulable 5 niv.", "229.00",  "88.00"),
        ("Table de réunion 8 pers.", "1190.00", "520.00"),
    ]),
    ("Fournitures",    "FOUR", [
        ("Ramette papier A4 500f",   "8.90",   "3.20"),
        ("Stylo bille (lot 12)",     "6.50",   "1.80"),
        ("Classeur levier A4",       "4.20",   "1.10"),
        ("Post-it (lot 8)",          "9.90",   "2.90"),
        ("Agrafeuse de bureau",      "14.90",  "4.50"),
    ]),
    ("Logiciels",      "LOGI", [
        ("Suite bureautique annuel", "99.00",  "12.00"),
        ("Antivirus Pro 3 postes",   "49.90",  "8.00"),
        ("Comptabilité PME",         "299.00", "35.00"),
        ("CRM Starter 5 users",      "199.00", "28.00"),
    ]),
    ("Réseau & Serveurs", "RESV", [
        ("Switch 24 ports Gigabit",  "249.00", "110.00"),
        ("Routeur Wi-Fi 6 Pro",      "179.00", "72.00"),
        ("NAS 4 baies",              "399.00", "165.00"),
        ("Disque dur 4 To NAS",      "89.00",  "38.00"),
        ("Câble RJ45 Cat6 (10 m)",   "12.90",  "3.50"),
    ]),
    ("Impression",     "IMPR", [
        ("Imprimante laser N&B",     "299.00", "130.00"),
        ("Imprimante couleur A3",    "599.00", "260.00"),
        ("Toner noir compatible",    "39.90",  "9.00"),
        ("Scanner A4 recto-verso",   "189.00", "72.00"),
    ]),
]

PRENOMS = ["Alice", "Bruno", "Camille", "David", "Emma", "Florent",
           "Gaëlle", "Hugo", "Inès", "Julien", "Karen", "Laurent",
           "Marie", "Nicolas", "Olivia", "Pierre", "Quentin", "Rachelle",
           "Sophie", "Thomas", "Ursula", "Victor", "Wendy", "Xavier"]

NOMS_FAM = ["Martin", "Bernard", "Dubois", "Thomas", "Robert", "Richard",
            "Petit", "Durand", "Leroy", "Moreau", "Simon", "Laurent",
            "Lefebvre", "Michel", "Garcia", "David", "Bertrand", "Roux",
            "Vincent", "Fournier", "Morel", "Girard", "André", "Mercier"]

SOCIETES = ["Acme Corp", "TechSol", "InfraGroup", "ProService", "DataSys",
            "NovaTech", "AlphaConsult", "BetaInvest", "GammaCloud", "DeltaPro",
            "Epsilon Solutions", "Zeta Partners", "Eta Conseil", "Theta Digital",
            "Iota Systems", "Kappa Industries", "Lambda Networks", "Mu Analytics"]

DOMAINES = ["gmail.com", "outlook.com", "laposte.net", "orange.fr",
            "sfr.fr", "free.fr", "yahoo.fr"]

DOMAINES_PRO = ["techsol.fr", "infra-group.com", "proservice.fr", "datasys.io",
                "novatech.eu", "alpha-consulting.fr", "betainvest.com"]


def _d(s):
    return decimal.Decimal(s)


def rand_date(start_days_ago, end_days_ago=0):
    delta = random.randint(end_days_ago, start_days_ago)
    return date.today() - timedelta(days=delta)


def slug_email(prenom, nom, domaine):
    p = prenom.lower().replace("ë","e").replace("é","e").replace("è","e").replace("ê","e")
    n = nom.lower().replace("ë","e").replace("é","e").replace("è","e").replace("ê","e")
    return f"{p}.{n}@{domaine}"


class Command(BaseCommand):
    help = "Seed 18 mois de données de ventes (régions, vendeurs, clients, commandes, retours)"

    def add_arguments(self, parser):
        parser.add_argument('--clear', action='store_true', help='Supprimer les données existantes avant de semer')

    @transaction.atomic
    def handle(self, *args, **options):
        if options['clear']:
            self.stdout.write("Suppression des données existantes…")
            Retour.objects.all().delete()
            LigneCommande.objects.all().delete()
            Commande.objects.all().delete()
            Client.objects.all().delete()
            Vendeur.objects.all().delete()
            Produit.objects.all().delete()
            Categorie.objects.all().delete()
            Region.objects.all().delete()
            self.stdout.write(self.style.WARNING("  Tables vidées."))

        # ── Régions ───────────────────────────────────────────────────────
        self.stdout.write("Création des régions…")
        region_objs = {}
        for nom, code in REGIONS:
            r, _ = Region.objects.get_or_create(code=code, defaults={'nom': nom})
            region_objs[code] = r

        # ── Catégories & Produits ─────────────────────────────────────────
        self.stdout.write("Création des catégories et produits…")
        produit_objs = []
        for cat_nom, prefix, items in CATEGORIES_PRODUITS:
            cat, _ = Categorie.objects.get_or_create(nom=cat_nom)
            for i, (nom_p, prix, cout) in enumerate(items, start=1):
                ref = f"{prefix}-{i:03d}"
                p, _ = Produit.objects.get_or_create(
                    reference=ref,
                    defaults={
                        'nom': nom_p,
                        'categorie': cat,
                        'prix_unitaire': _d(prix),
                        'cout_achat': _d(cout),
                        'stock': random.randint(5, 200),
                        'actif': True,
                    }
                )
                produit_objs.append(p)

        # ── Vendeurs ──────────────────────────────────────────────────────
        self.stdout.write("Création des vendeurs…")
        vendeur_data = [
            ("Dupont",    "Marc",      "IDF", "85000.00", 730),
            ("Legrand",   "Julie",     "ARA", "72000.00", 900),
            ("Fontaine",  "Éric",      "PACA","68000.00", 750),
            ("Chevalier", "Nathalie",  "NAQ", "60000.00", 800),
            ("Garnier",   "Sébastien", "HDF", "58000.00", 850),
            ("Leblanc",   "Amélie",    "OCC", "62000.00", 780),
            ("Bonnet",    "Thomas",    "GRE", "55000.00", 920),
        ]
        vendeur_objs = []
        for nom, prenom, reg_code, obj, hire_days in vendeur_data:
            email = f"{prenom.lower().replace('é','e').replace('è','e')}.{nom.lower()}@ormstudio.fr"
            v, _ = Vendeur.objects.get_or_create(
                email=email,
                defaults={
                    'nom': nom, 'prenom': prenom,
                    'region': region_objs[reg_code],
                    'objectif_mensuel': _d(obj),
                    'date_embauche': date.today() - timedelta(days=hire_days),
                    'actif': True,
                }
            )
            vendeur_objs.append(v)

        # ── Clients ───────────────────────────────────────────────────────
        self.stdout.write("Création des clients (80 B2C + 40 PME + 10 Grands comptes + 10 Public)…")
        client_specs = [
            ('B2C',    80, NOMS_FAM,  DOMAINES),
            ('PME',    40, SOCIETES,  DOMAINES_PRO),
            ('GRAND',  10, SOCIETES,  DOMAINES_PRO),
            ('PUBLIC', 10, SOCIETES,  ["mairie.fr", "region.fr", "hopital.fr", "academie.fr"]),
        ]
        client_objs = []
        used_emails = set()
        for segment, count, nom_pool, dom_pool in client_specs:
            pool = list(nom_pool)
            for _ in range(count):
                reg_code, villes = random.choice(list(VILLES_PAR_REGION.items()))
                region = region_objs[reg_code]
                ville = random.choice(villes)
                if segment == 'B2C':
                    prenom = random.choice(PRENOMS)
                    nom = random.choice(pool)
                    nom_complet = f"{prenom} {nom}"
                    base_email = slug_email(prenom, nom, random.choice(dom_pool))
                else:
                    nom_complet = random.choice(pool) + (f" {ville}" if segment in ('PUBLIC',) else "")
                    slug = nom_complet.lower().replace(" ", "").replace("-", "")[:12]
                    base_email = f"contact.{slug}@{random.choice(dom_pool)}"

                # Make email unique
                email = base_email
                suffix = 2
                while email in used_emails:
                    parts = base_email.split('@')
                    email = f"{parts[0]}{suffix}@{parts[1]}"
                    suffix += 1
                used_emails.add(email)

                vendeur = random.choice(vendeur_objs) if random.random() < 0.7 else None
                c = Client.objects.create(
                    nom=nom_complet,
                    email=email,
                    telephone=f"0{random.randint(6,7)}{random.randint(10000000,99999999)}",
                    ville=ville,
                    region=region,
                    segment=segment,
                    chiffre_affaires_cumul=_d("0.00"),
                    date_creation=rand_date(900, 550),
                    vendeur_attitré=vendeur,
                )
                client_objs.append(c)

        # ── Commandes sur 18 mois ─────────────────────────────────────────
        self.stdout.write("Génération des commandes (18 mois)…")

        # Saisonnalité mensuelle : indice de volume relatif (jan=1.0 = base)
        saisonnalite = {1:0.7, 2:0.8, 3:1.0, 4:1.1, 5:1.2, 6:1.1,
                        7:0.6, 8:0.5, 9:1.2, 10:1.3, 11:1.4, 12:1.6}

        statuts_poids = [
            ('LIVREE',    55),
            ('EXPEDIEE',  15),
            ('CONFIRMEE', 20),
            ('ANNULEE',    7),
            ('BROUILLON',  3),
        ]
        statuts, poids = zip(*statuts_poids)

        paiements = ['CB', 'CB', 'CB', 'VIREMENT', 'VIREMENT', 'CHEQUE', 'ESPECES']

        commandes_a_retour = []
        cmd_counter = 1
        today = date.today()

        for days_ago in range(548, 0, -1):  # 18 mois ≈ 548 jours
            cmd_date = today - timedelta(days=days_ago)
            mois = cmd_date.month
            base_cmds = 2  # commandes par jour en base
            nb_cmds = int(base_cmds * saisonnalite[mois] * random.uniform(0.5, 1.8))

            for _ in range(nb_cmds):
                client = random.choice(client_objs)
                # Grands comptes commandent plus souvent en semaine
                vendeur = client.vendeur_attitré if (client.segment in ('GRAND', 'PME') and random.random() < 0.8) else (random.choice(vendeur_objs) if random.random() < 0.4 else None)

                statut = random.choices(statuts, weights=poids, k=1)[0]
                # Les commandes récentes (< 30 j) sont rarement livrées
                if days_ago < 30 and statut == 'LIVREE':
                    statut = random.choice(['EXPEDIEE', 'CONFIRMEE'])

                remise_g = decimal.Decimal('0')
                if client.segment == 'GRAND':
                    remise_g = decimal.Decimal(str(random.choice([5, 8, 10, 12, 15])))
                elif client.segment == 'PME' and random.random() < 0.3:
                    remise_g = decimal.Decimal(str(random.choice([3, 5, 7])))

                numero = f"CMD-{cmd_date.year}-{cmd_counter:05d}"
                cmd_counter += 1

                liv_prevue = cmd_date + timedelta(days=random.randint(3, 14)) if statut != 'ANNULEE' else None

                cmd = Commande.objects.create(
                    numero=numero,
                    client=client,
                    vendeur=vendeur,
                    date_commande=cmd_date,
                    date_livraison_prevue=liv_prevue,
                    statut=statut,
                    mode_paiement=random.choice(paiements),
                    remise_globale=remise_g,
                )

                # Lignes : 1 à 5 produits
                nb_lignes = random.choices([1, 2, 3, 4, 5], weights=[35, 30, 20, 10, 5])[0]
                produits_choisis = random.sample(produit_objs, min(nb_lignes, len(produit_objs)))

                for produit in produits_choisis:
                    # B2C achète en petites quantités, B2B en plus grandes
                    if client.segment == 'B2C':
                        qte = random.choices([1, 2, 3], weights=[70, 20, 10])[0]
                    elif client.segment in ('PME', 'GRAND'):
                        qte = random.choices([1, 2, 5, 10, 20], weights=[30, 25, 25, 15, 5])[0]
                    else:
                        qte = random.randint(1, 8)

                    # Légère variation de prix autour du tarif catalogue (±5%)
                    prix_catalogue = produit.prix_unitaire
                    variation = decimal.Decimal(str(round(random.uniform(-0.05, 0.05), 3)))
                    prix_ligne = (prix_catalogue * (1 + variation)).quantize(decimal.Decimal('0.01'))

                    remise_l = decimal.Decimal('0')
                    if client.segment == 'GRAND' and random.random() < 0.4:
                        remise_l = decimal.Decimal(str(random.choice([2, 3, 5])))

                    LigneCommande.objects.create(
                        commande=cmd,
                        produit=produit,
                        quantite=qte,
                        prix_unitaire_ht=prix_ligne,
                        remise_ligne=remise_l,
                    )

                if statut == 'LIVREE':
                    commandes_a_retour.append(cmd)

        # ── Retours (~6% des commandes livrées) ──────────────────────────
        self.stdout.write("Génération des retours (~6 %)…")
        motifs = ['DEFAUT', 'ERREUR', 'INSATISF', 'DOUBLON', 'DELAI', 'AUTRE']
        motifs_poids = [30, 20, 25, 10, 10, 5]
        nb_retours = int(len(commandes_a_retour) * 0.06)
        pour_retour = random.sample(commandes_a_retour, min(nb_retours, len(commandes_a_retour)))

        for cmd in pour_retour:
            delai = random.randint(7, 45)
            date_retour = cmd.date_commande + timedelta(days=delai)
            if date_retour > today:
                date_retour = today
            montant = decimal.Decimal(str(round(random.uniform(20, 500), 2)))
            Retour.objects.create(
                commande=cmd,
                date_retour=date_retour,
                motif=random.choices(motifs, weights=motifs_poids)[0],
                montant_rembourse=montant,
                traite=random.random() < 0.85,
            )

        # ── Récap ─────────────────────────────────────────────────────────
        self.stdout.write(self.style.SUCCESS("\n✓ Seed terminé :"))
        self.stdout.write(f"  {Region.objects.count():>5}  régions")
        self.stdout.write(f"  {Categorie.objects.count():>5}  catégories")
        self.stdout.write(f"  {Produit.objects.count():>5}  produits")
        self.stdout.write(f"  {Vendeur.objects.count():>5}  vendeurs")
        self.stdout.write(f"  {Client.objects.count():>5}  clients")
        self.stdout.write(f"  {Commande.objects.count():>5}  commandes")
        self.stdout.write(f"  {LigneCommande.objects.count():>5}  lignes de commande")
        self.stdout.write(f"  {Retour.objects.count():>5}  retours")

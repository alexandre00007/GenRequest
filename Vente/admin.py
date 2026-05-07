from django.contrib import admin
from .models import Categorie, Produit, Region, Vendeur, Client, Commande, LigneCommande, Retour


class LigneInline(admin.TabularInline):
    model = LigneCommande
    extra = 0
    readonly_fields = ('montant_ht',)


class RetourInline(admin.TabularInline):
    model = Retour
    extra = 0


@admin.register(Commande)
class CommandeAdmin(admin.ModelAdmin):
    list_display = ('numero', 'client', 'vendeur', 'date_commande', 'statut', 'mode_paiement', 'remise_globale')
    list_filter = ('statut', 'mode_paiement', 'date_commande')
    search_fields = ('numero', 'client__nom')
    inlines = [LigneInline, RetourInline]
    date_hierarchy = 'date_commande'


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('nom', 'segment', 'ville', 'region', 'vendeur_attitré', 'date_creation')
    list_filter = ('segment', 'region')
    search_fields = ('nom', 'email')


@admin.register(Produit)
class ProduitAdmin(admin.ModelAdmin):
    list_display = ('reference', 'nom', 'categorie', 'prix_unitaire', 'cout_achat', 'stock', 'actif')
    list_filter = ('categorie', 'actif')
    search_fields = ('reference', 'nom')


@admin.register(Vendeur)
class VendeurAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'region', 'objectif_mensuel', 'date_embauche', 'actif')
    list_filter = ('region', 'actif')


admin.register(Categorie)(admin.ModelAdmin)
admin.register(Region)(admin.ModelAdmin)
admin.register(LigneCommande)(admin.ModelAdmin)
admin.register(Retour)(admin.ModelAdmin)

# Register your models here.
from django.contrib import admin
from .models import Author, Book, DatabaseSchema, QueryHistory

@admin.register(DatabaseSchema)
class DatabaseSchemaAdmin(admin.ModelAdmin):
    list_display = ('name', 'dialect', 'created_at')

@admin.register(QueryHistory)
class QueryHistoryAdmin(admin.ModelAdmin):
    list_display = ('query_type', 'prompt_utilisateur', 'execution_time', 'is_helpful', 'created_at')
    list_filter = ('query_type', 'is_helpful')

@admin.register(Author)
class AuthorAdmin(admin.ModelAdmin):
    list_display = ('name',)

@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ('title', 'author')
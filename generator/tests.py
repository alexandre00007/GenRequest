from django.test import TestCase, Client
from django.urls import reverse

from .models import Author, Book, QueryHistory
from .generator.executor import generate_project_schema_context


class IndexViewTest(TestCase):
    def test_index_returns_200(self):
        response = self.client.get(reverse('index'))
        self.assertEqual(response.status_code, 200)

    def test_index_context_has_schemas_and_history(self):
        response = self.client.get(reverse('index'))
        self.assertIn('schemas', response.context)
        self.assertIn('history', response.context)


class VoteQueryTest(TestCase):
    def setUp(self):
        self.entry = QueryHistory.objects.create(
            prompt_utilisateur="test",
            requete_generee="Author.objects.all()",
            query_type="Django ORM",
        )

    def test_vote_up(self):
        response = self.client.post(
            reverse('vote_query', args=[self.entry.id]),
            {'vote': 'up'},
        )
        self.assertEqual(response.status_code, 200)
        self.entry.refresh_from_db()
        self.assertTrue(self.entry.is_helpful)

    def test_vote_down(self):
        self.client.post(reverse('vote_query', args=[self.entry.id]), {'vote': 'down'})
        self.entry.refresh_from_db()
        self.assertFalse(self.entry.is_helpful)

    def test_vote_get_rejected(self):
        response = self.client.get(reverse('vote_query', args=[self.entry.id]))
        self.assertEqual(response.status_code, 400)


class ExecuteQueryTest(TestCase):
    def setUp(self):
        author = Author.objects.create(name="Hugo")
        Book.objects.create(title="Les Misérables", author=author)

    def test_all_authors(self):
        response = self.client.post(
            reverse('execute_query'),
            {'sql_query': 'Author.objects.all()'},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['row_count'], 1)

    def test_count_returns_int(self):
        response = self.client.post(
            reverse('execute_query'),
            {'sql_query': 'Author.objects.count()'},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['rows'], [['1']])

    def test_blocked_pattern_rejected(self):
        response = self.client.post(
            reverse('execute_query'),
            {'sql_query': 'Author.objects.all() # __import__("os")'},
        )
        self.assertEqual(response.status_code, 400)

    def test_no_model_name_rejected(self):
        response = self.client.post(
            reverse('execute_query'),
            {'sql_query': 'list(range(5))'},
        )
        self.assertEqual(response.status_code, 400)

    def test_empty_query_rejected(self):
        response = self.client.post(reverse('execute_query'), {'sql_query': ''})
        self.assertEqual(response.status_code, 400)

    def test_get_rejected(self):
        response = self.client.get(reverse('execute_query'))
        self.assertEqual(response.status_code, 405)


class SchemaContextTest(TestCase):
    def test_contains_project_models(self):
        context = generate_project_schema_context()
        self.assertIn('Author', context)
        self.assertIn('Book', context)

    def test_excludes_django_internals(self):
        context = generate_project_schema_context()
        self.assertNotIn('LogEntry', context)  # django.contrib.admin
        self.assertNotIn('Permission', context)  # django.contrib.auth

    def test_caching(self):
        # Two calls must return the exact same object (lru_cache hit)
        self.assertIs(
            generate_project_schema_context(),
            generate_project_schema_context(),
        )

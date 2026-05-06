from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('stream-generation/', views.stream_query_generation, name='stream_generation'),
    path('execute-query/', views.execute_generated_query, name='execute_query'),
    path('analyze-results/', views.analyze_results, name='analyze_results'),
    path('vote/<int:query_id>/', views.vote_query, name='vote_query'),
]
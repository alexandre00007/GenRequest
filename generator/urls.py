from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('stream-generation/', views.stream_query_generation, name='stream_generation'),
    path('execute-query/', views.execute_generated_query, name='execute_query'),
    path('chat/', views.chat_with_data, name='chat_with_data'),
    path('vote/<int:query_id>/', views.vote_query, name='vote_query'),
    # Model picker API
    path('api/models/', views.list_project_models, name='list_project_models'),
    # Auto-fix hallucinations
    path('fix-query/', views.stream_fix_query, name='fix_query'),
    # Session persistence
    path('sessions/', views.list_chat_sessions, name='list_chat_sessions'),
    path('sessions/save/', views.save_chat_session, name='save_chat_session'),
    path('sessions/<int:session_id>/', views.load_chat_session, name='load_chat_session'),
    path('sessions/<int:session_id>/delete/', views.delete_chat_session, name='delete_chat_session'),
]
from django.urls import path

from . import campanhas, recebimento, views, whatsapp_conexao

app_name = 'notificacoes'

urlpatterns = [
    path('whatsapp/', whatsapp_conexao.conexao, name='conexao'),
    path('webhook/<uuid:codigo>/<str:token>/', recebimento.webhook, name='webhook'),
    path('conversas/', recebimento.conversas, name='conversas'),
    path('conversas/<str:telefone>/', recebimento.conversa, name='conversa'),
    path('whatsapp/desconectar/', whatsapp_conexao.desconectar, name='desconectar'),
    path('campanhas/', campanhas.campanhas, name='campanhas'),
    path('api/novidades/', views.novidades, name='novidades'),
    path('', views.lista, name='lista'),
    path('<int:pk>/reenviar/', views.reenviar, name='reenviar'),
    path('processar/', views.processar_agora, name='processar'),
    path('testar/', views.testar, name='testar'),
]

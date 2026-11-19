from django.urls import path

from . import campanhas, views, whatsapp_conexao

app_name = 'notificacoes'

urlpatterns = [
    path('whatsapp/', whatsapp_conexao.conexao, name='conexao'),
    path('whatsapp/desconectar/', whatsapp_conexao.desconectar, name='desconectar'),
    path('campanhas/', campanhas.campanhas, name='campanhas'),
    path('', views.lista, name='lista'),
    path('<int:pk>/reenviar/', views.reenviar, name='reenviar'),
    path('processar/', views.processar_agora, name='processar'),
    path('testar/', views.testar, name='testar'),
]

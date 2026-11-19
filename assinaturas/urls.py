from django.urls import path

from . import views

app_name = 'assinaturas'

urlpatterns = [
    path('cadastro/', views.cadastro, name='cadastro'),
    path('minha/', views.minha, name='minha'),
    path('bloqueado/', views.bloqueado, name='bloqueado'),
    path('painel/', views.painel, name='painel'),
    path('painel/acao/', views.acao, name='acao'),
    path('planos/novo/', views.plano_form, name='plano_novo'),
    path('planos/<int:pk>/', views.plano_form, name='plano_editar'),
]

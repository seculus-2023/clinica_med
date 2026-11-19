from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

app_name = 'contas'

urlpatterns = [
    path('entrar/', views.Entrar.as_view(), name='login'),
    path('sair/', LogoutView.as_view(), name='logout'),
    path('clinica/', views.selecionar_clinica, name='selecionar_clinica'),
    path('minha-conta/', views.minha_conta, name='minha_conta'),
    path('clinicas/', views.clinicas, name='clinicas'),
    path('clinicas/nova/', views.clinica_form, name='clinica_nova'),
    path('clinicas/<int:pk>/', views.clinica_form, name='clinica_editar'),
    path('configuracoes/', views.configuracoes, name='configuracoes'),
    path('usuarios/', views.usuarios, name='usuarios'),
    path('usuarios/novo/', views.usuario_form, name='usuario_novo'),
    path('usuarios/<int:pk>/', views.usuario_form, name='usuario_editar'),
    path('perfis/', views.perfis, name='perfis'),
    path('perfis/novo/', views.perfil_form, name='perfil_novo'),
    path('perfis/<int:pk>/', views.perfil_form, name='perfil_editar'),
    path('lembretes/<int:pk>/concluir/', views.lembrete_concluir, name='lembrete_concluir'),
] + views.LembreteCrud.urls('lembretes')

from django.urls import path

from . import relatorios, views

app_name = 'painel'

urlpatterns = [
    path('', views.inicio, name='inicio'),
    path('dashboard/', views.dashboard, name='dashboard'),
    path('busca/', views.busca, name='busca'),
    path('relatorios/', relatorios.relatorios, name='relatorios'),
]

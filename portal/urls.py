from django.urls import path

from . import views

app_name = 'portal'

urlpatterns = [
    path('<uuid:codigo>/', views.inicio, name='inicio'),
    path('<uuid:codigo>/manifest.webmanifest', views.manifest, name='manifest'),
    path('<uuid:codigo>/entrar/', views.entrar, name='entrar'),
    path('<uuid:codigo>/sair/', views.sair, name='sair'),
    path('<uuid:codigo>/termo/', views.termo, name='termo'),
    path('<uuid:codigo>/agendar/', views.agendar, name='agendar'),
    path('<uuid:codigo>/consulta/<int:pk>/confirmar/', views.confirmar, name='confirmar'),
    path('<uuid:codigo>/consulta/<int:pk>/cancelar/', views.cancelar, name='cancelar'),
    path('<uuid:codigo>/medicacoes/', views.medicacoes, name='medicacoes'),
    path('<uuid:codigo>/medicoes/', views.medicoes, name='medicoes'),
    path('<uuid:codigo>/avisos/', views.avisos, name='avisos'),
    path('<uuid:codigo>/mais/', views.mais, name='mais'),
    path('<uuid:codigo>/documento/<int:pk>/', views.documento, name='documento'),
    path('<uuid:codigo>/assinado/<int:pk>/', views.assinado, name='assinado'),
    path('<uuid:codigo>/exame/<int:pk>/', views.exame, name='exame'),
    path('<uuid:codigo>/recibo/<int:pk>/', views.recibo, name='recibo'),
]

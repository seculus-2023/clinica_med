from django.urls import path

from . import views

app_name = 'areamedica'

urlpatterns = [
    path('', views.agenda, name='agenda'),
    path('entrar/', views.Entrar.as_view(), name='entrar'),
    path('sair/', views.sair, name='sair'),
    path('clinica/', views.escolher_clinica, name='clinica'),
    path('manifest.webmanifest', views.manifest, name='manifest'),
    path('atendimento/<int:pk>/', views.paciente, name='paciente'),
    path('atendimento/<int:pk>/status/', views.status, name='status'),
    path('atendimento/<int:pk>/chamar/', views.chamar, name='chamar'),
]

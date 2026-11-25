from django.urls import path

from . import views

app_name = 'ouvidoria'

urlpatterns = [
    path('', views.painel, name='painel'),
    path('nova/', views.nova, name='nova'),
    path('<int:pk>/', views.detalhe, name='detalhe'),
    path('<int:pk>/comprovante/', views.comprovante, name='comprovante'),
    path('<int:pk>/acao/<slug:nome>/', views.acao, name='acao'),
    path('configurar/', views.configurar, name='configurar'),
    path('p/<uuid:codigo>/', views.publico, name='publico'),
    path('p/<uuid:codigo>/registrada/', views.registrada, name='registrada'),
    path('p/<uuid:codigo>/consultar/', views.consultar, name='consultar'),
    path('acompanhar/<uuid:token>/', views.acompanhar, name='acompanhar'),
]
urlpatterns += views.SetorCrud.urls('setores')

from django.urls import path

from . import views

app_name = 'callcenter'

urlpatterns = [
    path('', views.fila, name='fila'),
    path('<int:pk>/atender/', views.atender, name='atender'),
]
urlpatterns += views.ContatoCrud.urls('contatos')

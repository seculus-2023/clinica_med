from django.urls import path

from . import views

app_name = 'portal'

urlpatterns = [
    path('<uuid:codigo>/', views.inicio, name='inicio'),
    path('<uuid:codigo>/entrar/', views.entrar, name='entrar'),
    path('<uuid:codigo>/sair/', views.sair, name='sair'),
    path('<uuid:codigo>/documento/<int:pk>/', views.documento, name='documento'),
    path('<uuid:codigo>/assinado/<int:pk>/', views.assinado, name='assinado'),
    path('<uuid:codigo>/exame/<int:pk>/', views.exame, name='exame'),
    path('<uuid:codigo>/recibo/<int:pk>/', views.recibo, name='recibo'),
]

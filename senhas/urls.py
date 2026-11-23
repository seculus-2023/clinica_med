from django.urls import path

from . import views

app_name = 'senhas'

urlpatterns = [
    path('', views.painel, name='painel'),
    path('guiche/sair/', views.sair_guiche, name='sair_guiche'),
    path('guiche/<int:pk>/assumir/', views.assumir_guiche, name='assumir_guiche'),
    path('guiche/<int:pk>/liberar/', views.liberar_guiche, name='liberar_guiche'),
    path('emitir/', views.emitir, name='emitir'),
    path('proxima/', views.chamar, name='proxima'),
    path('<int:pk>/chamar/', views.chamar, name='chamar'),
    path('<int:pk>/rechamar/', views.rechamar, name='rechamar'),
    path('<int:pk>/acao/<slug:nome>/', views.acao, name='acao'),
    path('<int:pk>/ticket/', views.ticket, name='ticket'),
    path('agendamento/<int:pk>/emitir/', views.agendamento_emitir, name='agendamento_emitir'),
    path('agendamento/<int:pk>/chamar/', views.agendamento_chamar, name='agendamento_chamar'),
    path('configurar/', views.configurar, name='configurar'),
    path('configurar/novo-link/', views.novo_link, name='novo_link'),
    path('tv/<uuid:token>/', views.tv, name='tv'),
    path('tv/<uuid:token>/dados/', views.tv_dados, name='tv_dados'),
]
urlpatterns += views.ServicoCrud.urls('servicos')
urlpatterns += views.PontoCrud.urls('guiches')

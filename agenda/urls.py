from django.urls import path

from . import publico, views

app_name = 'agenda'

urlpatterns = [
    path('', views.calendario, name='calendario'),
    path('eventos/', views.eventos, name='eventos'),
    path('dia/', views.dia, name='dia'),
    path('marcar/', views.marcar, name='marcar'),
    path('grade/', views.grade, name='grade'),
    path('online/<uuid:codigo>/grade/', publico.grade_publica, name='grade_publica'),
    path('novo/', views.novo, name='novo'),
    path('<int:pk>/', views.detalhe, name='detalhe'),
    path('<int:pk>/editar/', views.editar, name='editar'),
    path('<int:pk>/status/', views.alterar_status, name='status'),
    path('<int:pk>/reenviar/', views.reenviar, name='reenviar'),
    path('<int:pk>/lancar/', views.lancar_financeiro, name='lancar'),
    path('c/<uuid:token>/', views.confirmar_publico, name='confirmar_publico'),
    path('online/<uuid:codigo>/', publico.online, name='online'),
    path('checkin/<uuid:token>/', publico.checkin, name='checkin'),
    path('avaliar/<uuid:token>/', publico.avaliar, name='avaliar'),
    path('tele/<uuid:token>/', publico.teleconsulta, name='teleconsulta'),
    path('espera/<int:pk>/agendar/', views.espera_agendar, name='espera_agendar'),
    path('api/pacotes/', views.pacotes_paciente, name='api_pacotes'),
    path('pacotes/novo/', views.pacote_novo, name='pacote_novo'),
    path('pacotes/<int:pk>/', views.pacote_detalhe, name='pacote_detalhe'),
]
# a rota "novo" acima tem precedência sobre a genérica do Crud
urlpatterns += views.PacoteCrud.urls('pacotes')
urlpatterns += views.BloqueioCrud.urls('bloqueios')
urlpatterns += views.EsperaCrud.urls('espera')
urlpatterns += views.RecursoCrud.urls('recursos')

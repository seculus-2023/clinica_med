from django.urls import path

from . import views

app_name = 'prontuario'

urlpatterns = [
    path('consulta/', views.consulta, name='consulta'),
    path('consulta/<int:pk>/', views.consulta_paciente, name='consulta_paciente'),
    path('paciente/<int:pk>/', views.paciente, name='paciente'),
    path('paciente/<int:pk>/historico/', views.historico, name='historico'),
    path('paciente/<int:pk>/atendimento/novo/', views.atendimento_novo, name='atendimento_novo'),
    path('paciente/<int:pk>/anexo/novo/', views.anexo_novo, name='anexo_novo'),
    path('paciente/<int:pk>/imprimir/', views.imprimir, name='imprimir'),
    path('paciente/<int:pk>/auditoria/', views.auditoria, name='auditoria'),
    path('atendimento/<int:pk>/', views.atendimento, name='atendimento'),
    path('atendimento/<int:pk>/editar/', views.atendimento_editar, name='atendimento_editar'),
    path('atendimento/<int:pk>/finalizar/', views.atendimento_finalizar, name='atendimento_finalizar'),
    path('agendamento/<int:agendamento_pk>/iniciar/', views.iniciar, name='iniciar'),
    path('anexo/<int:pk>/arquivo/', views.anexo_arquivo, name='anexo_arquivo'),
    path('agendamento/<int:agendamento_pk>/gravacao/', views.gravacao, name='gravacao'),
    path('paciente/<int:pk>/resultados/', views.resultados_lancar, name='resultados_lancar'),
    path('modelos/padrao/', views.modelos_padrao, name='modelos_padrao'),
    path('exames/padrao/', views.exames_padrao, name='exames_padrao'),
]
urlpatterns += views.ModeloCrud.urls('modelos')
urlpatterns += views.ExameCrud.urls('exames')

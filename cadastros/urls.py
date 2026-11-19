from django.urls import path

from . import views

app_name = 'cadastros'

urlpatterns = [
    path('pacientes/<int:pk>/ficha/', views.paciente_ficha, name='paciente_ficha'),
    path('medicamentos/importar/', views.importar_cmed, name='importar_cmed'),
    path('procedimentos/importar/', views.importar_procedimentos, name='importar_procedimentos'),
    path('cid/importar/', views.importar_cid, name='importar_cid'),
    path('api/medicamentos/', views.api_medicamentos, name='api_medicamentos'),
    path('api/procedimentos/', views.api_procedimentos, name='api_procedimentos'),
    path('api/cid/', views.api_cid, name='api_cid'),
    path('api/verificar-prescricao/', views.api_verificar_prescricao, name='api_verificar_prescricao'),
    path('interacoes/importar/', views.interacao_importar, name='interacao_importar'),
    path('medicamentos/<int:pk>/bula/', views.medicamento_bula, name='medicamento_bula'),
]
urlpatterns += views.PacienteCrud.urls('pacientes')
urlpatterns += views.MedicoCrud.urls('medicos')
urlpatterns += views.EspecialidadeCrud.urls('especialidades')
urlpatterns += views.MedicamentoCrud.urls('medicamentos')
urlpatterns += views.ProcedimentoCrud.urls('procedimentos')
urlpatterns += views.CidCrud.urls('cid')
urlpatterns += views.TipoAtendimentoCrud.urls('tabela-precos')
urlpatterns += views.HorarioCrud.urls('horarios')
urlpatterns += views.InteracaoCrud.urls('interacoes')

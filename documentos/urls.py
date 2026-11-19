from django.urls import path

from . import assinatura, views

app_name = 'documentos'

urlpatterns = [
    path('assinar/', assinatura.assinar, name='assinar'),
    path('assinar/iniciar/', assinatura.iniciar, name='assinar_iniciar'),
    path('assinar/gravar/', assinatura.gravar, name='assinar_gravar'),
    path('assinados/', assinatura.assinados, name='assinados'),
    path('assinados/<int:pk>/arquivo/', assinatura.arquivo_assinado, name='assinado_arquivo'),
    path('verificar/', assinatura.verificar, name='verificar'),
    path('medico/<int:pk>/assinatura/', assinatura.imagem_assinatura, name='medico_assinatura'),
    path('documentos/novo/', views.documento_form, name='documento_novo'),
    path('documentos/<int:pk>/editar/', views.documento_form, name='documento_editar'),
    path('documentos/<int:pk>/imprimir/', views.imprimir, name='imprimir'),
    path('api/modelo/<int:pk>/', views.api_modelo, name='api_modelo'),
    path('api/alergias/<int:pk>/', views.api_alergias, name='api_alergias'),
]
urlpatterns += views.DocumentoCrud.urls('documentos')
urlpatterns += views.ModeloCrud.urls('modelos')

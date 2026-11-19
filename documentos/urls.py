from django.urls import path

from . import views

app_name = 'documentos'

urlpatterns = [
    path('documentos/novo/', views.documento_form, name='documento_novo'),
    path('documentos/<int:pk>/editar/', views.documento_form, name='documento_editar'),
    path('documentos/<int:pk>/imprimir/', views.imprimir, name='imprimir'),
    path('api/modelo/<int:pk>/', views.api_modelo, name='api_modelo'),
    path('api/alergias/<int:pk>/', views.api_alergias, name='api_alergias'),
]
urlpatterns += views.DocumentoCrud.urls('documentos')
urlpatterns += views.ModeloCrud.urls('modelos')

from django.urls import path

from . import views

app_name = 'convenios'

urlpatterns = [
    path('guias/', views.guias, name='guias'),
    path('guias/nova/', views.guia_form, name='guia_nova'),
    path('guias/<int:pk>/', views.guia_form, name='guia_editar'),
    path('guias/<int:pk>/imprimir/', views.guia_imprimir, name='guia_imprimir'),
    path('lotes/', views.lotes, name='lotes'),
    path('lotes/<int:pk>/', views.lote, name='lote'),
    path('lotes/<int:pk>/acao/', views.lote_acao, name='lote_acao'),
    path('glosas/', views.glosas, name='glosas'),
    path('api/paciente/<int:pk>/', views.api_paciente, name='api_paciente'),
    path('api/planos/', views.api_planos, name='api_planos'),
]
urlpatterns += views.OperadoraCrud.urls('operadoras')
urlpatterns += views.PlanoCrud.urls('planos')
urlpatterns += views.PrecoCrud.urls('precos')

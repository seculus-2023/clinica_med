from django.urls import path

from . import conciliacao, views

app_name = 'financeiro'

urlpatterns = [
    path('conciliacao/', conciliacao.conciliacao_inicio, name='conciliacao_inicio'),
    path('conciliacao/<int:pk>/', conciliacao.conciliacao, name='conciliacao'),
    path('conciliacao/transacao/<int:pk>/', conciliacao.acao_transacao, name='transacao_acao'),
    path('', views.lancamentos, name='lancamentos'),
    path('fluxo-de-caixa/', views.fluxo_caixa, name='fluxo'),
    path('lancamentos/<int:pk>/baixar/', views.baixar, name='baixar'),
]
urlpatterns += views.LancamentoCrud.urls('lancamentos')
urlpatterns += views.CategoriaCrud.urls('categorias')
urlpatterns += conciliacao.ContaCrud.urls('contas')

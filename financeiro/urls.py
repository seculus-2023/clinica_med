from django.urls import path

from . import conciliacao, gestao, views

app_name = 'financeiro'

urlpatterns = [
    path('conciliacao/', conciliacao.conciliacao_inicio, name='conciliacao_inicio'),
    path('conciliacao/<int:pk>/', conciliacao.conciliacao, name='conciliacao'),
    path('conciliacao/transacao/<int:pk>/', conciliacao.acao_transacao, name='transacao_acao'),
    path('', views.lancamentos, name='lancamentos'),
    path('caixa/', gestao.caixa, name='caixa'),
    path('caixa/<int:pk>/', gestao.caixa_detalhe, name='caixa_detalhe'),
    path('lancamentos/<int:pk>/recibo/', gestao.recibo, name='recibo'),
    path('orcamentos/', gestao.orcamentos, name='orcamentos'),
    path('orcamentos/novo/', gestao.orcamento_form, name='orcamento_novo'),
    path('orcamentos/<int:pk>/', gestao.orcamento_form, name='orcamento_editar'),
    path('orcamentos/<int:pk>/imprimir/', gestao.orcamento_imprimir, name='orcamento_imprimir'),
    path('orcamentos/<int:pk>/aprovar/', gestao.orcamento_aprovar, name='orcamento_aprovar'),
    path('dre/', gestao.dre, name='dre'),
    path('fluxo-de-caixa/', views.fluxo_caixa, name='fluxo'),
    path('lancamentos/<int:pk>/baixar/', views.baixar, name='baixar'),
]
urlpatterns += views.LancamentoCrud.urls('lancamentos')
urlpatterns += views.CategoriaCrud.urls('categorias')
urlpatterns += conciliacao.ContaCrud.urls('contas')

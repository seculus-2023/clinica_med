from django.urls import path

from . import compras, views

app_name = 'estoque'

urlpatterns = [
    path('produtos/<int:pk>/kardex/', views.kardex, name='produto_kardex'),
    path('pedidos/', compras.pedidos, name='pedidos'),
    path('pedidos/novo/', compras.pedido_form, name='pedido_novo'),
    path('pedidos/<int:pk>/', compras.pedido, name='pedido'),
    path('pedidos/<int:pk>/editar/', compras.pedido_form, name='pedido_editar'),
    path('pedidos/<int:pk>/acao/', compras.pedido_acao, name='pedido_acao'),
    path('inventarios/', compras.inventarios, name='inventarios'),
    path('inventarios/<int:pk>/', compras.inventario, name='inventario'),
    path('lotes/', compras.lotes, name='lotes'),
]
urlpatterns += views.ProdutoCrud.urls('produtos')
urlpatterns += views.MovimentoCrud.urls('movimentos')
urlpatterns += views.InsumoCrud.urls('insumos')
urlpatterns += compras.FornecedorCrud.urls('fornecedores')

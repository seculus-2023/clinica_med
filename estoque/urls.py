from django.urls import path

from . import views

app_name = 'estoque'

urlpatterns = [
    path('produtos/<int:pk>/kardex/', views.kardex, name='produto_kardex'),
]
urlpatterns += views.ProdutoCrud.urls('produtos')
urlpatterns += views.MovimentoCrud.urls('movimentos')
urlpatterns += views.InsumoCrud.urls('insumos')

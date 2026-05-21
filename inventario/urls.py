# inventario/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # Kardex
    path('kardex/',          views.lista_kardex,      name='kardex-lista'),
    path('kardex/nuevo/',    views.crear_kardex,       name='kardex-crear'),

    # Stock
    path('reposicion/',      views.reposicion_stock,   name='inventario-reposicion'),
    path('resumen/',         views.resumen_inventario, name='inventario-resumen'),

    # Pedidos
    path('pedidos/crear/',                     views.crear_pedido,    name='crear_pedido'),
    path('pedidos/cliente/<int:cliente_id>/',  views.pedidos_cliente, name='pedidos_cliente'),
    path('pedidos/artesano/<int:artesano_id>/',views.pedidos_artesano,name='pedidos_artesano'),
    path('pedido/estado/',                     views.cambiar_estado,  name='cambiar_estado'),
    
    
]
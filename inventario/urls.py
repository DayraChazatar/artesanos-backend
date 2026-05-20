# inventario/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # Lista y creación de movimientos manuales
    path('kardex/',          views.lista_kardex,        name='kardex-lista'),
    path('kardex/nuevo/',    views.crear_kardex,         name='kardex-crear'),

    # Botón +Stock desde tabla de Productos
    path('reposicion/',      views.reposicion_stock,     name='inventario-reposicion'),


    # Tarjetas resumen
    path('resumen/',         views.resumen_inventario,   name='inventario-resumen'),
    
    # Crear pedido desde el carrito del cliente
    path('pedidos/crear/',                    views.crear_pedido,     name='crear_pedido'),
 
    # Listar pedidos por actor
    path('pedidos/cliente/<int:cliente_id>/', views.pedidos_cliente,  name='pedidos_cliente'),
    path('pedidos/artesano/<int:artesano_id>/',views.pedidos_artesano, name='pedidos_artesano'),
 
    # Cambiar estado (usado por el artesano y por el cliente para cancelar)
    path('pedido/estado/',                    views.cambiar_estado,   name='cambiar_estado'),
]
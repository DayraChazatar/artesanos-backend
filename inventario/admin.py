from django.contrib import admin
from .models import Pedido, DetallePedido, Kardex

@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ['codigo', 'cliente', 'artesano', 'estado', 'total', 'fecha']
    list_filter = ['estado']
    search_fields = ['codigo', 'cliente__nombre']
    ordering = ['-fecha']

@admin.register(DetallePedido)
class DetallePedidoAdmin(admin.ModelAdmin):
    list_display = ['pedido', 'producto', 'cantidad', 'precio']

@admin.register(Kardex)
class KardexAdmin(admin.ModelAdmin):
    list_display = ['fecha', 'producto', 'tipo', 'subtipo', 'origen', 'cantidad', 'stock_resultante', 'creado_por']
    list_filter = ['tipo', 'subtipo', 'origen']
    search_fields = ['producto__nombre', 'pedido_ref']
    ordering = ['-creado_en']

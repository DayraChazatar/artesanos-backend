from django.contrib import admin
from .models import Usuario, Categoria, Producto, Kardex

@admin.register(Kardex)
class KardexAdmin(admin.ModelAdmin):
    list_display = ['producto', 'tipo', 'cantidad', 'fecha', 'nota']
    list_filter = ['tipo', 'fecha']

@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'cantidad', 'stock_minimo', 'stock_maximo']

@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'descripcion']

@admin.register(Usuario)
class UsuarioAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'correo', 'tipo']
from django.contrib import admin
from .models import Usuario, Categoria, Producto, Notificacion, ContactoIniciado, Favorito, Resena, PasswordResetToken

@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'artesano', 'categoria', 'cantidad', 'stock_minimo', 'stock_maximo', 'visible']
    list_filter = ['visible', 'categoria']
    search_fields = ['nombre', 'codigo_barra']

@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'descripcion', 'cantidad_artesanos']

    def cantidad_artesanos(self, obj):
        return obj.artesanos.count()
    cantidad_artesanos.short_description = 'Artesanos en esta categoría'

@admin.register(Usuario)
class UsuarioAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'correo', 'tipo', 'telefono', 'categoria']
    list_filter = ['tipo', 'categoria']
    search_fields = ['nombre', 'correo']

@admin.register(Notificacion)
class NotificacionAdmin(admin.ModelAdmin):
    list_display = ['titulo', 'tipo', 'leida', 'fecha']
    list_filter = ['tipo', 'leida']
    ordering = ['-fecha']

@admin.register(ContactoIniciado)
class ContactoIniciadoAdmin(admin.ModelAdmin):
    list_display = ['artesano', 'cliente', 'producto', 'fecha']
    search_fields = ['artesano__nombre', 'cliente__nombre']
    ordering = ['-fecha']

@admin.register(Favorito)
class FavoritoAdmin(admin.ModelAdmin):
    list_display = ['cliente', 'producto', 'creado_en']
    search_fields = ['cliente__nombre', 'producto__nombre']
    ordering = ['-creado_en']

@admin.register(Resena)
class ResenaAdmin(admin.ModelAdmin):
    list_display = ['cliente', 'producto', 'calificacion', 'creado_en']
    list_filter = ['calificacion']
    search_fields = ['cliente__nombre', 'producto__nombre', 'comentario']
    ordering = ['-creado_en']

@admin.register(PasswordResetToken)
class PasswordResetTokenAdmin(admin.ModelAdmin):
    list_display = ['usuario', 'usado', 'creado_en']
    list_filter = ['usado']
    search_fields = ['usuario__correo']
    ordering = ['-creado_en']
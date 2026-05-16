from rest_framework import serializers
from django.contrib.auth.hashers import make_password
from .models import Usuario, Categoria, Producto, Kardex
 
 
class UsuarioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Usuario
        fields = '__all__'
 
    def create(self, validated_data):
        validated_data['password'] = make_password(validated_data['password'])
        return super().create(validated_data)
 
    def update(self, instance, validated_data):
        if 'password' in validated_data:
            validated_data['password'] = make_password(validated_data['password'])
        return super().update(instance, validated_data)
 
 
class CategoriaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Categoria
        fields = '__all__'
 
 
class ProductoSerializer(serializers.ModelSerializer):
    categoria_nombre = serializers.CharField(source='categoria.nombre', read_only=True)
    precio_con_iva   = serializers.FloatField(read_only=True)
    precio_final     = serializers.FloatField(read_only=True)
    estado_stock     = serializers.CharField(read_only=True)
 
    class Meta:
        model = Producto
        fields = [
            'id',
            'codigo_barra',   # nuevo
            'lote',           # nuevo
            'nombre',
            'categoria',
            'categoria_nombre',
            'precio_neto',
            'iva',
            'descuento',
            'valor_descuento',
            'cantidad',
            'stock_minimo',   # nuevo
            'stock_maximo',   # nuevo
            'artesano',
            'precio_con_iva',
            'precio_final',
            'estado_stock',   # nuevo
        ]
    def validate(self, data):
        cantidad    = data.get('cantidad', 0)
        stock_min   = data.get('stock_minimo', 0)
        stock_max   = data.get('stock_maximo', 0)
        precio_neto = data.get('precio_neto', 0)

        # No negativos
        if cantidad < 0:
            raise serializers.ValidationError({'cantidad': 'La cantidad no puede ser negativa.'})
        if stock_min < 0:
            raise serializers.ValidationError({'stock_minimo': 'El stock mínimo no puede ser negativo.'})
        if stock_max < 0:
            raise serializers.ValidationError({'stock_maximo': 'El stock máximo no puede ser negativo.'})
        if precio_neto <= 0:
            raise serializers.ValidationError({'precio_neto': 'El precio neto debe ser mayor a 0.'})

        # Mínimo no mayor que máximo
        if stock_max > 0 and stock_min > stock_max:
            raise serializers.ValidationError({
                'stock_minimo': 'El stock mínimo no puede ser mayor al stock máximo.'
            })

        return data
 
 
class KardexSerializer(serializers.ModelSerializer):
    producto_nombre = serializers.CharField(source='producto.nombre', read_only=True)
 
    class Meta:
        model = Kardex
        fields = ['id', 'producto', 'producto_nombre', 'tipo', 'cantidad', 'fecha', 'nota']

from .models import Notificacion

class NotificacionSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Notificacion
        fields = ['id', 'tipo', 'titulo', 'detalle', 'leida', 'fecha', 'referencia_id', 'ruta']
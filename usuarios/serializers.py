# usuarios/serializers.py
from rest_framework import serializers
from django.contrib.auth.hashers import make_password
from .models import Usuario, Categoria, Producto, Notificacion
from inventario.models import Kardex


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
    categoria_nombre    = serializers.CharField(source='categoria.nombre', read_only=True)
    precio_con_iva      = serializers.FloatField(read_only=True)
    precio_final        = serializers.FloatField(read_only=True)
    estado_stock        = serializers.CharField(read_only=True)
    cantidad_reservada  = serializers.IntegerField(read_only=True)
    cantidad_disponible = serializers.IntegerField(read_only=True)
    artesano_nombre     = serializers.CharField(source='artesano.nombre', read_only=True)
    imagen_url          = serializers.SerializerMethodField()

    class Meta:
        model = Producto
        fields = [
            'id',
            'codigo_barra',
            'lote',
            'nombre',
            'categoria',
            'categoria_nombre',
            'precio_neto',
            'precio_pvp',
            'iva',
            'descuento',
            'valor_descuento',
            'cantidad',
            'stock_minimo',
            'stock_maximo',
            'artesano',
            'artesano_nombre',
            'precio_con_iva',
            'precio_final',
            'estado_stock',
            'cantidad_reservada',
            'cantidad_disponible',
            'imagen',
            'imagen_url',
        ]

    def get_imagen_url(self, obj):
        request = self.context.get('request')
        if obj.imagen and request:
            return request.build_absolute_uri(obj.imagen.url)
        return ''

    def validate(self, data):
        cantidad    = data.get('cantidad', 0)
        stock_min   = data.get('stock_minimo', 0)
        stock_max   = data.get('stock_maximo', 0)
        precio_neto = data.get('precio_neto', 0)

        if cantidad < 0:
            raise serializers.ValidationError({'cantidad': 'La cantidad no puede ser negativa.'})
        if stock_min < 0:
            raise serializers.ValidationError({'stock_minimo': 'El stock mínimo no puede ser negativo.'})
        if stock_max < 0:
            raise serializers.ValidationError({'stock_maximo': 'El stock máximo no puede ser negativo.'})
        if precio_neto <= 0:
            raise serializers.ValidationError({'precio_neto': 'El precio neto debe ser mayor a 0.'})
        if stock_max > 0 and stock_min > stock_max:
            raise serializers.ValidationError({
                'stock_minimo': 'El stock mínimo no puede ser mayor al stock máximo.'
            })
        return data
    
class CatalogoProductoSerializer(serializers.ModelSerializer):
    categoria_nombre    = serializers.CharField(source='categoria.nombre', read_only=True)
    cantidad_disponible = serializers.IntegerField(read_only=True)
    precio_final        = serializers.FloatField(read_only=True)
    artesano_nombre     = serializers.CharField(source='artesano.nombre', read_only=True)
    imagen_url          = serializers.SerializerMethodField()

    class Meta:
        model  = Producto
        fields = [
            'id', 'nombre', 'categoria_nombre',
            'precio_neto', 'precio_pvp', 'precio_final',
            'iva', 'descuento', 'valor_descuento',
            'cantidad_disponible',
            'artesano_nombre', 'imagen_url',
        ]

    def get_imagen_url(self, obj):
        request = self.context.get('request')
        if obj.imagen and request:
            return request.build_absolute_uri(obj.imagen.url)
        return ''


class KardexSerializer(serializers.ModelSerializer):
    producto_nombre  = serializers.CharField(source='producto.nombre', read_only=True)
    tipo_display     = serializers.CharField(source='get_tipo_display', read_only=True)
    subtipo_display  = serializers.CharField(source='get_subtipo_display', read_only=True)
    origen_display   = serializers.CharField(source='get_origen_display', read_only=True)

    class Meta:
        model  = Kardex
        fields = [
            'id',
            'producto',
            'producto_nombre',
            'pedido_ref',
            'tipo',
            'tipo_display',
            'subtipo',
            'subtipo_display',
            'origen',
            'origen_display',
            'cantidad',
            'stock_resultante',
            'precio_unitario',
            'fecha',
            'nota',
            'creado_por',
            'creado_en',
        ]
        read_only_fields = [
            'id', 'tipo', 'subtipo', 'origen',
            'stock_resultante', 'precio_unitario',
            'creado_por', 'creado_en',
        ]


class NotificacionSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Notificacion
        fields = ['id', 'tipo', 'titulo', 'detalle', 'leida', 'fecha', 'referencia_id', 'ruta']
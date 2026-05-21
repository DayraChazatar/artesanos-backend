# usuarios/serializers.py
from rest_framework import serializers
from django.contrib.auth.hashers import make_password
from .models import Usuario, Categoria, Producto, Notificacion
from inventario.models import Kardex


class UsuarioSerializer(serializers.ModelSerializer):
    foto_url        = serializers.SerializerMethodField()
    categoria_id    = serializers.SerializerMethodField()
    categoria_nombre = serializers.SerializerMethodField()

    class Meta:
        model  = Usuario
        fields = '__all__'

    def get_foto_url(self, obj):
        request = self.context.get('request')
        if obj.foto and request:
            return request.build_absolute_uri(obj.foto.url)
        return ''

    def get_categoria_id(self, obj):
        """Devuelve el id de la categoría del artesano (si existe)."""
        if obj.tipo == 'artesano' and hasattr(obj, 'categoria'):
            return obj.categoria.id
        return None

    def get_categoria_nombre(self, obj):
        """Devuelve el nombre de la categoría del artesano (si existe)."""
        if obj.tipo == 'artesano' and hasattr(obj, 'categoria'):
            return obj.categoria.nombre
        return None

    def create(self, validated_data):
        validated_data['password'] = make_password(validated_data['password'])
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if 'password' in validated_data:
            validated_data['password'] = make_password(validated_data['password'])
        return super().update(instance, validated_data)


class RegistroArtesanoSerializer(serializers.ModelSerializer):
    categoria_id = serializers.IntegerField(write_only=True)

    class Meta:
        model  = Usuario
        fields = [
            'id', 'nombre', 'correo', 'password',
            'telefono', 'especialidad', 'biografia', 'foto',
            'tipo', 'categoria_id',
        ]
        extra_kwargs = {
            'password':     {'write_only': True},
            'tipo':         {'required': False, 'default': 'artesano'},
            'especialidad': {'required': False, 'default': ''},
            'telefono':     {'required': False, 'default': ''},
            'biografia':    {'required': False, 'default': ''},
            'foto':         {'required': False, 'default': None},
        }

    def validate_categoria_id(self, value):
        try:
            cat = Categoria.objects.get(pk=value)
        except Categoria.DoesNotExist:
            raise serializers.ValidationError('La categoría seleccionada no existe.')
        if cat.artesano is not None:
            raise serializers.ValidationError(
                'Esa categoría ya está asignada a otro artesano. '
                'Contacta al administrador para crear una nueva.'
            )
        return value

    def create(self, validated_data):
        categoria_id = validated_data.pop('categoria_id')
        validated_data['password'] = make_password(validated_data['password'])
        validated_data['tipo'] = 'artesano'
        categoria = Categoria.objects.get(pk=categoria_id)
        validated_data['especialidad'] = categoria.nombre
        artesano = super().create(validated_data)
        Categoria.objects.filter(pk=categoria_id).update(artesano=artesano)
        return artesano

class CategoriaSerializer(serializers.ModelSerializer):
    artesano_nombre = serializers.CharField(source='artesano.nombre', read_only=True)
    disponible      = serializers.SerializerMethodField()

    class Meta:
        model  = Categoria
        fields = ['id', 'nombre', 'descripcion', 'artesano', 'artesano_nombre', 'disponible']
        extra_kwargs = {'artesano': {'read_only': True}}  # solo el admin la asigna

    def get_disponible(self, obj):
        """True si la categoría no tiene artesano asignado todavía."""
        return obj.artesano is None


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
        model  = Producto
        fields = [
            'id', 
            'codigo_barra', 
            'lote', 
            'nombre',
            'categoria', 
            'categoria_nombre',
            'precio_neto', 'precio_pvp', 'iva',
            'descuento', 'valor_descuento',
            'cantidad', 'stock_minimo', 'stock_maximo',
            'artesano', 'artesano_nombre',
            'precio_con_iva', 'precio_final',
            'estado_stock', 'cantidad_reservada', 'cantidad_disponible',
            'imagen', 'imagen_url', 'visible',
        ]
        extra_kwargs = {
            'categoria': {'required': False, 'allow_null': True},
            'artesano':  {'required': False},
            'imagen':    {'required': False},
            'lote':      {'required': False, 'allow_null': True, 'allow_blank': True},
            'codigo_barra': {'required': False, 'allow_null': True, 'allow_blank': True},
        }


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
        artesano    = data.get('artesano')
        categoria   = data.get('categoria')

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

        # Valida que la categoría pertenezca al artesano
        if artesano and categoria:
            cat_correcta = getattr(artesano, 'categoria', None)
            if cat_correcta and cat_correcta.id != categoria.id:
                raise serializers.ValidationError({
                    'categoria': 'La categoría no corresponde a este artesano.'
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
            'cantidad_disponible', 'artesano_nombre', 'imagen_url',
        ]

    def get_imagen_url(self, obj):
        request = self.context.get('request')
        if obj.imagen and request:
            return request.build_absolute_uri(obj.imagen.url)
        return ''


class KardexSerializer(serializers.ModelSerializer):
    producto_nombre = serializers.CharField(source='producto.nombre', read_only=True)
    tipo_display    = serializers.CharField(source='get_tipo_display', read_only=True)
    subtipo_display = serializers.CharField(source='get_subtipo_display', read_only=True)
    origen_display  = serializers.CharField(source='get_origen_display', read_only=True)

    class Meta:
        model  = Kardex
        fields = [
            'id', 'producto', 'producto_nombre', 'pedido_ref',
            'tipo', 'tipo_display', 'subtipo', 'subtipo_display',
            'origen', 'origen_display', 'cantidad', 'stock_resultante',
            'precio_unitario', 'fecha', 'nota', 'creado_por', 'creado_en',
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
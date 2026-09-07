# usuarios/serializers.py
from rest_framework import serializers
from django.contrib.auth.hashers import make_password
from .models import Usuario, Categoria, Producto, Notificacion, Favorito, Resena
from inventario.models import Kardex, DetallePedido


class UsuarioSerializer(serializers.ModelSerializer):
    foto_url        = serializers.SerializerMethodField()
    categoria_id    = serializers.SerializerMethodField()
    categoria_nombre = serializers.SerializerMethodField()

    class Meta:
        model  = Usuario
        fields = '__all__'
        extra_kwargs = {'password': {'write_only': True}}

    def get_foto_url(self, obj):
        if not obj.foto:
          return ''
    # Si ya es una URL completa (Supabase), devolverla directamente
        if str(obj.foto).startswith('http'):
          return str(obj.foto)
        request = self.context.get('request')
        if request:
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
    visible = serializers.BooleanField(required=False)
    artesano_telefono = serializers.CharField(source='artesano.telefono', read_only=True)

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
            'artesano', 'artesano_nombre', 'artesano_telefono',
            'precio_con_iva', 'precio_final',
            'estado_stock', 'cantidad_reservada', 'cantidad_disponible',
            'imagen', 'imagen_url', 'visible',
            'maneja_tallas', 'tallas', 'colores',
            'visitas',
        ]
        extra_kwargs = {
            'categoria': {'required': False, 'allow_null': True},
            'artesano':  {'required': False},
            'imagen':    {'required': False},
            'lote':      {'required': False, 'allow_null': True, 'allow_blank': True},
            'codigo_barra': {'required': False, 'allow_null': True, 'allow_blank': True},
            'visitas':   {'read_only': True},
        }


    def get_imagen_url(self, obj):
        if not obj.imagen:
           return ''
        if str(obj.imagen).startswith('http'):
           return str(obj.imagen)
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
        if not obj.imagen:
           return ''
        if str(obj.imagen).startswith('http'):
           return str(obj.imagen)
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


class FavoritoSerializer(serializers.ModelSerializer):
    producto_nombre     = serializers.CharField(source='producto.nombre', read_only=True)
    producto_imagen_url = serializers.CharField(source='producto.imagen', read_only=True, default='')
    producto_precio     = serializers.FloatField(source='producto.precio_final', read_only=True)
    artesano_nombre     = serializers.CharField(source='producto.artesano.nombre', read_only=True)

    class Meta:
        model  = Favorito
        fields = [
            'id', 'producto', 'producto_nombre', 'producto_imagen_url',
            'producto_precio', 'artesano_nombre', 'creado_en',
        ]
        read_only_fields = ['id', 'creado_en']


class ResenaSerializer(serializers.ModelSerializer):
    cliente_nombre  = serializers.CharField(source='cliente.nombre', read_only=True)
    producto_nombre = serializers.CharField(source='producto.nombre', read_only=True)

    class Meta:
        model  = Resena
        fields = [
            'id', 'producto', 'producto_nombre', 'cliente', 'cliente_nombre',
            'calificacion', 'comentario', 'creado_en', 'actualizado_en',
        ]
        read_only_fields = ['id', 'cliente', 'creado_en', 'actualizado_en']

    def validate_calificacion(self, value):
        if not (1 <= value <= 5):
            raise serializers.ValidationError('La calificación debe estar entre 1 y 5.')
        return value

    def validate(self, data):
        request  = self.context.get('request')
        producto = data.get('producto') or getattr(self.instance, 'producto', None)
        if request is None or producto is None:
            return data

        # Solo al crear: exige que el cliente haya comprado y recibido el producto.
        if self.instance is None:
            from .views import get_usuario_actual
            cliente = get_usuario_actual(request)
            if cliente is None:
                raise serializers.ValidationError('Debes iniciar sesión para dejar una reseña.')
            compro = DetallePedido.objects.filter(
                producto=producto,
                pedido__cliente=cliente,
                pedido__estado='Entregado',
            ).exists()
            if not compro:
                raise serializers.ValidationError(
                    'Solo puedes reseñar productos que ya te hayan sido entregados.'
                )
        return data
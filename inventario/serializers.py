# inventario/serializers.py
from rest_framework import serializers
from .models import Kardex, Pedido, DetallePedido, Devolucion

class DevolucionSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Devolucion
        fields = [
            'motivo', 'respuesta_artesano',
            'estado', 'fecha_solicitud', 'fecha_respuesta',
        ]

class DetallePedidoSerializer(serializers.ModelSerializer):
    producto_nombre = serializers.CharField(source='producto.nombre', read_only=True)
    producto_codigo = serializers.CharField(source='producto.codigo_barra', read_only=True, default='')
    producto_imagen = serializers.SerializerMethodField()
    subtotal        = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model  = DetallePedido
        fields = ['id', 'producto', 'producto_nombre', 'producto_codigo', 'producto_imagen',
                  'cantidad', 'precio', 'subtotal']

    def get_producto_imagen(self, obj):
        request = self.context.get('request')
        img = getattr(obj.producto, 'imagen', None)
        if not img:
            return ''
        if isinstance(img, str):
            return img
        try:
            url = img.url
        except (ValueError, AttributeError):
            return ''
        return request.build_absolute_uri(url) if request else url

class PedidoSerializer(serializers.ModelSerializer):
    detalles        = DetallePedidoSerializer(many=True, read_only=True)
    cliente_nombre  = serializers.SerializerMethodField()
    artesano_nombre = serializers.CharField(source='artesano.nombre', read_only=True, default='')
    devolucion      = DevolucionSerializer(read_only=True)  # ← agregar

    def get_cliente_nombre(self, obj):
        nombre = getattr(obj.cliente, 'nombre', '') or ''
        email  = getattr(obj.cliente, 'email',  '') or ''
        return nombre.strip() if nombre.strip() else email

    class Meta:
        model  = Pedido
        fields = [
            'id', 'codigo', 'cliente', 'cliente_nombre',
            'artesano', 'artesano_nombre',
            'estado', 'total', 'direccion', 'telefono',
            'fecha', 'updated', 'detalles',
            'numero_guia', 'transportadora',
            'fecha_envio', 'fecha_entrega',
            'devolucion',
        ]
        read_only_fields = ['id', 'codigo', 'fecha', 'updated']


class CrearDetallePedidoSerializer(serializers.Serializer):
    producto_id = serializers.IntegerField()
    cantidad    = serializers.IntegerField(min_value=1)
    precio      = serializers.DecimalField(max_digits=12, decimal_places=2)


class CrearPedidoSerializer(serializers.Serializer):
    cliente_id = serializers.IntegerField()
    items      = CrearDetallePedidoSerializer(many=True)
    direccion  = serializers.CharField(required=False, allow_blank=True, default='')
    telefono   = serializers.CharField(required=False, allow_blank=True, default='')


class CambiarEstadoSerializer(serializers.Serializer):
    pedido_id      = serializers.IntegerField(required=False)
    pedido_ref     = serializers.CharField(required=False)
    estado_nuevo   = serializers.CharField()
    admin_response = serializers.CharField(required=False, allow_blank=True, default='')
    admin_photos   = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )
    # Solo se usan al pasar a "Enviado": número de guía/ticket real que la
    # transportadora le dio al artesano, y el nombre de esa transportadora
    # (texto libre porque no hay integración con ninguna transportadora).
    numero_guia    = serializers.CharField(required=False, allow_blank=True, default='')
    transportadora = serializers.CharField(required=False, allow_blank=True, default='')


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
            'stock_resultante', 'precio_unitario', 'creado_por', 'creado_en',
        ]

    def validate_cantidad(self, value):
        if value <= 0:
            raise serializers.ValidationError("La cantidad debe ser mayor que 0.")
        return value
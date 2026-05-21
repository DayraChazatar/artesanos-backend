# inventario/views.py

from datetime import date
import uuid
from .models import Pedido, DetallePedido, Kardex, Devolucion

from django.shortcuts import get_object_or_404
from django.db import transaction
from django.contrib.auth.hashers import check_password

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from usuarios.models import Producto, Usuario
from usuarios.serializers import UsuarioSerializer

from .models import Pedido, DetallePedido, Kardex

from .serializers import (
    PedidoSerializer,
    CrearPedidoSerializer,
    CambiarEstadoSerializer,
    KardexSerializer,
)

from .services import (
    registrar_ajuste_manual,
    registrar_reposicion,
    registrar_reserva,
    registrar_venta,
    registrar_cancelacion,
    registrar_devolucion,
)


# ─────────────────────────────────────────────────────────────
# HELPERS DE STOCK
# ─────────────────────────────────────────────────────────────

def _reservar_stock(producto: Producto, cantidad: int):
    disponible = producto.cantidad - getattr(producto, 'cantidad_reservada', 0)
    if disponible < cantidad:
        raise ValueError(
            f'Stock disponible insuficiente para "{producto.nombre}": '
            f'disponible {disponible}, solicitado {cantidad}.'
        )
    producto.cantidad_reservada = getattr(producto, 'cantidad_reservada', 0) + cantidad
    producto.save(update_fields=['cantidad_reservada'])


def _liberar_reserva(producto: Producto, cantidad: int):
    producto.cantidad += cantidad
    producto.cantidad_reservada = max(0, getattr(producto, 'cantidad_reservada', 0) - cantidad)
    producto.save()


def _confirmar_entrega(producto: Producto, cantidad: int):
    producto.cantidad_reservada = max(0, getattr(producto, 'cantidad_reservada', 0) - cantidad)
    producto.save()


def _reponer_stock(producto: Producto, cantidad: int):
    producto.cantidad += cantidad
    producto.save()


# ─────────────────────────────────────────────────────────────
# CREAR PEDIDO
# ─────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def crear_pedido(request):
    serializer = CrearPedidoSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data

    try:
        cliente = Usuario.objects.get(pk=data['cliente_id'])
    except Usuario.DoesNotExist:
        return Response({'error': 'Cliente no encontrado'}, status=status.HTTP_404_NOT_FOUND)

    items = data['items']
    if not items:
        return Response({'error': 'El pedido debe contener productos'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        with transaction.atomic():
            productos_map = {}
            for item in items:
                pid = item['producto_id']
                try:
                    producto = Producto.objects.select_for_update().get(pk=pid)
                except Producto.DoesNotExist:
                    raise ValueError(f'Producto {pid} no encontrado.')
                productos_map[pid] = producto

            primer_producto  = productos_map[items[0]['producto_id']]
            artesano_obj     = getattr(primer_producto, 'artesano', None)
            total            = sum(item['precio'] * item['cantidad'] for item in items)

            pedido = Pedido.objects.create(
                cliente   = cliente,
                artesano  = artesano_obj,
                estado    = 'Pendiente',
                total     = total,
                direccion = data.get('direccion', ''),
                telefono  = data.get('telefono', ''),
            )

            for item in items:
                producto = productos_map[item['producto_id']]
                _reservar_stock(producto, item['cantidad'])
                registrar_reserva(
                    producto   = producto,
                    cantidad   = item['cantidad'],
                    pedido_ref = pedido.codigo,
                    creado_por = 'Sistema',
                )
                DetallePedido.objects.create(
                    pedido   = pedido,
                    producto = producto,
                    cantidad = item['cantidad'],
                    precio   = item['precio'],
                )

    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(
        PedidoSerializer(pedido, context={'request': request}).data,
        status=status.HTTP_201_CREATED,
    )


# ─────────────────────────────────────────────────────────────
# PEDIDOS CLIENTE
# ─────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])
def pedidos_cliente(request, cliente_id):
    pedidos = Pedido.objects.filter(
        cliente_id=cliente_id
    ).prefetch_related('detalles__producto')
    return Response(PedidoSerializer(pedidos, many=True, context={'request': request}).data)


# ─────────────────────────────────────────────────────────────
# PEDIDOS ARTESANO
# ─────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])
def pedidos_artesano(request, artesano_id):
    pedidos = Pedido.objects.filter(
        artesano_id=artesano_id
    ).prefetch_related('detalles__producto')
    return Response(PedidoSerializer(pedidos, many=True, context={'request': request}).data)


TRANSICIONES_VALIDAS = {
    # Cliente puede cancelar solo en Pendiente
    # Artesano acepta → En proceso
    'Pendiente': ['En proceso', 'Cancelado'],

    # Artesano prepara → Enviado (se bloquea cancelación)
    'En proceso': ['Enviado'],

    # Artesano despacha → Entregado (se genera guía automática)
    'Enviado': ['Entregado'],

    # Cliente puede solicitar devolución
    'Entregado': ['Devolucion solicitada'],

    # Artesano aprueba o rechaza
    'Devolucion solicitada': ['Devolucion aprobada', 'Devolucion rechazada'],

    # Estados finales
    'Cancelado':            [],
    'Devolucion aprobada':  [],
    'Devolucion rechazada': [],
}


# ─────────────────────────────────────────────────────────────
# CAMBIAR ESTADO PEDIDO
# ─────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def cambiar_estado(request):
    serializer = CambiarEstadoSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data

    if data.get('pedido_id'):
        pedido = get_object_or_404(Pedido, pk=data['pedido_id'])
    elif data.get('pedido_ref'):
        pedido = get_object_or_404(Pedido, codigo=data['pedido_ref'])
    else:
        return Response({'error': 'Debes enviar pedido_id o pedido_ref'}, status=status.HTTP_400_BAD_REQUEST)

    estado_anterior = pedido.estado
    estado_nuevo    = data['estado_nuevo']

    if estado_anterior == estado_nuevo:
        return Response({'error': 'El pedido ya tiene ese estado'}, status=status.HTTP_400_BAD_REQUEST)

    permitidos = TRANSICIONES_VALIDAS.get(estado_anterior, [])
    if estado_nuevo not in permitidos:
        return Response(
            {'error': f'Transición no permitida: {estado_anterior} → {estado_nuevo}. Permitidas: {permitidos}'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if estado_nuevo == 'Devolucion solicitada' and estado_anterior != 'Entregado':
        return Response({'error': 'Solo puedes devolver pedidos entregados.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        with transaction.atomic():
            detalles = pedido.detalles.select_related('producto').select_for_update()

            for detalle in detalles:
                producto = detalle.producto
                cantidad = detalle.cantidad

                if estado_nuevo == 'Cancelado':
                    registrar_cancelacion(
                        producto   = producto,
                        cantidad   = cantidad,
                        pedido_ref = pedido.codigo,
                        creado_por = 'Sistema',
                    )

                elif estado_nuevo == 'Entregado':
                    registrar_venta(
                        producto   = producto,
                        cantidad   = cantidad,
                        pedido_ref = pedido.codigo,
                        creado_por = 'Sistema',
                    )

                elif estado_nuevo == 'Devuelto':
                    registrar_devolucion(
                        producto   = producto,
                        cantidad   = cantidad,
                        pedido_ref = pedido.codigo,
                        nota       = 'Producto devuelto',
                        creado_por = 'Sistema',
                    )

            # Actualizar estado
            pedido.estado = estado_nuevo

            # Guardar devolución cuando el cliente la solicita
            if estado_nuevo == 'Devolucion solicitada':
                motivo = data.get('admin_response', '')
                Devolucion.objects.update_or_create(
                    pedido=pedido,
                    defaults={
                        'motivo': motivo,
                        'estado': 'Pendiente',
                    }
                )

# Actualizar devolución cuando el artesano responde
            if estado_nuevo == 'Devolucion aprobada':
                Devolucion.objects.filter(pedido=pedido).update(
                    estado='Aprobada',
                    respuesta_artesano=data.get('admin_response', ''),
                    fecha_respuesta=date.today(),
                )

            if estado_nuevo == 'Devolucion rechazada':
                Devolucion.objects.filter(pedido=pedido).update(
                    estado='Rechazada',
                    respuesta_artesano=data.get('admin_response', ''),
                    fecha_respuesta=date.today(),
                )

            if estado_nuevo == 'Enviado' and not pedido.numero_guia:
                pedido.numero_guia    = f'PKR-{pedido.codigo}-{uuid.uuid4().hex[:6].upper()}'
                pedido.transportadora = 'Coordinadora'
                pedido.fecha_envio    = date.today()

            pedido.save()
            pedido.refresh_from_db()
            print(f">>> GUIA: {pedido.numero_guia}")

    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    primer_detalle  = pedido.detalles.select_related('producto').first()
    stock_actual    = getattr(primer_detalle.producto, 'cantidad', None)          if primer_detalle else None
    stock_reservado = getattr(primer_detalle.producto, 'cantidad_reservada', None) if primer_detalle else None

    return Response({
        'ok':              True,
        'pedido_id':       pedido.pk,
        'codigo':          pedido.codigo,
        'estado_anterior': estado_anterior,
        'estado_nuevo':    estado_nuevo,
        'numero_guia':     pedido.numero_guia,
        'transportadora':  pedido.transportadora,
        'fecha_envio':     pedido.fecha_envio,
        'stock_actual':    stock_actual,
        'stock_reservado': stock_reservado,
    })

# ─────────────────────────────────────────────────────────────
# KARDEX — LISTAR
# ─────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])
def lista_kardex(request):
    qs = Kardex.objects.select_related('producto').all()

    desde       = request.query_params.get('desde')
    hasta       = request.query_params.get('hasta')
    producto_id = request.query_params.get('producto')
    tipo        = request.query_params.get('tipo')
    origen      = request.query_params.get('origen')

    if desde:       qs = qs.filter(fecha__gte=desde)
    if hasta:       qs = qs.filter(fecha__lte=hasta)
    if producto_id: qs = qs.filter(producto_id=producto_id)
    if tipo:        qs = qs.filter(tipo=tipo)
    if origen:      qs = qs.filter(origen=origen)

    return Response(KardexSerializer(qs, many=True).data)


# ─────────────────────────────────────────────────────────────
# KARDEX — CREAR
# ─────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def crear_kardex(request):
    producto_id  = request.data.get('producto')
    cantidad_raw = request.data.get('cantidad')
    fecha        = request.data.get('fecha')
    nota         = request.data.get('nota', '')
    precio_pvp   = request.data.get('precio_pvp')

    if not producto_id or cantidad_raw is None or not fecha:
        return Response({'error': 'producto, cantidad y fecha son obligatorios.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        cantidad_raw = int(cantidad_raw)
    except (TypeError, ValueError):
        return Response({'error': 'La cantidad debe ser un número entero.'}, status=status.HTTP_400_BAD_REQUEST)

    if cantidad_raw <= 0:
        return Response({'error': 'La cantidad debe ser mayor a 0.'}, status=status.HTTP_400_BAD_REQUEST)

    if precio_pvp is not None:
        try:
            precio_pvp = float(precio_pvp)
            if precio_pvp < 0:
                raise ValueError()
        except (TypeError, ValueError):
            return Response({'error': 'El precio de venta al público debe ser un número positivo.'}, status=status.HTTP_400_BAD_REQUEST)

    producto = get_object_or_404(Producto, pk=producto_id)

    try:
        movimiento = registrar_ajuste_manual(
            producto     = producto,
            cantidad_raw = cantidad_raw,
            nota         = nota,
            fecha        = fecha,
            creado_por   = 'Sistema',
            precio_pvp   = precio_pvp,
        )
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(KardexSerializer(movimiento).data, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────────
# REPOSICIÓN DE STOCK
# ─────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def reposicion_stock(request):
    producto_id = request.data.get('producto')
    cantidad    = request.data.get('cantidad')
    nota        = request.data.get('nota', '')

    if not producto_id or not cantidad:
        return Response({'error': 'producto y cantidad son obligatorios.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        cantidad = int(cantidad)
        if cantidad <= 0:
            raise ValueError()
    except (TypeError, ValueError):
        return Response({'error': 'La cantidad debe ser un número entero mayor que 0.'}, status=status.HTTP_400_BAD_REQUEST)

    producto = get_object_or_404(Producto, pk=producto_id)

    try:
        movimiento = registrar_reposicion(
            producto   = producto,
            cantidad   = cantidad,
            nota       = nota,
            creado_por = 'Sistema',
        )
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(
        {**KardexSerializer(movimiento).data, 'stock_resultante': movimiento.stock_resultante},
        status=status.HTTP_201_CREATED,
    )


# ─────────────────────────────────────────────────────────────
# RESUMEN INVENTARIO
# ─────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])
def resumen_inventario(request):
    kardex = Kardex.objects.all()

    total_entradas = sum(
        k.cantidad for k in kardex
        if k.tipo in ('Entrada', 'Devolucion') and k.subtipo not in ('cancelacion',)
    )
    total_salidas = sum(
        k.cantidad for k in kardex if k.tipo in ('Salida',)
    )
    valor_movido = sum(
        (k.precio_unitario or 0) * k.cantidad
        for k in kardex
        if k.tipo in ('Entrada', 'Devolucion', 'Salida') and k.subtipo not in ('reserva', 'cancelacion')
    )

    return Response({
        'total_entradas':    total_entradas,
        'total_salidas':     total_salidas,
        'balance_neto':      total_entradas - total_salidas,
        'total_movimientos': kardex.count(),
        'valor_movido':      float(valor_movido),
    })


# ─────────────────────────────────────────────────────────────
# PERFIL ARTESANO
# ─────────────────────────────────────────────────────────────

@api_view(['GET', 'PATCH'])
@permission_classes([AllowAny])
def perfil_artesano(request, usuario_id):
    try:
        usuario = Usuario.objects.get(pk=usuario_id, tipo='artesano')
    except Usuario.DoesNotExist:
        return Response({'error': 'Artesano no encontrado'}, status=status.HTTP_404_NOT_FOUND)

    if request.method == 'GET':
        serializer = UsuarioSerializer(usuario, context={'request': request})
        return Response(serializer.data)

    if request.method == 'PATCH':
        serializer = UsuarioSerializer(usuario, data=request.data, partial=True, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ─────────────────────────────────────────────────────────────
# CAMBIAR CONTRASEÑA
# ─────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def cambiar_password(request, usuario_id):
    try:
        usuario = Usuario.objects.get(pk=usuario_id)
    except Usuario.DoesNotExist:
        return Response({'error': 'Usuario no encontrado'}, status=status.HTTP_404_NOT_FOUND)

    password_actual    = request.data.get('password_actual')
    password_nueva     = request.data.get('password_nueva')
    password_confirmar = request.data.get('password_confirmar')

    if not all([password_actual, password_nueva, password_confirmar]):
        return Response({'error': 'Todos los campos son obligatorios'}, status=status.HTTP_400_BAD_REQUEST)

    if not check_password(password_actual, usuario.password):
        return Response({'error': 'La contraseña actual es incorrecta'}, status=status.HTTP_400_BAD_REQUEST)

    if password_nueva != password_confirmar:
        return Response({'error': 'Las contraseñas nuevas no coinciden'}, status=status.HTTP_400_BAD_REQUEST)

    if len(password_nueva) < 6:
        return Response({'error': 'La contraseña debe tener al menos 6 caracteres'}, status=status.HTTP_400_BAD_REQUEST)

    usuario.set_password(password_nueva)
    usuario.save()
    return Response({'ok': True, 'mensaje': 'Contraseña actualizada correctamente'})
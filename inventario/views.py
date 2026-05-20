# inventario/views.py
from datetime import date
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from django.db import transaction
from rest_framework.decorators import api_view

from usuarios.models import Producto
from usuarios.models import Usuario

from .models      import Pedido, DetallePedido
from .serializers import (
    PedidoSerializer,
    CrearPedidoSerializer,
    CambiarEstadoSerializer,
)   

from .models import Kardex
from .serializers import KardexSerializer
from .services import (
    registrar_ajuste_manual,
    registrar_reposicion,
    registrar_reserva,
    registrar_venta,
    registrar_cancelacion,
    registrar_devolucion,
)

# ─── Helpers de stock ─────────────────────────────────────────────────────────
 
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
    producto.cantidad           += cantidad
    producto.cantidad_reservada  = max(0, getattr(producto, 'cantidad_reservada', 0) - cantidad)
    producto.save()
 
def _confirmar_entrega(producto: Producto, cantidad: int):
    producto.cantidad_reservada = max(0, getattr(producto, 'cantidad_reservada', 0) - cantidad)
    producto.save()
 
def _reponer_stock(producto: Producto, cantidad: int):
    producto.cantidad += cantidad
    producto.save()
 
# ─── 1. Crear pedido ──────────────────────────────────────────────────────────
 
@api_view(['POST'])
@permission_classes([AllowAny])
def crear_pedido(request):
    ser = CrearPedidoSerializer(data=request.data)
    if not ser.is_valid():
        return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
 
    data = ser.validated_data
 
    try:
        cliente = Usuario.objects.get(pk=data['cliente_id'])
    except Usuario.DoesNotExist:
        return Response({'error': 'Cliente no encontrado'}, status=status.HTTP_404_NOT_FOUND)
 
    items = data['items']
    if not items:
        return Response({'error': 'El pedido debe tener al menos un producto'}, status=400)
 
    try:
        with transaction.atomic():
            productos_map: dict[int, Producto] = {}
            for item in items:
                pid = item['producto_id']
                try:
                    prod = Producto.objects.select_for_update().get(pk=pid)
                except Producto.DoesNotExist:
                    raise ValueError(f'Producto {pid} no encontrado.')
                productos_map[pid] = prod
 
            primer_prod  = productos_map[items[0]['producto_id']]
            artesano_obj = getattr(primer_prod, 'artesano', None)
 
            total = sum(item['precio'] * item['cantidad'] for item in items)
 
            pedido = Pedido.objects.create(
                cliente   = cliente,
                artesano  = artesano_obj,
                estado    = 'Pendiente',
                total     = total,
                direccion = data.get('direccion', ''),
                telefono  = data.get('telefono', ''),
            )
 
            for item in items:
                prod = productos_map[item['producto_id']]
                _reservar_stock(prod, item['cantidad'])
                DetallePedido.objects.create(
                    pedido   = pedido,
                    producto = prod,
                    cantidad = item['cantidad'],
                    precio   = item['precio'],
                )
 
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
 
    return Response(
        PedidoSerializer(pedido, context={'request': request}).data,
        status=status.HTTP_201_CREATED,
    )
 
# ─── 2. Listar pedidos por cliente ───────────────────────────────────────────
 
@api_view(['GET'])
@permission_classes([AllowAny])
def pedidos_cliente(request, cliente_id):
    pedidos = Pedido.objects.filter(cliente_id=cliente_id).prefetch_related('detalles__producto')
    return Response(PedidoSerializer(pedidos, many=True, context={'request': request}).data)
 
# ─── 3. Listar pedidos por artesano ──────────────────────────────────────────
 
@api_view(['GET'])
@permission_classes([AllowAny])
def pedidos_artesano(request, artesano_id):
    pedidos = Pedido.objects.filter(artesano_id=artesano_id).prefetch_related('detalles__producto')
    return Response(PedidoSerializer(pedidos, many=True, context={'request': request}).data)
 
# ─── 4. Cambiar estado ────────────────────────────────────────────────────────

TRANSICIONES_VALIDAS: dict[str, list[str]] = {
    'Pendiente':             ['En proceso', 'Enviado', 'Cancelado'],
    'En proceso':            ['Enviado', 'Cancelado'],
    'Enviado':               ['Entregado', 'Cancelado'],
    'Entregado':             ['Devolucion solicitada', 'Devolucion'],
    'Cancelado':             [],
    'Devolucion solicitada': ['Devuelto', 'Rechazado'],
    'Devuelto':              [],
    'Rechazado':             [],
    'Devolucion':            [],
}
 
@api_view(['POST'])
@permission_classes([AllowAny])
def cambiar_estado(request):
    ser = CambiarEstadoSerializer(data=request.data)
    if not ser.is_valid():
        return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
 
    data = ser.validated_data
 
    if data.get('pedido_id'):
        pedido = get_object_or_404(Pedido, pk=data['pedido_id'])
    elif data.get('pedido_ref'):
        pedido = get_object_or_404(Pedido, codigo=data['pedido_ref'])
    else:
        return Response({'error': 'Proporciona pedido_id o pedido_ref'}, status=400)
 
    estado_anterior = pedido.estado
    estado_nuevo    = data['estado_nuevo']
 
    if estado_anterior == estado_nuevo:
        return Response({'error': 'El pedido ya tiene ese estado'}, status=400)
 
    permitidos = TRANSICIONES_VALIDAS.get(estado_anterior, [])
    if estado_nuevo not in permitidos:
        return Response(
            {'error': f'Transición no permitida: {estado_anterior} → {estado_nuevo}. '
                      f'Permitidas: {permitidos}'},
            status=status.HTTP_400_BAD_REQUEST,
        )
 
    try:
        with transaction.atomic():
            detalles = pedido.detalles.select_related('producto').select_for_update()

            for detalle in detalles:
                prod     = detalle.producto
                cantidad = detalle.cantidad

                if estado_nuevo == 'Cancelado':
                    if estado_anterior not in ('Cancelado', 'Entregado',
                                               'Devolucion', 'Devuelto'):
                        registrar_cancelacion(
                            producto   = prod,
                            cantidad   = cantidad,
                            pedido_ref = pedido.codigo,
                            creado_por = 'Sistema',
                        )

                elif estado_nuevo == 'Entregado':
                    registrar_venta(
                        producto   = prod,
                        cantidad   = cantidad,
                        pedido_ref = pedido.codigo,
                        creado_por = 'Sistema',
                    )

                elif estado_nuevo in ('Devolucion', 'Devuelto'):
                    registrar_devolucion(
                        producto   = prod,
                        cantidad   = cantidad,
                        pedido_ref = pedido.codigo,
                        nota       = 'Devolución registrada',
                        creado_por = 'Sistema',
                    )

            pedido.estado = estado_nuevo
            pedido.save()

    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
 
    primer_detalle  = pedido.detalles.select_related('producto').first()
    stock_actual    = getattr(primer_detalle.producto, 'cantidad', None) if primer_detalle else None
    stock_reservado = getattr(primer_detalle.producto, 'cantidad_reservada', None) if primer_detalle else None
 
    return Response({
        'ok':              True,
        'pedido_id':       pedido.pk,
        'codigo':          pedido.codigo,
        'estado_anterior': estado_anterior,
        'estado_nuevo':    estado_nuevo,
        'stock_actual':    stock_actual,
        'stock_reservado': stock_reservado,
    })

# ─────────────────────────────────────────────────────────────────────────────
# GET /api/inventario/kardex/
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])
def lista_kardex(request):
    qs = Kardex.objects.select_related('producto').all()

    desde       = request.query_params.get('desde')
    hasta       = request.query_params.get('hasta')
    producto_id = request.query_params.get('producto')
    tipo        = request.query_params.get('tipo')
    origen      = request.query_params.get('origen')

    if desde:
        qs = qs.filter(fecha__gte=desde)
    if hasta:
        qs = qs.filter(fecha__lte=hasta)
    if producto_id:
        qs = qs.filter(producto_id=producto_id)
    if tipo:
        qs = qs.filter(tipo=tipo)
    if origen:
        qs = qs.filter(origen=origen)

    return Response(KardexSerializer(qs, many=True).data)


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/inventario/kardex/nuevo/
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def crear_kardex(request):
    producto_id  = request.data.get('producto')
    cantidad_raw = request.data.get('cantidad')
    fecha        = request.data.get('fecha')
    nota         = request.data.get('nota', '')
    precio_pvp   = request.data.get('precio_pvp')

    if not producto_id or cantidad_raw is None or not fecha:
        return Response(
            {'error': 'producto, cantidad y fecha son obligatorios.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        cantidad_raw = int(cantidad_raw)
    except (TypeError, ValueError):
        return Response(
            {'error': 'La cantidad debe ser un número entero.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if cantidad_raw <= 0:
        return Response(
            {'error': 'La cantidad debe ser mayor a 0.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    if precio_pvp is not None:
        try:
            precio_pvp = float(precio_pvp)
            if precio_pvp < 0:
                raise ValueError()
        except (TypeError, ValueError):
            return Response(
                {'error': 'El precio de venta al público debe ser un número positivo.'},
                status=status.HTTP_400_BAD_REQUEST
            )

    producto   = get_object_or_404(Producto, pk=producto_id)
    creado_por = 'Sistema'

    try:
        movimiento = registrar_ajuste_manual(
            producto     = producto,
            cantidad_raw = cantidad_raw,
            nota         = nota,
            fecha        = fecha,
            creado_por   = creado_por,
            precio_pvp   = precio_pvp,
        )
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(KardexSerializer(movimiento).data, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/inventario/reposicion/
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def reposicion_stock(request):
    producto_id = request.data.get('producto')
    cantidad    = request.data.get('cantidad')
    nota        = request.data.get('nota', '')

    if not producto_id or not cantidad:
        return Response(
            {'error': 'producto y cantidad son obligatorios.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        cantidad = int(cantidad)
        if cantidad <= 0:
            raise ValueError()
    except (TypeError, ValueError):
        return Response(
            {'error': 'La cantidad debe ser un número entero mayor que 0.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    producto   = get_object_or_404(Producto, pk=producto_id)
    creado_por = 'Sistema'

    try:
        movimiento = registrar_reposicion(
            producto   = producto,
            cantidad   = cantidad,
            nota       = nota,
            creado_por = creado_por,
        )
    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(
        {
            **KardexSerializer(movimiento).data,
            'stock_resultante': movimiento.stock_resultante,
        },
        status=status.HTTP_201_CREATED
    )


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/inventario/resumen/
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([AllowAny])
def resumen_inventario(request):
    kardex = Kardex.objects.all()

    total_entradas = sum(
        k.cantidad for k in kardex
        if k.tipo in ('Entrada', 'Devolucion')
        and k.subtipo not in ('cancelacion',)
    )
    total_salidas = sum(
        k.cantidad for k in kardex
        if k.tipo in ('Salida',)
    )
    valor_movido = sum(
        (k.precio_unitario or 0) * k.cantidad
        for k in kardex
        if k.tipo in ('Entrada', 'Devolucion', 'Salida')
        and k.subtipo not in ('reserva', 'cancelacion')
    )

    return Response({
        'total_entradas':    total_entradas,
        'total_salidas':     total_salidas,
        'balance_neto':      total_entradas - total_salidas,
        'total_movimientos': kardex.count(),
        'valor_movido':      float(valor_movido),
    })
   # ── Perfil artesano ───────────────────────────────────────────────────────────
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
        serializer = UsuarioSerializer(
            usuario, data=request.data, partial=True,
            context={'request': request}
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ── Cambiar contraseña ────────────────────────────────────────────────────────
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
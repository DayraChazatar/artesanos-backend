# inventario/views.py
import hashlib
import os

from datetime import date
import uuid
from .models import Pedido, DetallePedido, Kardex, Devolucion, Favorito


from django.shortcuts import get_object_or_404
from django.db import transaction

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from usuarios.models import Producto, Usuario
from storage_backend import upload_image

from usuarios.views import get_usuario_actual
from .serializers import (
    PedidoSerializer,
    CrearPedidoSerializer,
    CambiarEstadoSerializer,
    KardexSerializer,
    FavoritoSerializer,
)

from .services import (
    registrar_ajuste_manual,
    registrar_reposicion,
    registrar_reserva,
    registrar_venta,
    registrar_cancelacion,
    registrar_devolucion,
    notificar,
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
@permission_classes([IsAuthenticated])
def crear_pedido(request):
    """Crea UN pedido por cada artesano presente en el carrito — un carrito
    con productos de 2 artesanos distintos genera 2 pedidos, cada uno solo
    con los productos (y el total) de ese artesano. Antes se creaba un único
    pedido que solo quedaba visible para el artesano del primer producto del
    carrito; el resto del pedido "desaparecía" para los demás."""
    serializer = CrearPedidoSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data

    usuario_actual = get_usuario_actual(request)
    if usuario_actual is None or usuario_actual.id != data['cliente_id']:
        return Response({'error': 'No puedes crear un pedido a nombre de otro usuario.'}, status=status.HTTP_403_FORBIDDEN)

    try:
        cliente = Usuario.objects.get(pk=data['cliente_id'])
    except Usuario.DoesNotExist:
        return Response({'error': 'Cliente no encontrado'}, status=status.HTTP_404_NOT_FOUND)

    items = data['items']
    if not items:
        return Response({'error': 'El pedido debe contener productos'}, status=status.HTTP_400_BAD_REQUEST)

    metodos_pago = data.get('metodos_pago') or {}

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

            # Agrupa los items del carrito por artesano, conservando el
            # orden de llegada (no altera el total ni las cantidades).
            grupos = {}  # artesano_id (o None) -> [items]
            for item in items:
                producto = productos_map[item['producto_id']]
                artesano_id = producto.artesano_id
                grupos.setdefault(artesano_id, []).append(item)

            pedidos_creados = []
            for artesano_id, items_grupo in grupos.items():
                metodo_pago = metodos_pago.get(str(artesano_id), 'wompi')

                if metodo_pago == 'transferencia':
                    artesano_obj = Usuario.objects.filter(pk=artesano_id).first()
                    if artesano_obj is None or not artesano_obj.tiene_pago_directo:
                        raise ValueError(
                            'Uno de los artesanos de tu carrito ya no tiene disponible el pago '
                            'directo — actualiza la página e inténtalo de nuevo.'
                        )
                else:
                    artesano_obj = Usuario.objects.filter(pk=artesano_id).first() if artesano_id else None

                total_grupo = sum(item['precio'] * item['cantidad'] for item in items_grupo)

                pedido = Pedido.objects.create(
                    cliente      = cliente,
                    artesano     = artesano_obj,
                    estado       = 'Pago pendiente',
                    total        = total_grupo,
                    direccion    = data.get('direccion', ''),
                    telefono     = data.get('telefono', ''),
                    metodo_pago  = metodo_pago,
                )

                for item in items_grupo:
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

                notificar(
                    artesano_obj,
                    tipo='pedido',
                    titulo=f'🛍️ Nuevo pedido {pedido.codigo}',
                    detalle=(
                        f'{cliente.nombre} hizo un pedido por ${total_grupo:,.0f} '
                        f'({"transferencia directa" if metodo_pago == "transferencia" else "pago con Wompi"}). '
                        f'Queda en "Pago pendiente" hasta que se confirme el pago.'
                    ),
                    ruta='/pedidos',
                    referencia_id=pedido.id,
                )

                pedidos_creados.append(pedido)

    except ValueError as e:
        return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(
        PedidoSerializer(pedidos_creados, many=True, context={'request': request}).data,
        status=status.HTTP_201_CREATED,
    )


# ─────────────────────────────────────────────────────────────
# PEDIDOS CLIENTE
# ─────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def pedidos_cliente(request, cliente_id):
    usuario_actual = get_usuario_actual(request)
    if usuario_actual is None or usuario_actual.id != cliente_id:
        return Response({'error': 'No puedes ver los pedidos de otro usuario.'}, status=status.HTTP_403_FORBIDDEN)

    pedidos = Pedido.objects.filter(
        cliente_id=cliente_id
    ).select_related('cliente', 'artesano', 'devolucion').prefetch_related('detalles__producto')
    return Response(PedidoSerializer(pedidos, many=True, context={'request': request}).data)


# ─────────────────────────────────────────────────────────────
# PEDIDOS ARTESANO
# ─────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def pedidos_artesano(request, artesano_id):
    usuario_actual = get_usuario_actual(request)
    if usuario_actual is None or usuario_actual.id != artesano_id:
        return Response({'error': 'No puedes ver los pedidos de otro artesano.'}, status=status.HTTP_403_FORBIDDEN)

    pedidos = Pedido.objects.filter(
        artesano_id=artesano_id
    ).select_related('cliente', 'artesano', 'devolucion').prefetch_related('detalles__producto')
    return Response(PedidoSerializer(pedidos, many=True, context={'request': request}).data)


TRANSICIONES_VALIDAS = {
    # Pago por transferencia directa: el cliente puede arrepentirse y
    # cancelar mientras espera, o el artesano confirma que le llegó el pago
    # (con Wompi esta transición la hace el webhook, no pasa por aquí).
    'Pago pendiente': ['Pago confirmado', 'Cancelado'],

    # El pago se confirmó (webhook Wompi, o el artesano a mano) → el
    # artesano acepta el pedido
    'Pago confirmado': ['Pendiente'],

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
@permission_classes([IsAuthenticated])
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

    usuario_actual = get_usuario_actual(request)
    es_el_cliente   = usuario_actual is not None and usuario_actual.id == pedido.cliente_id
    es_el_artesano  = usuario_actual is not None and usuario_actual.id == pedido.artesano_id
    if not (es_el_cliente or es_el_artesano):
        return Response({'error': 'No tienes permiso sobre este pedido.'}, status=status.HTTP_403_FORBIDDEN)

    estado_anterior = pedido.estado
    estado_nuevo    = data['estado_nuevo']

    # Solo el artesano gestiona el despacho/entrega, las devoluciones y la
    # confirmación manual del pago; el cliente solo puede cancelar o
    # solicitar una devolución.
    SOLO_ARTESANO = ('En proceso', 'Enviado', 'Entregado', 'Devolucion aprobada', 'Devolucion rechazada', 'Pago confirmado')
    if estado_nuevo in SOLO_ARTESANO and not es_el_artesano:
        return Response({'error': 'Solo el artesano puede realizar esta acción.'}, status=status.HTTP_403_FORBIDDEN)

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

    # Confirmar "Pago confirmado" desde "Pago pendiente" a mano solo tiene
    # sentido para pago por transferencia directa (el de Wompi lo confirma
    # su propio webhook, con la firma verificada — nunca a mano por aquí), y
    # solo si el cliente ya subió el comprobante.
    if estado_nuevo == 'Pago confirmado' and estado_anterior == 'Pago pendiente':
        if pedido.metodo_pago != 'transferencia':
            return Response({'error': 'El pago de este pedido se confirma automáticamente por Wompi, no a mano.'}, status=status.HTTP_400_BAD_REQUEST)
        if not pedido.comprobante_url:
            return Response({'error': 'El cliente todavía no ha subido el comprobante de pago.'}, status=status.HTTP_400_BAD_REQUEST)

    # ── Envío: como no hay integración con ninguna transportadora, el
    # número de guía/ticket lo digita el artesano en la pestaña "Referencias"
    # y es obligatorio — ya no se genera uno falso automáticamente.
    numero_guia_nuevo  = (data.get('numero_guia') or '').strip()
    transportadora_nueva = (data.get('transportadora') or '').strip()
    if estado_nuevo == 'Enviado' and not numero_guia_nuevo:
        return Response(
            {'error': 'Debes indicar el número de referencia o ticket que te dio la transportadora.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

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
                elif estado_nuevo == 'Devolucion aprobada':
                    registrar_devolucion(
                       producto   = producto,
                       cantidad   = cantidad,
                       pedido_ref = pedido.codigo,
                       nota       = 'Devolución aprobada por el artesano',
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

            if estado_nuevo == 'Enviado':
                pedido.numero_guia    = numero_guia_nuevo
                if transportadora_nueva:
                    pedido.transportadora = transportadora_nueva
                pedido.fecha_envio    = date.today()

            if estado_nuevo == 'Entregado':
                pedido.fecha_entrega = date.today()

            pedido.save()
            pedido.refresh_from_db()

            if estado_nuevo == 'Devolucion solicitada':
                notificar(
                    pedido.artesano,
                    tipo='pedido',
                    titulo=f'↩️ Solicitud de devolución {pedido.codigo}',
                    detalle=f'{pedido.cliente.nombre} solicitó devolver este pedido. Revisa el motivo y responde.',
                    ruta='/pedidos',
                    referencia_id=pedido.id,
                )

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

# NOTA: se retiró cambiar_estado_masivo (marcar varios pedidos como
# Enviado/Entregado de un clic). Ya no aplica: desde la pestaña
# "Referencias" cada envío requiere su propio número de guía/ticket real,
# así que no tiene sentido aplicar el mismo cambio a varios pedidos a la vez.

# ─────────────────────────────────────────────────────────────
# COMPROBANTE DE PAGO (transferencia directa)
# ─────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def subir_comprobante(request, pedido_id):
    """El cliente sube la foto del comprobante de su transferencia — el
    artesano la revisa desde su panel y confirma el pago a mano."""
    pedido = get_object_or_404(Pedido, pk=pedido_id)

    usuario_actual = get_usuario_actual(request)
    if usuario_actual is None or usuario_actual.id != pedido.cliente_id:
        return Response({'error': 'No puedes subir un comprobante para el pedido de otro usuario.'}, status=status.HTTP_403_FORBIDDEN)

    if pedido.metodo_pago != 'transferencia':
        return Response({'error': 'Este pedido no se paga por transferencia directa.'}, status=status.HTTP_400_BAD_REQUEST)
    if pedido.estado != 'Pago pendiente':
        return Response({'error': f'Este pedido ya está en estado "{pedido.estado}".'}, status=status.HTTP_400_BAD_REQUEST)

    archivo = request.FILES.get('comprobante')
    if not archivo:
        return Response({'error': 'Debes adjuntar una imagen del comprobante.'}, status=status.HTTP_400_BAD_REQUEST)

    filename = f"{uuid.uuid4()}_{archivo.name}"
    pedido.comprobante_url = upload_image(archivo, 'comprobantes', filename)
    pedido.save(update_fields=['comprobante_url'])

    notificar(
        pedido.artesano,
        tipo='pedido',
        titulo=f'🧾 Comprobante recibido {pedido.codigo}',
        detalle=f'{usuario_actual.nombre} subió el comprobante de su transferencia. Revísalo y confirma el pago.',
        ruta='/pedidos',
        referencia_id=pedido.id,
    )

    return Response(PedidoSerializer(pedido, context={'request': request}).data)

# ─────────────────────────────────────────────────────────────
# KARDEX — LISTAR
# ─────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def lista_kardex(request):
    usuario_actual = get_usuario_actual(request)
    if usuario_actual is None:
        return Response({'error': 'No autenticado.'}, status=status.HTTP_403_FORBIDDEN)

    qs = Kardex.objects.select_related('producto').filter(producto__artesano_id=usuario_actual.id)

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
@permission_classes([IsAuthenticated])
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

    usuario_actual = get_usuario_actual(request)
    if usuario_actual is None or producto.artesano_id != usuario_actual.id:
        return Response({'error': 'No puedes ajustar el inventario de un producto que no es tuyo.'}, status=status.HTTP_403_FORBIDDEN)

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
@permission_classes([IsAuthenticated])
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

    usuario_actual = get_usuario_actual(request)
    if usuario_actual is None or producto.artesano_id != usuario_actual.id:
        return Response({'error': 'No puedes reponer stock de un producto que no es tuyo.'}, status=status.HTTP_403_FORBIDDEN)

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
@permission_classes([IsAuthenticated])
def resumen_inventario(request):
    usuario_actual = get_usuario_actual(request)
    if usuario_actual is None:
        return Response({'error': 'No autenticado.'}, status=status.HTTP_403_FORBIDDEN)

    kardex = Kardex.objects.filter(producto__artesano_id=usuario_actual.id)

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


# NOTA: se retiraron perfil_artesano/cambiar_password de este archivo — eran
# una copia duplicada y sin control de dueño (AllowAny) de las versiones
# reales en usuarios/views.py, que son las que de verdad están conectadas
# en las URLs (api/perfil/artesano/... y api/perfil/cambiar-password/...).

# ─────────────────────────────────────────────────────────────
# webhook_wompi
# ─────────────────────────────────────────────────────────────
@api_view(['POST'])
@permission_classes([AllowAny])
def webhook_wompi(request):

    data = request.data

    try:
        transaccion = data['data']['transaction']
        propiedades = data['signature']['properties']
        valores = ''.join(str(_get_nested(data['data'], p)) for p in propiedades)
        cadena = f"{valores}{data['timestamp']}{os.getenv('WOMPI_EVENTS_SECRET')}"
        firma_calculada = hashlib.sha256(cadena.encode()).hexdigest()

        if firma_calculada != data['signature']['checksum']:
            return Response(status=status.HTTP_400_BAD_REQUEST)
    except (KeyError, TypeError):
        return Response(status=status.HTTP_400_BAD_REQUEST)

    try:
        pedido = Pedido.objects.get(codigo=transaccion['reference'])
    except Pedido.DoesNotExist:
        return Response(status=status.HTTP_404_NOT_FOUND)

    if transaccion['status'] == 'APPROVED':
        monto_esperado = int(pedido.total * 100)
        if transaccion.get('amount_in_cents') != monto_esperado:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        ya_confirmado = pedido.estado == 'Pago confirmado'
        pedido.estado = 'Pago confirmado'
        pedido.save()
        if not ya_confirmado:
            notificar(
                pedido.artesano,
                tipo='pedido',
                titulo=f'💰 Pago confirmado {pedido.codigo}',
                detalle=f'Wompi confirmó el pago de ${pedido.total:,.0f}. Ya puedes preparar el pedido.',
                ruta='/pedidos',
                referencia_id=pedido.id,
            )
    elif transaccion['status'] in ('DECLINED', 'ERROR', 'VOIDED'):
        pedido.estado = 'Cancelado'
        pedido.save()
        for detalle in pedido.detalles.all():
            _liberar_reserva(detalle.producto, detalle.cantidad)

    return Response(status=status.HTTP_200_OK)


def _get_nested(data, path):
    """Navega un diccionario anidado usando notación 'a.b.c'"""
    for key in path.split('.'):
        data = data[key]
    return data

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def wompi_integrity(request):
    referencia = request.data.get('reference')
    moneda = request.data.get('currency')

    if not referencia or not moneda:
        return Response(
            {'error': 'Faltan datos para generar la firma'},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        pedido = Pedido.objects.get(codigo=referencia)
    except Pedido.DoesNotExist:
        return Response({'error': 'Pedido no encontrado'}, status=status.HTTP_404_NOT_FOUND)

    usuario_actual = get_usuario_actual(request)
    if usuario_actual is None or usuario_actual.id != pedido.cliente_id:
        return Response({'error': 'No puedes generar el pago de un pedido que no es tuyo.'}, status=status.HTTP_403_FORBIDDEN)

    monto = int(pedido.total * 100)  # el monto real, calculado aquí, no confiamos en lo que mande el navegador

    secreto = os.getenv('WOMPI_INTEGRITY_SECRET')
    if not secreto:
        return Response(
            {'error': 'WOMPI_INTEGRITY_SECRET no configurado'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    cadena = f"{referencia}{monto}{moneda}{secreto}"
    firma = hashlib.sha256(cadena.encode()).hexdigest()

    return Response({'signature': firma})
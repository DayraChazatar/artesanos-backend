# usuarios/views.py
import io
import os
import json
import secrets
import urllib.request
import urllib.error

from rest_framework import viewsets, status
from rest_framework.authtoken.models import Token
from django.contrib.auth.models import User
from rest_framework.decorators import api_view, action, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.conf import settings as django_settings
from django.db.models import Sum, F
from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAuthenticatedOrReadOnly, BasePermission, SAFE_METHODS

# ── Imports de modelos ────────────────────────────────────────────────────────
from .models import (
    Usuario, Categoria, Producto, Notificacion, ContactoIniciado,
    Favorito, Resena, PasswordResetToken,
)
from inventario.models import Kardex, Pedido
from storage_backend import upload_image

# ── Imports de serializers ────────────────────────────────────────────────────
from .serializers import (
    UsuarioSerializer,
    CategoriaSerializer,
    ProductoSerializer,
    CatalogoProductoSerializer,
    KardexSerializer,
    NotificacionSerializer,
    FavoritoSerializer,
    ResenaSerializer,
)

# ── Helper: obtener el Usuario real detrás del token ────────────────────────
def get_usuario_actual(request):
    """
    Devuelve el objeto Usuario correspondiente a quien está autenticado,
    o None si no se encuentra (no debería pasar si el token es válido).
    """
    try:
        return Usuario.objects.get(correo=request.user.username)
    except Usuario.DoesNotExist:
        return None


def _foto_url(usuario):
    """Misma regla que UsuarioSerializer.get_foto_url, para usarla en las
    respuestas de login (que no pasan por ese serializer)."""
    foto = usuario.foto
    return str(foto) if foto and str(foto).startswith('http') else ''

    # ── Permiso: solo el artesano dueño puede editar/borrar su producto ─────────
class EsDuenioDelProducto(BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:  # GET, HEAD, OPTIONS: cualquiera puede ver
            return True
        usuario_actual = get_usuario_actual(request)
        return usuario_actual is not None and obj.artesano_id == usuario_actual.id

# ── Permiso: solo el artesano dueño puede editar/borrar su categoría ────────
class EsDuenioDeCategoria(BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        usuario_actual = get_usuario_actual(request)
        return usuario_actual is not None and obj.artesano_id == usuario_actual.id

# ── Permiso: solo el artesano dueño del producto puede ver/tocar su kardex ──
class EsDuenioDelKardex(BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        usuario_actual = get_usuario_actual(request)
        return usuario_actual is not None and obj.producto.artesano_id == usuario_actual.id

# ── Permiso: solo el propio usuario puede ver/editar/borrar su registro ─────
class EsElMismoUsuario(BasePermission):
    def has_object_permission(self, request, view, obj):
        usuario_actual = get_usuario_actual(request)
        return usuario_actual is not None and usuario_actual.id == obj.id

# ── Usuarios ──────────────────────────────────────────────────────────────────
class UsuarioViewSet(viewsets.ModelViewSet):
    queryset = Usuario.objects.all()
    serializer_class = UsuarioSerializer
    permission_classes = [EsElMismoUsuario]

    def get_permissions(self):
        # El registro (create) sigue abierto a cualquiera; todo lo demás
        # (incluyendo "list", que es lo que usa ?correo=) exige sesión.
        if self.action == 'create':
            return [AllowAny()]
        return [IsAuthenticated(), EsElMismoUsuario()]

    def get_queryset(self):
        correo = self.request.query_params.get('correo')
        usuario_actual = get_usuario_actual(self.request)
        if correo:
            # Solo puedes consultarte a ti mismo por correo, nunca a otro
            # usuario — antes esto exponía nombre/teléfono/bio de cualquiera
            # con solo saber (o adivinar) su correo, sin necesidad de sesión.
            if usuario_actual is not None and usuario_actual.correo == correo:
                return Usuario.objects.filter(pk=usuario_actual.id)
            return Usuario.objects.none()
        if usuario_actual is not None:
            return Usuario.objects.filter(pk=usuario_actual.id)
        return Usuario.objects.none()

    @action(detail=False, methods=['get'], url_path='artesanos')
    def artesanos(self, request):
        qs = Usuario.objects.filter(tipo='artesano')
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    def update(self, request, *args, **kwargs):
        # Permite actualizar la foto de perfil subiendo un archivo real
        # (a Supabase Storage), igual que ya funciona para el artesano —
        # antes el cliente solo la guardaba como base64 en localStorage.
        data = request.data.copy()
        foto = request.FILES.get('foto')
        if foto:
            import uuid
            filename = f"{uuid.uuid4()}_{foto.name}"
            data['foto'] = upload_image(foto, 'perfiles', filename)

        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=data, partial=partial, context={'request': request})
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)


@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    correo   = request.data.get('correo')
    password = request.data.get('password')
    try:
        usuario = Usuario.objects.get(correo=correo)
        if check_password(password, usuario.password):
            auth_user, _ = User.objects.get_or_create(username=correo)
            auth_user.set_password(password)
            auth_user.save()
            token, _ = Token.objects.get_or_create(user=auth_user)
            return Response({
                'success': True,
                'id':      usuario.id,
                'nombre':  usuario.nombre,
                'tipo':    usuario.tipo,
                'token':   token.key,
                'foto_url': _foto_url(usuario),
            })
        return Response({'success': False, 'mensaje': 'Contraseña incorrecta'})
    except Usuario.DoesNotExist:
        return Response({'success': False, 'mensaje': 'Usuario no encontrado'})


# ── Login con Google ───────────────────────────────────────────────────────────
GOOGLE_CLIENT_ID = os.getenv(
    'GOOGLE_CLIENT_ID',
    '845925419316-dnpgshd089pchteb2pvt2b5u55t96cn9.apps.googleusercontent.com',
)


@api_view(['POST'])
@permission_classes([AllowAny])
def login_google(request):
    """
    Recibe el "credential" (id_token JWT) que entrega Google en el frontend,
    lo valida contra los servidores de Google, y crea/vincula el Usuario real
    para poder emitir un token de la app — así el login con Google también
    funciona para carrito, perfil y pedidos, igual que el login normal.
    """
    credential = request.data.get('credential')
    if not credential:
        return Response({'error': 'Falta el token de Google.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        url = f'https://oauth2.googleapis.com/tokeninfo?id_token={credential}'
        with urllib.request.urlopen(url, timeout=6) as resp:
            info = json.loads(resp.read().decode())
    except urllib.error.HTTPError:
        return Response({'error': 'Token de Google inválido o expirado.'}, status=status.HTTP_400_BAD_REQUEST)
    except Exception:
        return Response({'error': 'No se pudo verificar el token de Google.'}, status=status.HTTP_502_BAD_GATEWAY)

    if info.get('aud') != GOOGLE_CLIENT_ID:
        return Response({'error': 'Este token de Google no corresponde a esta aplicación.'}, status=status.HTTP_400_BAD_REQUEST)
    if str(info.get('email_verified')).lower() != 'true':
        return Response({'error': 'Tu correo de Google no está verificado.'}, status=status.HTTP_400_BAD_REQUEST)

    correo = info.get('email')
    nombre = info.get('name') or correo.split('@')[0]

    usuario, creado = Usuario.objects.get_or_create(
        correo=correo,
        defaults={
            'nombre': nombre,
            # Nunca se usa para iniciar sesión (solo Google puede autenticar
            # esta cuenta), pero el campo es obligatorio en el modelo.
            'password': make_password(secrets.token_urlsafe(24)),
            'tipo': 'cliente',
        },
    )

    auth_user, auth_creado = User.objects.get_or_create(username=correo)
    if auth_creado:
        auth_user.set_unusable_password()
        auth_user.save()
    token, _ = Token.objects.get_or_create(user=auth_user)

    return Response({
        'success': True,
        'id':      usuario.id,
        'nombre':  usuario.nombre,
        'correo':  usuario.correo,
        'tipo':    usuario.tipo,
        'token':   token.key,
        'foto_url': _foto_url(usuario),
    })


# ── Recuperar contraseña ────────────────────────────────────────────────────────
@api_view(['POST'])
@permission_classes([AllowAny])
def solicitar_reset_password(request):
    """
    Siempre responde igual, exista o no el correo — evita que alguien use
    esto para descubrir qué correos están registrados en el sistema.
    """
    correo = (request.data.get('correo') or '').strip()
    if not correo:
        return Response({'error': 'Debes indicar un correo.'}, status=status.HTTP_400_BAD_REQUEST)

    respuesta_generica = Response({
        'ok': True,
        'mensaje': 'Si existe una cuenta con ese correo, te enviamos instrucciones para restablecer la contraseña.',
    })

    try:
        usuario = Usuario.objects.get(correo=correo)
    except Usuario.DoesNotExist:
        return respuesta_generica

    # Invalida cualquier enlace anterior sin usar antes de crear uno nuevo.
    PasswordResetToken.objects.filter(usuario=usuario, usado=False).update(usado=True)
    reset_token = PasswordResetToken.objects.create(usuario=usuario)

    frontend_url = getattr(django_settings, 'FRONTEND_URL', 'http://localhost:5173')
    enlace = f'{frontend_url}/restablecer-contrasena/{reset_token.token}'

    try:
        send_mail(
            subject='Recupera tu contraseña — Pakari Shop',
            message=(
                f'Hola {usuario.nombre},\n\n'
                'Recibimos una solicitud para restablecer tu contraseña en Pakari Shop.\n'
                f'Haz clic en el siguiente enlace (válido por 1 hora):\n\n{enlace}\n\n'
                'Si tú no solicitaste esto, puedes ignorar este correo con tranquilidad.'
            ),
            from_email=None,
            recipient_list=[usuario.correo],
            fail_silently=False,
        )
    except Exception:
        # No exponemos el error real de envío al usuario final; queda en
        # los logs del servidor para que el equipo lo revise.
        pass

    return respuesta_generica


@api_view(['POST'])
@permission_classes([AllowAny])
def confirmar_reset_password(request):
    token_valor         = request.data.get('token')
    password_nueva      = request.data.get('password_nueva')
    password_confirmar  = request.data.get('password_confirmar')

    if not all([token_valor, password_nueva, password_confirmar]):
        return Response({'error': 'Todos los campos son obligatorios.'}, status=status.HTTP_400_BAD_REQUEST)
    if password_nueva != password_confirmar:
        return Response({'error': 'Las contraseñas no coinciden.'}, status=status.HTTP_400_BAD_REQUEST)
    if len(password_nueva) < 6:
        return Response({'error': 'La contraseña debe tener al menos 6 caracteres.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        reset_token = PasswordResetToken.objects.select_related('usuario').get(token=token_valor)
    except PasswordResetToken.DoesNotExist:
        return Response({'error': 'El enlace de recuperación no es válido.'}, status=status.HTTP_400_BAD_REQUEST)

    if reset_token.usado:
        return Response({'error': 'Este enlace ya fue utilizado.'}, status=status.HTTP_400_BAD_REQUEST)
    if reset_token.expirado:
        return Response({'error': 'Este enlace expiró. Solicita uno nuevo.'}, status=status.HTTP_400_BAD_REQUEST)

    usuario = reset_token.usuario
    usuario.set_password(password_nueva)
    usuario.save()
    reset_token.usado = True
    reset_token.save(update_fields=['usado'])

    return Response({'ok': True, 'mensaje': 'Contraseña actualizada correctamente. Ya puedes iniciar sesión.'})


@api_view(['POST'])
@permission_classes([AllowAny])
def registro_artesano(request):
    """Registro de nuevo artesano con categoria_id."""
    data = request.data.copy()
    password = data.get('password')
    categoria_id = data.get('categoria_id')

    if not password:
        return Response({'error': 'La contraseña es obligatoria'}, status=status.HTTP_400_BAD_REQUEST)
    if not categoria_id:
        return Response({'error': 'Debes seleccionar una categoría'}, status=status.HTTP_400_BAD_REQUEST)
    if Usuario.objects.filter(correo=data.get('correo')).exists():
        return Response({'error': 'Ya existe un usuario con ese correo'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        categoria = Categoria.objects.get(pk=categoria_id)
    except Categoria.DoesNotExist:
        return Response({'error': 'Categoría no encontrada'}, status=status.HTTP_400_BAD_REQUEST)

    data['tipo'] = 'artesano'

    serializer = UsuarioSerializer(data=data)
    if serializer.is_valid():
        usuario = serializer.save()
        # Asignar la categoría al artesano recién creado
        categoria.artesano = usuario
        categoria.save()
        return Response({
            'success': True,
            'id':      usuario.id,
            'nombre':  usuario.nombre,
            'tipo':    usuario.tipo,
        }, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ── Categorías ────────────────────────────────────────────────────────────────
class CategoriaViewSet(viewsets.ModelViewSet):
    queryset = Categoria.objects.all()
    serializer_class = CategoriaSerializer
    permission_classes = [IsAuthenticated, EsDuenioDeCategoria]
    
    def get_queryset(self):
        usuario_actual = get_usuario_actual(self.request)
        if usuario_actual is None:
            return Categoria.objects.none()
        return Categoria.objects.filter(artesano_id=usuario_actual.id)

    def create(self, request, *args, **kwargs):
        print("🔥 ENTRO AL CREATE")
        print("DATA:", request.data)
        print("FILES:", request.FILES)
    
        imagen = request.FILES.get('imagen')
        data = request.data.copy()
    
        if imagen:
           import uuid
           filename = f"{uuid.uuid4()}_{imagen.name}"
           url = upload_image(imagen, 'productos', filename)
           data['imagen'] = url
    
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    def update(self, request, *args, **kwargs):
        imagen = request.FILES.get('imagen')
        data = request.data.copy()
    
        if imagen:
           import uuid
           filename = f"{uuid.uuid4()}_{imagen.name}"
           url = upload_image(imagen, 'productos', filename)
           data['imagen'] = url
    
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)


# ── Productos ─────────────────────────────────────────────────────────────────
class ProductoViewSet(viewsets.ModelViewSet):
    queryset = Producto.objects.all()
    serializer_class = ProductoSerializer
    permission_classes = [IsAuthenticatedOrReadOnly, EsDuenioDelProducto]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        Producto.objects.filter(pk=instance.pk).update(visitas=F('visitas') + 1)
        instance.refresh_from_db(fields=['visitas'])
        serializer = self.get_serializer(instance)
        return Response(serializer.data)
        
    def create(self, request, *args, **kwargs):
        import uuid
        imagen = request.FILES.get('imagen')
        data = request.data.copy()

        usuario_actual = get_usuario_actual(request)
        if usuario_actual is None or usuario_actual.tipo != 'artesano':
            return Response(
                {'error': 'Solo un artesano autenticado puede crear productos.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        data['artesano'] = usuario_actual.id  # ignora cualquier 'artesano' que venga del frontend

        if imagen:
           filename = f"{uuid.uuid4()}_{imagen.name}"
           url = upload_image(imagen, 'productos', filename)
           data['imagen'] = url
        else:
            data.pop('imagen', None)

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def get_queryset(self):
        qs = super().get_queryset().select_related('categoria', 'artesano')
        artesano_id = self.request.query_params.get('artesano')
        if artesano_id:
            qs = qs.filter(artesano_id=artesano_id)
        return qs


@api_view(['POST'])
@permission_classes([AllowAny])
def asignar_categoria_productos(request):
    """Asigna una categoría a una lista de productos."""
    categoria_id = request.data.get('categoria_id')
    producto_ids = request.data.get('producto_ids', [])

    if not categoria_id:
        return Response({'error': 'categoria_id es obligatorio'}, status=status.HTTP_400_BAD_REQUEST)
    if not producto_ids:
        return Response({'error': 'producto_ids no puede estar vacío'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        categoria = Categoria.objects.get(pk=categoria_id)
    except Categoria.DoesNotExist:
        return Response({'error': 'Categoría no encontrada'}, status=status.HTTP_404_NOT_FOUND)

    actualizados = Producto.objects.filter(pk__in=producto_ids).update(categoria=categoria)
    return Response({'ok': True, 'actualizados': actualizados})


# ── Helper notificaciones ─────────────────────────────────────────────────────
def crear_notificacion(tipo, titulo, detalle, referencia_id=None, ruta=''):
    Notificacion.objects.create(
        tipo=tipo,
        titulo=titulo,
        detalle=detalle,
        referencia_id=referencia_id,
        ruta=ruta,
    )


# ── Kardex ────────────────────────────────────────────────────────────────────
class KardexViewSet(viewsets.ModelViewSet):
    queryset = Kardex.objects.all().order_by('-fecha')
    serializer_class = KardexSerializer
    permission_classes = [IsAuthenticated, EsDuenioDelKardex]

    def get_queryset(self):
        # NOTA: antes existían dos "get_queryset" en esta clase — Python se
        # queda con el último y el primero (que sí filtraba por dueño) nunca
        # se ejecutaba. Eso hacía que /api/kardex/ devolviera el inventario
        # de TODOS los artesanos en vez de solo el del usuario autenticado.
        usuario_actual = get_usuario_actual(self.request)
        if usuario_actual is None:
            return Kardex.objects.none()

        qs = Kardex.objects.filter(
            producto__artesano_id=usuario_actual.id
        ).select_related('producto')

        producto_id = self.request.query_params.get('producto')
        if producto_id:
            qs = qs.filter(producto_id=producto_id)
        return qs.order_by('-fecha')

    def perform_create(self, serializer):
        kardex = serializer.save()
        producto = kardex.producto
        if producto.cantidad <= producto.stock_minimo:
            crear_notificacion(
                tipo='stock',
                titulo='Stock bajo',
                detalle=f'El producto "{producto.nombre}" tiene solo {producto.cantidad} unidades disponibles.',
                referencia_id=producto.id,
                ruta='/inventario',
            )


# ── Helper: validar dueño de los reportes ──────────────────────────────────────
def _artesano_autenticado_o_error(request):
    """
    Devuelve (artesano_id, None) usando siempre el id del usuario autenticado
    — nunca el valor que venga por query param — o (None, Response) si no hay
    una sesión válida. Evita que un artesano descargue el reporte de otro con
    solo cambiar ?artesano= en la URL.
    """
    usuario_actual = get_usuario_actual(request)
    if usuario_actual is None:
        return None, Response({'error': 'No autenticado.'}, status=status.HTTP_403_FORBIDDEN)
    return usuario_actual.id, None


# ── Helper: queryset kardex con filtros ───────────────────────────────────────
def _kardex_filtrado(request, artesano_id):
    """Devuelve el Kardex del artesano dado, aplicando filtros de fecha."""
    desde = request.query_params.get('desde')
    hasta = request.query_params.get('hasta')
    qs = Kardex.objects.filter(producto__artesano_id=artesano_id).select_related('producto').order_by('fecha')
    if desde:
        qs = qs.filter(fecha__date__gte=desde)
    if hasta:
        qs = qs.filter(fecha__date__lte=hasta)
    return qs


# ── Helpers Excel/PDF ─────────────────────────────────────────────────────────
def estilo_excel(ws, headers):
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='B45309')
        cell.alignment = Alignment(horizontal='center')
    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = max_len + 4


def estilo_pdf(elements, titulo, headers, data):
    styles = getSampleStyleSheet()
    elements.append(Paragraph(f'<b>{titulo}</b>', styles['Title']))
    elements.append(Spacer(1, 12))
    tabla = Table([headers] + data)
    tabla.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, 0),  colors.HexColor('#B45309')),
        ('TEXTCOLOR',     (0, 0), (-1, 0),  colors.white),
        ('FONTNAME',      (0, 0), (-1, 0),  'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1, 0),  10),
        ('ROWBACKGROUNDS',(0, 1), (-1, -1), [colors.white, colors.HexColor('#FEF3C7')]),
        ('GRID',          (0, 0), (-1, -1), 0.5, colors.HexColor('#D97706')),
        ('FONTSIZE',      (0, 1), (-1, -1), 9),
        ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elements.append(tabla)


# ── Reportes Productos ────────────────────────────────────────────────────────
@api_view(['GET'])
def reporte_productos_excel(request):
    artesano_id, error = _artesano_autenticado_o_error(request)
    if error:
        return error
    productos = Producto.objects.filter(artesano_id=artesano_id)
    wb = Workbook()
    ws = wb.active
    ws.title = 'Productos'
    headers = ['Código', 'Lote', 'Nombre', 'Categoría', 'Precio neto', 'PVP', 'IVA (%)', 'Descuento', 'Stock', 'Stock mín.', 'Stock máx.', 'Estado']
    for col, h in enumerate(headers, 1):
        ws.cell(row=1, column=col, value=h)
    for p in productos:
        ws.append([
            p.codigo_barra or '—', p.lote or '—', p.nombre,
            p.categoria.nombre if p.categoria else '—',
            float(p.precio_neto),
            float(p.precio_final),
            p.iva,
            f'Sí ({p.valor_descuento}%)' if p.descuento else 'No',
            p.cantidad, p.stock_minimo, p.stock_maximo,
            p.estado_stock,
        ])
    estilo_excel(ws, headers)
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return HttpResponse(buffer, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': 'attachment; filename="productos.xlsx"'})


@api_view(['GET'])
def reporte_productos_pdf(request):
    artesano_id, error = _artesano_autenticado_o_error(request)
    if error:
        return error
    productos = Producto.objects.filter(artesano_id=artesano_id)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))
    elements = []
    headers = ['Código', 'Nombre', 'Categoría', 'Precio neto', 'PVP', 'IVA', 'Stock', 'Mín.', 'Máx.', 'Estado']
    data = [[
        p.codigo_barra or '—', p.nombre,
        p.categoria.nombre if p.categoria else '—',
        f'${float(p.precio_neto):,.0f}',
        f'${float(p.precio_final):,.0f}',
        f'{p.iva}%',
        str(p.cantidad), str(p.stock_minimo), str(p.stock_maximo),
        p.estado_stock,
    ] for p in productos]
    estilo_pdf(elements, 'Reporte de Productos — Pakari Shop', headers, data)
    doc.build(elements)
    buffer.seek(0)
    return HttpResponse(buffer, content_type='application/pdf',
                        headers={'Content-Disposition': 'attachment; filename="productos.pdf"'})


# ── Reportes Inventario ───────────────────────────────────────────────────────
@api_view(['GET'])
def reporte_inventario_excel(request):
    artesano_id, error = _artesano_autenticado_o_error(request)
    if error:
        return error
    productos = Producto.objects.filter(artesano_id=artesano_id)
    wb = Workbook()

    ws = wb.active
    ws.title = 'Stock'
    headers = ['Producto', 'Código', 'Stock actual', 'Stock mínimo', 'Stock máximo', 'Estado']
    for col, h in enumerate(headers, 1):
        ws.cell(row=1, column=col, value=h)
    for p in productos:
        ws.append([p.nombre, p.codigo_barra or '—', p.cantidad, p.stock_minimo, p.stock_maximo, p.estado_stock])
    estilo_excel(ws, headers)

    ws2 = wb.create_sheet(title='Movimientos')
    headers2 = ['Producto', 'Tipo', 'Subtipo', 'Cantidad', 'Stock result.', 'Origen', 'Pedido', 'Fecha', 'Nota']
    for col, h in enumerate(headers2, 1):
        ws2.cell(row=1, column=col, value=h)
    kardex = _kardex_filtrado(request, artesano_id)
    for k in kardex:
        ws2.append([
            k.producto.nombre, k.tipo, k.subtipo or '—',
            k.cantidad, k.stock_resultante,
            k.origen, k.pedido_ref or '—',
            str(k.fecha), k.nota or '—',
        ])
    estilo_excel(ws2, headers2)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return HttpResponse(buffer, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': 'attachment; filename="inventario.xlsx"'})


@api_view(['GET'])
def reporte_inventario_pdf(request):
    artesano_id, error = _artesano_autenticado_o_error(request)
    if error:
        return error
    productos = Producto.objects.filter(artesano_id=artesano_id)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))
    elements = []

    headers = ['Producto', 'Código', 'Stock actual', 'Stock mín.', 'Stock máx.', 'Estado']
    data = [[
        p.nombre, p.codigo_barra or '—',
        str(p.cantidad), str(p.stock_minimo), str(p.stock_maximo),
        p.estado_stock,
    ] for p in productos]
    estilo_pdf(elements, 'Reporte de Inventario — Pakari Shop', headers, data)

    elements.append(Spacer(1, 24))
    headers2 = ['Producto', 'Total entradas', 'Total salidas', 'Neto']
    data2 = []
    for p in productos:
        entradas = Kardex.objects.filter(producto=p, tipo='Entrada').aggregate(t=Sum('cantidad'))['t'] or 0
        salidas  = Kardex.objects.filter(producto=p, tipo='Salida').aggregate(t=Sum('cantidad'))['t'] or 0
        data2.append([p.nombre, f'+{entradas}', f'-{salidas}', str(entradas - salidas)])
    estilo_pdf(elements, 'Resumen de movimientos por producto', headers2, data2)

    doc.build(elements)
    buffer.seek(0)
    return HttpResponse(buffer, content_type='application/pdf',
                        headers={'Content-Disposition': 'attachment; filename="inventario.pdf"'})


# ── Reportes Kardex ───────────────────────────────────────────────────────────
@api_view(['GET'])
def reporte_kardex_excel(request):
    artesano_id, error = _artesano_autenticado_o_error(request)
    if error:
        return error
    kardex = _kardex_filtrado(request, artesano_id)
    wb = Workbook()
    ws = wb.active
    ws.title = 'Movimientos'
    headers = ['Producto', 'Tipo', 'Subtipo', 'Cantidad', 'Stock resultante', 'Precio unit.', 'Origen', 'Pedido ref.', 'Fecha', 'Nota', 'Registrado por']
    for col, h in enumerate(headers, 1):
        ws.cell(row=1, column=col, value=h)
    for k in kardex:
        ws.append([
            k.producto.nombre, k.tipo, k.subtipo or '—',
            k.cantidad, k.stock_resultante,
            float(k.precio_unitario) if k.precio_unitario else '—',
            k.origen, k.pedido_ref or '—',
            str(k.fecha), k.nota or '—', k.creado_por,
        ])
    estilo_excel(ws, headers)
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return HttpResponse(buffer, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': 'attachment; filename="kardex.xlsx"'})


@api_view(['GET'])
def reporte_kardex_pdf(request):
    artesano_id, error = _artesano_autenticado_o_error(request)
    if error:
        return error
    kardex = _kardex_filtrado(request, artesano_id)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))
    elements = []
    headers = ['Producto', 'Tipo', 'Cantidad', 'Stock result.', 'Origen', 'Pedido', 'Fecha', 'Nota']
    data = [[
        k.producto.nombre, k.tipo, str(k.cantidad),
        str(k.stock_resultante), k.origen,
        k.pedido_ref or '—', str(k.fecha), k.nota or '—',
    ] for k in kardex]
    estilo_pdf(elements, 'Historial de Movimientos — Pakari Shop', headers, data)
    doc.build(elements)
    buffer.seek(0)
    return HttpResponse(buffer, content_type='application/pdf',
                        headers={'Content-Disposition': 'attachment; filename="kardex.pdf"'})


# ── Reportes Contable ─────────────────────────────────────────────────────────
@api_view(['GET'])
def reporte_contable_excel(request):
    artesano_id, error = _artesano_autenticado_o_error(request)
    if error:
        return error
    productos = Producto.objects.filter(artesano_id=artesano_id)
    wb = Workbook()
    ws = wb.active
    ws.title = 'Contable'
    headers = ['Producto', 'Precio neto', 'IVA (%)', 'Precio con IVA', 'Descuento', 'Precio final (PVP)', 'Stock', 'Valor inventario (neto)']
    for col, h in enumerate(headers, 1):
        ws.cell(row=1, column=col, value=h)
    for p in productos:
        ws.append([
            p.nombre,
            float(p.precio_neto),
            p.iva,
            round(p.precio_con_iva, 2),
            f'{p.valor_descuento}%' if p.descuento else 'No',
            round(p.precio_final, 2),
            p.cantidad,
            round(float(p.precio_neto) * p.cantidad, 2),
        ])
    estilo_excel(ws, headers)
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return HttpResponse(buffer, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': 'attachment; filename="contable.xlsx"'})


@api_view(['GET'])
def reporte_contable_pdf(request):
    artesano_id, error = _artesano_autenticado_o_error(request)
    if error:
        return error
    productos = Producto.objects.filter(artesano_id=artesano_id)
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))
    elements = []
    headers = ['Producto', 'Precio neto', 'IVA', 'Precio con IVA', 'Precio final (PVP)', 'Stock', 'Valor inventario (neto)']
    data = [[
        p.nombre,
        f'${float(p.precio_neto):,.0f}',
        f'{p.iva}%',
        f'${p.precio_con_iva:,.0f}',
        f'${p.precio_final:,.0f}',
        str(p.cantidad),
        f'${float(p.precio_neto) * p.cantidad:,.0f}',
    ] for p in productos]
    estilo_pdf(elements, 'Reporte Contable — Pakari Shop', headers, data)
    doc.build(elements)
    buffer.seek(0)
    return HttpResponse(buffer, content_type='application/pdf',
                        headers={'Content-Disposition': 'attachment; filename="contable.pdf"'})


# ── Reportes Envíos (pestaña "Referencias") ────────────────────────────────────
def _pedidos_con_guia(usuario_actual, artesano_id):
    """Pedidos con número de guía/referencia registrado, validando que el
    artesano solicitado sea el usuario autenticado."""
    if usuario_actual is None or (artesano_id and str(usuario_actual.id) != str(artesano_id)):
        return None
    return (
        Pedido.objects
        .filter(artesano_id=artesano_id or usuario_actual.id)
        .exclude(numero_guia__isnull=True).exclude(numero_guia='')
        .select_related('cliente')
        .prefetch_related('detalles__producto')
        .order_by('-fecha_envio', '-fecha')
    )


@api_view(['GET'])
def reporte_envios_excel(request):
    artesano_id = request.query_params.get('artesano')
    pedidos = _pedidos_con_guia(get_usuario_actual(request), artesano_id)
    if pedidos is None:
        return Response({'error': 'No puedes descargar el reporte de envíos de otro artesano.'}, status=status.HTTP_403_FORBIDDEN)

    wb = Workbook()
    ws = wb.active
    ws.title = 'Envíos'
    headers = ['Pedido', 'Cliente', 'Producto', 'Cantidad', 'Referencia/Guía', 'Estado', 'Fecha envío', 'Fecha entrega']
    for col, h in enumerate(headers, 1):
        ws.cell(row=1, column=col, value=h)
    for p in pedidos:
        detalles = list(p.detalles.all()) or [None]
        for d in detalles:
            ws.append([
                p.codigo, p.cliente.nombre,
                d.producto.nombre if d else '—', d.cantidad if d else 0,
                p.numero_guia, p.estado,
                str(p.fecha_envio) if p.fecha_envio else '—',
                str(p.fecha_entrega) if p.fecha_entrega else '—',
            ])
    estilo_excel(ws, headers)
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return HttpResponse(buffer, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        headers={'Content-Disposition': 'attachment; filename="envios.xlsx"'})


@api_view(['GET'])
def reporte_envios_pdf(request):
    artesano_id = request.query_params.get('artesano')
    pedidos = _pedidos_con_guia(get_usuario_actual(request), artesano_id)
    if pedidos is None:
        return Response({'error': 'No puedes descargar el reporte de envíos de otro artesano.'}, status=status.HTTP_403_FORBIDDEN)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter))
    elements = []
    headers = ['Pedido', 'Cliente', 'Producto', 'Cant.', 'Referencia/Guía', 'Estado', 'Fecha envío', 'Fecha entrega']
    data = []
    for p in pedidos:
        detalles = list(p.detalles.all()) or [None]
        for d in detalles:
            data.append([
                p.codigo, p.cliente.nombre,
                d.producto.nombre if d else '—', str(d.cantidad) if d else '0',
                p.numero_guia, p.estado,
                str(p.fecha_envio) if p.fecha_envio else '—',
                str(p.fecha_entrega) if p.fecha_entrega else '—',
            ])
    estilo_pdf(elements, 'Reporte de Envíos — Pakari Shop', headers, data)
    doc.build(elements)
    buffer.seek(0)
    return HttpResponse(buffer, content_type='application/pdf',
                        headers={'Content-Disposition': 'attachment; filename="envios.pdf"'})


# ── Notificaciones ────────────────────────────────────────────────────────────
class NotificacionViewSet(viewsets.ModelViewSet):
    queryset = Notificacion.objects.all()
    serializer_class = NotificacionSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['patch'], url_path='leer-todas')
    def leer_todas(self, request):
        Notificacion.objects.filter(leida=False).update(leida=True)
        return Response({'ok': True})

    @action(detail=True, methods=['patch'], url_path='leer')
    def leer(self, request, pk=None):
        notificacion = self.get_object()
        notificacion.leida = True
        notificacion.save()
        return Response({'ok': True})

    @action(detail=False, methods=['get'], url_path='no-leidas')
    def no_leidas(self, request):
        count = Notificacion.objects.filter(leida=False).count()
        return Response({'count': count})


# ── Favoritos ────────────────────────────────────────────────────────────────
class FavoritoViewSet(viewsets.ModelViewSet):
    serializer_class = FavoritoSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        usuario_actual = get_usuario_actual(self.request)
        if usuario_actual is None:
            return Favorito.objects.none()
        return Favorito.objects.filter(cliente_id=usuario_actual.id).select_related('producto', 'producto__artesano')

    def create(self, request, *args, **kwargs):
        usuario_actual = get_usuario_actual(request)
        if usuario_actual is None or usuario_actual.tipo != 'cliente':
            return Response({'error': 'Solo los clientes pueden guardar favoritos.'}, status=status.HTTP_403_FORBIDDEN)

        producto_id = request.data.get('producto')
        existente = Favorito.objects.filter(cliente=usuario_actual, producto_id=producto_id).first()
        if existente:
            # Idempotente: si ya lo tenía guardado, no es un error.
            return Response(self.get_serializer(existente).data, status=status.HTTP_200_OK)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(cliente=usuario_actual)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        usuario_actual = get_usuario_actual(request)
        if usuario_actual is None or instance.cliente_id != usuario_actual.id:
            return Response({'error': 'No puedes eliminar el favorito de otro usuario.'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=['delete'], url_path=r'producto/(?P<producto_id>\d+)')
    def eliminar_por_producto(self, request, producto_id=None):
        """Permite quitar un favorito conociendo solo el id del producto (para el botón ♥ del catálogo)."""
        usuario_actual = get_usuario_actual(request)
        if usuario_actual is None:
            return Response({'error': 'No autenticado.'}, status=status.HTTP_403_FORBIDDEN)
        Favorito.objects.filter(cliente=usuario_actual, producto_id=producto_id).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Reseñas ──────────────────────────────────────────────────────────────────
class ResenaViewSet(viewsets.ModelViewSet):
    queryset = Resena.objects.all().select_related('cliente', 'producto')
    serializer_class = ResenaSerializer

    def get_permissions(self):
        # Cualquiera puede leer reseñas de un producto; solo un cliente
        # autenticado (y dueño de la reseña) puede crear/editar/borrar.
        if self.action in ('list', 'retrieve'):
            return [AllowAny()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = super().get_queryset()
        producto_id = self.request.query_params.get('producto')
        if producto_id:
            qs = qs.filter(producto_id=producto_id)
        if self.request.query_params.get('mias') == 'true':
            usuario_actual = get_usuario_actual(self.request)
            qs = qs.filter(cliente_id=usuario_actual.id if usuario_actual else -1)
        return qs

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def create(self, request, *args, **kwargs):
        usuario_actual = get_usuario_actual(request)
        if usuario_actual is None or usuario_actual.tipo != 'cliente':
            return Response({'error': 'Solo los clientes pueden dejar reseñas.'}, status=status.HTTP_403_FORBIDDEN)
        if Resena.objects.filter(cliente=usuario_actual, producto_id=request.data.get('producto')).exists():
            return Response({'error': 'Ya dejaste una reseña para este producto.'}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(cliente=usuario_actual)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        usuario_actual = get_usuario_actual(request)
        if usuario_actual is None or instance.cliente_id != usuario_actual.id:
            return Response({'error': 'No puedes editar la reseña de otro usuario.'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        usuario_actual = get_usuario_actual(request)
        if usuario_actual is None or instance.cliente_id != usuario_actual.id:
            return Response({'error': 'No puedes eliminar la reseña de otro usuario.'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


# ── Catálogo (solo productos visibles) ───────────────────────────────────────
@api_view(['GET'])
@permission_classes([AllowAny])
def catalogo(request):
    productos = Producto.objects.filter(visible=True).select_related('categoria', 'artesano')

    # Límite opcional (ej. la página de inicio solo necesita 3 "destacados"
    # y antes traía el catálogo completo solo para mostrar tres).
    limite = request.query_params.get('limit')
    if limite:
        try:
            productos = productos[:max(1, int(limite))]
        except ValueError:
            pass

    serializer = CatalogoProductoSerializer(productos, many=True, context={'request': request})
    return Response(serializer.data)


# ── Toggle visibilidad ────────────────────────────────────────────────────────
@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def toggle_visibilidad(request, producto_id):
    try:
        producto = Producto.objects.get(id=producto_id)
    except Producto.DoesNotExist:
        return Response({'error': 'Producto no encontrado'}, status=status.HTTP_404_NOT_FOUND)

    usuario_actual = get_usuario_actual(request)
    if usuario_actual is None or producto.artesano_id != usuario_actual.id:
        return Response({'error': 'No puedes cambiar la visibilidad de un producto que no es tuyo.'}, status=status.HTTP_403_FORBIDDEN)

    producto.visible = not producto.visible
    producto.save()
    return Response({'visible': producto.visible})


# ── Perfil artesano ───────────────────────────────────────────────────────────
@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def perfil_artesano(request, usuario_id):
    try:
        usuario = Usuario.objects.get(pk=usuario_id, tipo='artesano')
    except Usuario.DoesNotExist:
        return Response({'error': 'Artesano no encontrado'}, status=status.HTTP_404_NOT_FOUND)

    usuario_actual = get_usuario_actual(request)
    if usuario_actual is None or usuario_actual.id != usuario.id:
        return Response({'error': 'No tienes permiso para acceder a este perfil.'}, status=status.HTTP_403_FORBIDDEN)

    if request.method == 'GET':
        serializer = UsuarioSerializer(usuario, context={'request': request})
        return Response(serializer.data)

    if request.method == 'PATCH':
        import uuid
        data = request.data.copy()
        foto = request.FILES.get('foto')

        if foto:
            filename = f"{uuid.uuid4()}_{foto.name}"
            url = upload_image(foto, 'perfiles', filename)
            data['foto'] = url

        serializer = UsuarioSerializer(
            usuario, data=data, partial=True,
            context={'request': request}
        )
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

# ── Cambiar contraseña ────────────────────────────────────────────────────────
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cambiar_password(request, usuario_id):
    try:
        usuario = Usuario.objects.get(pk=usuario_id)
    except Usuario.DoesNotExist:
        return Response({'error': 'Usuario no encontrado'}, status=status.HTTP_404_NOT_FOUND)

    usuario_actual = get_usuario_actual(request)
    if usuario_actual is None or usuario_actual.id != usuario.id:
        return Response({'error': 'No tienes permiso para cambiar esta contraseña.'}, status=status.HTTP_403_FORBIDDEN)

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

@api_view(['POST'])
def registrar_contacto(request):
    ContactoIniciado.objects.create(
        artesano_id=request.data.get('artesano_id'),
        cliente_id=request.data.get('cliente_id'),  # puede ser null si no ha iniciado sesión
        producto_id=request.data.get('producto_id'),
    )
    return Response({'ok': True}, status=201)
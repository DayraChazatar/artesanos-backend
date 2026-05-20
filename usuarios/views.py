from rest_framework import viewsets, status
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from django.contrib.auth.hashers import check_password

from .models import Usuario, Categoria, Producto, Kardex
from .serializers import (
    UsuarioSerializer, CategoriaSerializer,
    ProductoSerializer, KardexSerializer,
    CatalogoProductoSerializer,
)


# ── Usuarios ────────────────────────────────────────────────────────────────
class UsuarioViewSet(viewsets.ModelViewSet):
    queryset = Usuario.objects.all()
    serializer_class = UsuarioSerializer

    @action(detail=False, methods=['get'], url_path='artesanos')
    def artesanos(self, request):
        qs = Usuario.objects.filter(tipo='artesano')
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)


@api_view(['POST'])
def login(request):
    correo   = request.data.get('correo')
    password = request.data.get('password')
    try:
        user = Usuario.objects.get(correo=correo)
        if check_password(password, user.password):
            return Response({
                'success': True,
                'id':      user.id,
                'nombre':  user.nombre,
                'tipo':    user.tipo,
            })
        return Response({'success': False, 'mensaje': 'Contraseña incorrecta'})
    except Usuario.DoesNotExist:
        return Response({'success': False, 'mensaje': 'Usuario no encontrado'})


# ── Categorías ───────────────────────────────────────────────────────────────
class CategoriaViewSet(viewsets.ModelViewSet):
    queryset = Categoria.objects.all()
    serializer_class = CategoriaSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        artesano_id = self.request.query_params.get('artesano')
        if artesano_id:
            qs = qs.filter(artesano_id=artesano_id)
        return qs


# ── Productos ────────────────────────────────────────────────────────────────
class ProductoViewSet(viewsets.ModelViewSet):
    queryset = Producto.objects.all()
    serializer_class = ProductoSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        artesano_id = self.request.query_params.get('artesano')
        if artesano_id:
            qs = qs.filter(artesano_id=artesano_id)
        return qs


# ── Kardex ───────────────────────────────────────────────────────────────────
class KardexViewSet(viewsets.ModelViewSet):
    queryset = Kardex.objects.all().order_by('-fecha')
    serializer_class = KardexSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        producto_id = self.request.query_params.get('producto')
        if producto_id:
            qs = qs.filter(producto_id=producto_id)
        return qs


# ── Catálogo (solo productos visibles) ───────────────────────────────────────
@api_view(['GET'])
def catalogo_productos(request):
    productos = Producto.objects.filter(visible=True)

    serializer = CatalogoProductoSerializer(
        productos,
        many=True,
        context={'request': request}
    )

    return Response({
        "debug": "ESTOY_USANDO_CATALOGO_PRODUCTOS",
        "ids_visibles": list(productos.values_list("id", flat=True)),
        "productos": serializer.data
    })
# ── Toggle visibilidad ────────────────────────────────────────────────────────
@api_view(['PATCH'])
def toggle_visibilidad(request, producto_id):
    try:
        producto = Producto.objects.get(id=producto_id)

        visible = request.data.get('visible')

        if visible is None:
            producto.visible = not producto.visible
        else:
            producto.visible = bool(visible)

        producto.save(update_fields=['visible'])

        return Response({
            'id': producto.id,
            'visible': producto.visible
        })

    except Producto.DoesNotExist:
        return Response(
            {'error': 'Producto no encontrado'},
            status=status.HTTP_404_NOT_FOUND
        )
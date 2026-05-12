from rest_framework import viewsets
from rest_framework.decorators import api_view, action
from rest_framework.response import Response
from django.contrib.auth.hashers import check_password
 
from .models import Usuario, Categoria, Producto, Kardex
from .serializers import (
    UsuarioSerializer, CategoriaSerializer,
    ProductoSerializer, KardexSerializer,
)
 
 
# ── Usuarios ────────────────────────────────────────────────────────────────
class UsuarioViewSet(viewsets.ModelViewSet):
    queryset = Usuario.objects.all()
    serializer_class = UsuarioSerializer
 
    @action(detail=False, methods=['get'], url_path='artesanos')
    def artesanos(self, request):
        """Devuelve solo usuarios de tipo artesano."""
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
        """Filtra por artesano si se pasa ?artesano=<id>"""
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
        """Filtra por artesano si se pasa ?artesano=<id>"""
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
        """Filtra por producto si se pasa ?producto=<id>"""
        qs = super().get_queryset()
        producto_id = self.request.query_params.get('producto')
        if producto_id:
            qs = qs.filter(producto_id=producto_id)
        return qs

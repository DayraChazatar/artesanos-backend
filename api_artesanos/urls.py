from django.contrib import admin
from django.urls import path, include
from rest_framework import routers
 
from usuarios.views import (
    UsuarioViewSet, CategoriaViewSet,
    ProductoViewSet, KardexViewSet, login,
)
 
router = routers.DefaultRouter()
router.register(r'usuarios',   UsuarioViewSet)
router.register(r'categorias', CategoriaViewSet)
router.register(r'productos',  ProductoViewSet)
router.register(r'kardex',     KardexViewSet)
 
urlpatterns = [
    path('admin/',     admin.site.urls),
    path('api/',       include(router.urls)),
    path('api/login/', login),
]
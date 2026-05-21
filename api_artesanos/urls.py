# artesanos-backend/api_artesanos/urls.py
from django.contrib import admin
from django.urls import path, include
from rest_framework import routers
from django.conf import settings
from django.conf.urls.static import static

from usuarios.views import (
    UsuarioViewSet,
    CategoriaViewSet,
    ProductoViewSet,
    KardexViewSet,
    NotificacionViewSet,
    login,
    registro_artesano,
    catalogo_productos,
    toggle_visibilidad,
    perfil_artesano,
    cambiar_password,
    asignar_categoria_productos,
    reporte_productos_excel, reporte_productos_pdf,
    reporte_inventario_excel, reporte_inventario_pdf,
    reporte_kardex_excel, reporte_kardex_pdf,
    reporte_contable_excel, reporte_contable_pdf,
)

router = routers.DefaultRouter()
router.register(r'usuarios',       UsuarioViewSet)
router.register(r'categorias',     CategoriaViewSet)
router.register(r'productos',      ProductoViewSet)
router.register(r'kardex',         KardexViewSet)
router.register(r'notificaciones', NotificacionViewSet)

urlpatterns = [
    path('admin/',                                           admin.site.urls),
    path('api/login/',                                       login),
    path('api/registro-artesano/',                           registro_artesano),
    path('api/catalogo/',                                    catalogo_productos),
    path('api/productos/<int:producto_id>/visibilidad/',     toggle_visibilidad),
    path('api/asignar-categorias/',                          asignar_categoria_productos),
    path('api/',                                             include(router.urls)),
    path('api/inventario/',                                  include('inventario.urls')),
    path('api/reportes/productos/excel/',                    reporte_productos_excel),
    path('api/reportes/productos/pdf/',                      reporte_productos_pdf),
    path('api/reportes/inventario/excel/',                   reporte_inventario_excel),
    path('api/reportes/inventario/pdf/',                     reporte_inventario_pdf),
    path('api/reportes/kardex/excel/',                       reporte_kardex_excel),
    path('api/reportes/kardex/pdf/',                         reporte_kardex_pdf),
    path('api/reportes/contable/excel/',                     reporte_contable_excel),
    path('api/reportes/contable/pdf/',                       reporte_contable_pdf),
    path('api/perfil/artesano/<int:usuario_id>/',            perfil_artesano),
    path('api/perfil/cambiar-password/<int:usuario_id>/',    cambiar_password),
]

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
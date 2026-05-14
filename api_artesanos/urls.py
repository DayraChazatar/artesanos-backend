from django.contrib import admin
from django.urls import path, include
from rest_framework import routers

from usuarios.views import (
    UsuarioViewSet, CategoriaViewSet,
    ProductoViewSet, KardexViewSet, login,
    reporte_productos_excel, reporte_productos_pdf,
    reporte_inventario_excel, reporte_inventario_pdf,
    reporte_kardex_excel, reporte_kardex_pdf,
    reporte_contable_excel, reporte_contable_pdf,
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

    # ── Reportes ──────────────────────────────────────────────────────────
    path('api/reportes/productos/excel/', reporte_productos_excel),
    path('api/reportes/productos/pdf/',   reporte_productos_pdf),
    path('api/reportes/inventario/excel/', reporte_inventario_excel),
    path('api/reportes/inventario/pdf/',   reporte_inventario_pdf),
    path('api/reportes/kardex/excel/',    reporte_kardex_excel),
    path('api/reportes/kardex/pdf/',      reporte_kardex_pdf),
    path('api/reportes/contable/excel/',  reporte_contable_excel),
    path('api/reportes/contable/pdf/',    reporte_contable_pdf),
]
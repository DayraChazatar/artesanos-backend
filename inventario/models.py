# inventario/models.py
from django.db import models

from django.db import models

 
 
ESTADO_CHOICES = [
    ('Pendiente',             'Pendiente'),
    ('En proceso',            'En proceso'),
    ('Enviado',               'Enviado'),
    ('Entregado',             'Entregado'),
    ('Cancelado',             'Cancelado'),
    ('Devolucion',            'Devolucion'),
    ('Devolucion solicitada', 'Devolucion solicitada'),
    ('Devuelto',              'Devuelto'),
    ('Rechazado',             'Rechazado'),
]
 
 
class Pedido(models.Model):
    """Cabecera del pedido.
 
    • cliente  → FK a usuarios.Usuario (tipo='cliente')
    • artesano → FK a usuarios.Usuario (tipo='artesano')
      Se asigna automáticamente desde el primer DetallePedido.
    """
    codigo    = models.CharField(max_length=20, unique=True, editable=False)
    cliente   = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.PROTECT,
        related_name='pedidos_cliente',
    )
    artesano  = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.PROTECT,
        related_name='pedidos_artesano',
        null=True, blank=True,
    )
    estado    = models.CharField(max_length=30, choices=ESTADO_CHOICES, default='Pendiente')
    total     = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    direccion = models.TextField(blank=True, default='')
    telefono  = models.CharField(max_length=20, blank=True, default='')
    fecha     = models.DateTimeField(auto_now_add=True)
    updated   = models.DateTimeField(auto_now=True)
 
    class Meta:
        ordering = ['-fecha']
 
    def __str__(self):
        return f'{self.codigo} — {self.estado}'
 
    def save(self, *args, **kwargs):
        # Genera código tipo PED-00042 la primera vez
        if not self.codigo:
            super().save(*args, **kwargs)
            self.codigo = f'PED-{self.pk:05d}'
            Pedido.objects.filter(pk=self.pk).update(codigo=self.codigo)
        else:
            super().save(*args, **kwargs)
 
 
class DetallePedido(models.Model):
    """Línea de detalle: un producto dentro de un pedido."""
    pedido   = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name='detalles')
    producto = models.ForeignKey(
        'usuarios.Producto',
        on_delete=models.PROTECT,
        related_name='detalles_pedido',
    )
    cantidad = models.PositiveIntegerField()
    precio   = models.DecimalField(max_digits=12, decimal_places=2)  # precio al momento de compra
 
    class Meta:
        ordering = ['id']
 
    def __str__(self):
        return f'{self.pedido.codigo} · {self.producto.nombre} x{self.cantidad}'
 
    @property
    def subtotal(self):
        return self.precio * self.cantidad
 

class Kardex(models.Model):

    TIPO_CHOICES = [
        ('Entrada',    'Entrada'),
        ('Salida',     'Salida'),
        ('Ajuste',     'Ajuste'),
        ('Devolucion', 'Devolución'),
    ]

    SUBTIPO_CHOICES = [
        ('stock_inicial',      'Stock inicial'),
        ('reposicion',         'Reposición'),
        ('ajuste_manual',      'Ajuste manual'),
        ('devolucion_cliente', 'Devolución de cliente'),
        ('venta',              'Venta'),
        ('cancelacion',        'Cancelación de pedido'),   # ← NUEVO
        ('reserva',            'Reserva de pedido'),       # ← NUEVO (trazabilidad)
    ]

    ORIGEN_CHOICES = [
        ('automatico', 'Automático'),
        ('manual',     'Manual'),
    ]

    producto = models.ForeignKey(
        'usuarios.Producto',
        on_delete=models.PROTECT,
        related_name='movimientos',
    )

    # Referencia al pedido (código legible, ej: PED-0001)
    pedido_ref = models.CharField(
        max_length=50, null=True, blank=True,
        help_text="Número del pedido relacionado, ej: PED-0001"
    )

    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    subtipo = models.CharField(
        max_length=30, choices=SUBTIPO_CHOICES,
        null=True, blank=True
    )
    origen = models.CharField(
        max_length=20, choices=ORIGEN_CHOICES,
        default='manual'
    )
    cantidad = models.PositiveIntegerField(
        help_text="Siempre positivo. El tipo indica si es entrada o salida."
    )
    stock_resultante = models.IntegerField(
        help_text="Stock del producto justo después de este movimiento."
    )
    precio_unitario = models.DecimalField(
        max_digits=12, decimal_places=2,
        null=True, blank=True,
        help_text="PVP del producto al momento del movimiento."
    )
    fecha = models.DateField()
    nota = models.TextField(blank=True, default='')

    creado_por = models.CharField(
        max_length=150, default='Sistema',
        help_text="Nombre del usuario o 'Sistema' si fue automático."
    )
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-creado_en']
        verbose_name = 'Movimiento de inventario'
        verbose_name_plural = 'Movimientos de inventario'

    def __str__(self):
        return f"{self.tipo} | {self.producto} | {self.cantidad} uds. | {self.fecha}"
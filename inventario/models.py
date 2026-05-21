# inventario/models.py

from django.db import models
from django.utils.timezone import now


# ─────────────────────────────────────────────────────────────
# ESTADOS DEL PEDIDO
# ─────────────────────────────────────────────────────────────
ESTADO_CHOICES = [
    ('Pendiente', 'Pendiente'),
    ('En proceso', 'En proceso'),
    ('Enviado', 'Enviado'),
    ('Entregado', 'Entregado'),

    ('Cancelado', 'Cancelado'),

    ('Devolucion solicitada', 'Devolucion solicitada'),
    ('Devolucion aprobada', 'Devolucion aprobada'),
    ('Devolucion rechazada', 'Devolucion rechazada'),

    ('Devuelto', 'Devuelto'),
]


# ─────────────────────────────────────────────────────────────
# PEDIDO
# ─────────────────────────────────────────────────────────────

class Pedido(models.Model):
    """
    Cabecera principal del pedido.
    """

    codigo = models.CharField(
        max_length=20,
        unique=True,
        editable=False
    )

    cliente = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.PROTECT,
        related_name='pedidos_cliente',
        limit_choices_to={'tipo': 'cliente'}
    )

    artesano = models.ForeignKey(
        'usuarios.Usuario',
        on_delete=models.PROTECT,
        related_name='pedidos_artesano',
        limit_choices_to={'tipo': 'artesano'},
        null=True,
        blank=True,
    )

    estado = models.CharField(
        max_length=30,
        choices=ESTADO_CHOICES,
        default='Pendiente'
    )

    total = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    direccion = models.TextField(
        blank=True,
        default=''
    )

    telefono = models.CharField(
        max_length=20,
        blank=True,
        default=''
    )

    # ─────────────────────────────────────────
    # GUÍA Y ENVÍO
    # ─────────────────────────────────────────

    numero_guia = models.CharField(
        max_length=50,
        null=True,
        blank=True
    )

    transportadora = models.CharField(
        max_length=100,
        default='Pakari Express',
        blank=True
    )

    fecha_envio = models.DateTimeField(
        null=True,
        blank=True
    )

    fecha_entrega = models.DateTimeField(
        null=True,
        blank=True
    )

    # ─────────────────────────────────────────
    # FECHAS
    # ─────────────────────────────────────────

    fecha = models.DateTimeField(auto_now_add=True)

    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-fecha']

    def __str__(self):
        return f'{self.codigo} — {self.estado}'

    # ─────────────────────────────────────────
    # GENERAR CÓDIGO PEDIDO
    # ─────────────────────────────────────────

    def save(self, *args, **kwargs):

        creando = self.pk is None

        super().save(*args, **kwargs)

        # Código pedido
        if creando and not self.codigo:
            self.codigo = f'PED-{self.pk:05d}'
            Pedido.objects.filter(pk=self.pk).update(
                codigo=self.codigo
            )

        # Generar guía automática
        if (
            self.estado == 'Enviado'
            and not self.numero_guia
        ):
            self.numero_guia = f'GUIA-PS-{self.pk:06d}'
            self.fecha_envio = now()

            Pedido.objects.filter(pk=self.pk).update(
                numero_guia=self.numero_guia,
                fecha_envio=self.fecha_envio
            )


# ─────────────────────────────────────────────────────────────
# DETALLE PEDIDO
# ─────────────────────────────────────────────────────────────

class DetallePedido(models.Model):
    """
    Productos contenidos dentro del pedido.
    """

    pedido = models.ForeignKey(
        Pedido,
        on_delete=models.CASCADE,
        related_name='detalles'
    )

    producto = models.ForeignKey(
        'usuarios.Producto',
        on_delete=models.PROTECT,
        related_name='detalles_pedido',
    )

    cantidad = models.PositiveIntegerField()

    precio = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.pedido.codigo} · {self.producto.nombre} x{self.cantidad}'

    @property
    def subtotal(self):
        return self.precio * self.cantidad


# ─────────────────────────────────────────────────────────────
# DEVOLUCIONES
# ─────────────────────────────────────────────────────────────

class Devolucion(models.Model):

    ESTADOS_DEVOLUCION = [
        ('Pendiente', 'Pendiente'),
        ('Aprobada', 'Aprobada'),
        ('Rechazada', 'Rechazada'),
    ]

    pedido = models.OneToOneField(
        Pedido,
        on_delete=models.CASCADE,
        related_name='devolucion'
    )

    motivo = models.TextField()

    respuesta_artesano = models.TextField(
        blank=True,
        default=''
    )

    estado = models.CharField(
        max_length=20,
        choices=ESTADOS_DEVOLUCION,
        default='Pendiente'
    )

    fecha_solicitud = models.DateTimeField(
        auto_now_add=True
    )

    fecha_respuesta = models.DateTimeField(
        null=True,
        blank=True
    )

    class Meta:
        ordering = ['-fecha_solicitud']

    def __str__(self):
        return f'Devolución {self.pedido.codigo} - {self.estado}'


# ─────────────────────────────────────────────────────────────
# KARDEX
# ─────────────────────────────────────────────────────────────

class Kardex(models.Model):

    TIPO_CHOICES = [
        ('Entrada', 'Entrada'),
        ('Salida', 'Salida'),
        ('Ajuste', 'Ajuste'),
        ('Devolucion', 'Devolución'),
    ]

    SUBTIPO_CHOICES = [
        ('stock_inicial', 'Stock inicial'),
        ('reposicion', 'Reposición'),
        ('ajuste_manual', 'Ajuste manual'),
        ('devolucion_cliente', 'Devolución de cliente'),

        ('venta', 'Venta'),

        ('cancelacion', 'Cancelación de pedido'),

        ('reserva', 'Reserva de pedido'),
    ]

    ORIGEN_CHOICES = [
        ('automatico', 'Automático'),
        ('manual', 'Manual'),
    ]

    producto = models.ForeignKey(
        'usuarios.Producto',
        on_delete=models.PROTECT,
        related_name='movimientos',
    )

    pedido_ref = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text='Número del pedido relacionado'
    )

    tipo = models.CharField(
        max_length=20,
        choices=TIPO_CHOICES
    )

    subtipo = models.CharField(
        max_length=30,
        choices=SUBTIPO_CHOICES,
        null=True,
        blank=True
    )

    origen = models.CharField(
        max_length=20,
        choices=ORIGEN_CHOICES,
        default='manual'
    )

    cantidad = models.PositiveIntegerField()

    stock_resultante = models.IntegerField()

    precio_unitario = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True
    )

    fecha = models.DateField()

    nota = models.TextField(
        blank=True,
        default=''
    )

    creado_por = models.CharField(
        max_length=150,
        default='Sistema'
    )

    creado_en = models.DateTimeField(
        auto_now_add=True
    )

    class Meta:
        ordering = ['-creado_en']
        verbose_name = 'Movimiento de inventario'
        verbose_name_plural = 'Movimientos de inventario'

    def __str__(self):
        return f"{self.tipo} | {self.producto} | {self.cantidad} uds."
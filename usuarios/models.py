from django.db import models
from django.contrib.auth.hashers import make_password, check_password
   

class Usuario(models.Model):
    TIPO = (
        ('cliente', 'Cliente'),
        ('artesano', 'Artesano'),
    )

    nombre = models.CharField(max_length=255)
    correo = models.EmailField(unique=True)
    password = models.CharField(max_length=255)

    # Campos opcionales (solo para artesano)
    telefono = models.CharField(max_length=20, blank=True, null=True)
    especialidad = models.CharField(max_length=255, blank=True, null=True)
    biografia = models.TextField(blank=True, null=True)
    foto = models.ImageField(upload_to='perfiles/', blank=True, null=True)
    foto = models.ImageField(upload_to='perfiles/', blank=True, null=True)
    tipo = models.CharField(max_length=10, choices=TIPO)

    def __str__(self):
        return f"{self.nombre} ({self.tipo})"

    def set_password(self, raw_password):
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self.password)


class Categoria(models.Model):
    nombre      = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True, null=True)
    artesano = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='categorias',
        limit_choices_to={'tipo': 'artesano'}
    )

    def __str__(self):
        return self.nombre
    

    def __str__(self):
        return self.nombre


class Producto(models.Model):

    IVA_OPCIONES = (
        (0, '0% — Excluido'),
        (5, '5%'),
        (19, '19%'),
    )

    cantidad_reservada = models.IntegerField(
        default=0,
        help_text='Unidades reservadas por pedidos en estado Pendiente.'
    )

    precio_pvp = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Precio de venta al público.'
    )

    # ── Identificación ───────────────────────────────────────────────────
    codigo_barra = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
        null=True,
        verbose_name='Código de barra / QR'
    )

    lote = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name='Lote'
    )

    # ── Información básica ───────────────────────────────────────────────
    nombre = models.CharField(max_length=150)

    imagen = models.ImageField(
        upload_to='productos/',
        null=True,
        blank=True
    )
    
    categoria = models.ForeignKey(
        'Categoria',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='productos'
    )
    
    precio_neto = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    iva = models.IntegerField(
        choices=IVA_OPCIONES,
        default=0
    )

    descuento = models.BooleanField(default=False)

    valor_descuento = models.PositiveIntegerField(
        default=0,
        verbose_name='Descuento (%)'
    )

    artesano = models.ForeignKey(
        Usuario,
        on_delete=models.CASCADE,
        related_name='productos',
        limit_choices_to={'tipo': 'artesano'}
    )

    # ── Visibilidad ──────────────────────────────────────────────────────
    visible = models.BooleanField(default=True, verbose_name='Visible en catálogo')

    # ── Stock ────────────────────────────────────────────────────────────
    cantidad = models.PositiveIntegerField(
        default=0,
        verbose_name='Stock actual'
    )

    stock_minimo = models.PositiveIntegerField(
        default=0,
        verbose_name='Stock mínimo'
    )

    stock_maximo = models.PositiveIntegerField(
        default=0,
        verbose_name='Stock máximo'
    )

    # ── Propiedades ──────────────────────────────────────────────────────
    #@property
    #def categoria(self):
       # """La categoría siempre viene del artesano."""
       # return self.artesano.categoria

    def __str__(self):
        return f"{self.nombre} ({self.artesano.categoria})"
    @property
    def cantidad_disponible(self):
        return max(0, self.cantidad - self.cantidad_reservada)

    @property
    def precio_con_iva(self):
        return float(self.precio_neto) * (1 + self.iva / 100)

    @property
    def precio_final(self):
        if self.precio_pvp:
            base = float(self.precio_pvp)
        else:
            base = float(self.precio_neto) * (1 + self.iva / 100)
        if self.descuento and self.valor_descuento > 0:
            return base * (1 - self.valor_descuento / 100)
        return base

    @property
    def estado_stock(self):
        if self.cantidad <= self.stock_minimo:
            return 'bajo'
        if self.stock_maximo > 0 and self.cantidad >= self.stock_maximo:
            return 'maximo'
        return 'normal'

    def __str__(self):
        return self.nombre


class Notificacion(models.Model):
    TIPOS = [
        ('pedido', 'Pedido'),
        ('stock', 'Stock'),
        ('sistema', 'Sistema'),
    ]
    tipo          = models.CharField(max_length=20, choices=TIPOS)
    titulo        = models.CharField(max_length=100)
    detalle       = models.TextField()
    leida         = models.BooleanField(default=False)
    fecha         = models.DateTimeField(auto_now_add=True)
    referencia_id = models.IntegerField(null=True, blank=True)
    ruta          = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ['-fecha']

    def __str__(self):
        return f"[{self.tipo}] {self.titulo}"
from django.core.management.base import BaseCommand
from inventario.services import liberar_pedidos_wompi_abandonados


class Command(BaseCommand):
    help = (
        'Cancela los pedidos con Wompi que llevan más de una hora en '
        '"Pago pendiente" sin confirmación, y libera el stock que tenían '
        'reservado. Ya se ejecuta solo al crear un pedido y al cargar el '
        'catálogo — este comando es opcional, por si prefieren programarlo '
        'aparte con un cron real en el servidor.'
    )

    def handle(self, *args, **options):
        liberar_pedidos_wompi_abandonados()
        self.stdout.write(self.style.SUCCESS('Listo.'))

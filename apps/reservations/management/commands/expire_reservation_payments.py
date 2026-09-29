from django.core.management.base import BaseCommand
from apps.reservations.services import expire_reservations

class Command(BaseCommand):
    help = 'Expira reservas sin pago enviado; conserva pagos por verificar.'
    def handle(self, **options):
        self.stdout.write(f"Reservas expiradas: {expire_reservations('AWAITING_PAYMENT')}")

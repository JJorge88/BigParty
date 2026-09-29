from django.core.management.base import BaseCommand
from apps.reservations.services import expire_reservations

class Command(BaseCommand):
    help = 'Expira solicitudes sin revisar cuyo plazo venció.'
    def handle(self, **options):
        self.stdout.write(f"Reservas expiradas: {expire_reservations('PENDING_REVIEW')}")

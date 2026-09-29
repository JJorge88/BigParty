from django.core.management.base import BaseCommand
from apps.events.services import expire_event_purchases

class Command(BaseCommand):
    help = 'Libera compras de evento sin comprobante cuyo plazo venció.'

    def handle(self, *args, **options):
        self.stdout.write(f'{expire_event_purchases()} compras expiradas.')

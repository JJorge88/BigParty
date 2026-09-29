from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from apps.venues.models import Area
from apps.printing.models import Printer


class Command(BaseCommand):
    help = 'Crea las cuatro rutas iniciales sin sobrescribir configuración ni inventar hosts.'

    @transaction.atomic
    def handle(self, *args, **options):
        for slug, code, name in [('sport-bar','BAR-SPORT','Barra 1'),('discoteca','BAR-DISCO','Barra 2'),('premium','BAR-PREMIUM','Barra 3')]:
            area = Area.objects.filter(slug=slug).first()
            if not area:
                raise CommandError(f'Falta el área {slug}; ejecuta primero seed_bigparty_defaults.')
            Printer.objects.get_or_create(code=code, defaults={'name':name,'printer_type':'BAR','area':area})
        Printer.objects.get_or_create(code='KITCHEN', defaults={'name':'Cocina','printer_type':'KITCHEN'})
        self.stdout.write(self.style.SUCCESS('Rutas de impresión listas; configuración existente conservada.'))

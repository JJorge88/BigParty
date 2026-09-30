from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

class Command(BaseCommand):
    help = 'Inicializa defaults e identidad; no crea usuarios, migra, borra ni sobrescribe.'
    @transaction.atomic
    def handle(self, *args, **options):
        if settings.DEPLOYMENT_MODE != 'local_node':
            raise CommandError('Requiere modo local_node.')
        for command in ('seed_bigparty_defaults','seed_catalog_defaults','seed_cash_defaults','seed_printer_defaults','init_local_node'):
            call_command(command, stdout=self.stdout)
        self.stdout.write('Preparación completada. Ejecuta collectstatic y check_local_node.')

from django.core.management.base import BaseCommand,CommandError
from apps.sync.worker import sync_once
from apps.sync.exceptions import SyncError

class Command(BaseCommand):
    help='Envía y recibe un lote, procesa comandos y confirma contacto.'
    def handle(self,*args,**options):
        try:result=sync_once()
        except SyncError as exc:raise CommandError(exc.code) from None
        self.stdout.write('Sync deshabilitado.' if result.get('disabled') else f"Sync completado: {result['pushed']} enviados, {result['pulled']} recibidos.")

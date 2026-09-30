from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from apps.cash.models import BusinessDay
from apps.core.ops.backups import backup_full,copy_secondary,root
from apps.core.ops.files import atomic_json
import json
class Command(BaseCommand):
    help='Backup postcierre separado del POS, idempotente por fecha de cierre.'
    def handle(self,*args,**options):
        day=BusinessDay.objects.filter(status='CLOSED').order_by('-closed_at').first()
        if not day:self.stdout.write('Sin jornada cerrada.');return
        key=str(day.pk)+':'+day.closed_at.isoformat();marker=root()/'logs'/'after-day.json'
        if marker.exists() and json.loads(marker.read_text()).get('closure')==key:
            self.stdout.write('Cierre ya respaldado.');return
        manifest=backup_full()
        if settings.BACKUP_SECONDARY_ROOT:copy_secondary(manifest)
        atomic_json(marker,{'closure':key,'manifest':manifest.name})
        self.stdout.write('Backup postcierre terminado.')

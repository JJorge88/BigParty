"""For the OS scheduler; bounded, no deletion or automatic restoration."""
from datetime import datetime, timezone
from django.core.management.base import BaseCommand
from apps.core.ops.backups import root, read_manifest, backup_full
from apps.core.ops.recovery import status


class Command(BaseCommand):
    help = 'Crea una copia completa si la última tiene más de cuatro horas; no borra copias.'

    def handle(self, *args, **options):
        if status()['active']:
            self.stdout.write('Respaldo programado suspendido durante recuperación.'); return
        latest = None
        for path in (root() / 'manifests').glob('*-full.json'):
            try:
                created = datetime.fromisoformat(read_manifest(path)['created_at'])
                latest = max(latest, created) if latest else created
            except Exception:
                continue
        if latest and (datetime.now(timezone.utc) - latest).total_seconds() < 4 * 3600:
            self.stdout.write('Respaldo reciente disponible.'); return
        self.stdout.write('Respaldo verificado: ' + backup_full().name)

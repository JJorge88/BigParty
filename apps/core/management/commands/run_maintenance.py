from datetime import datetime,timezone
from pathlib import Path
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand,CommandError
from apps.core.ops.recovery import status
class Command(BaseCommand):
    help='Mantenimiento idempotente por autoridad; no imprime, no purga historial, no VACUUM FULL.'
    def handle(self,*args,**options):
        if status()['active']:raise CommandError('RECOVERY_MODE: mantenimiento mutador suspendido.')
        commands=[]
        if settings.DEPLOYMENT_MODE=='cloud' or not settings.SYNC_ENABLED:
            commands+=['expire_reservation_holds','expire_reservation_payments','expire_event_purchases']
        if settings.DEPLOYMENT_MODE!='cloud':commands+=['recover_stale_print_jobs']
        for name in commands:call_command(name,stdout=self.stdout)
        # Only old counter JSON; stable lock files are retained to avoid inode lock races.
        from apps.core.ops.locking import file_lock
        import time
        folder=Path(settings.OPERATIONS_STATE_ROOT)/'rate-limits'
        removed=0
        for path in folder.glob('*.json'):
            if len(path.stem)!=64 or any(c not in '0123456789abcdef' for c in path.stem):continue
            try:
                with file_lock(path.with_suffix('.lock')):
                    if path.exists() and time.time()-path.stat().st_mtime>86400:
                        path.unlink();removed+=1
            except OSError:continue
        self.stdout.write(f'Mantenimiento completo. Contadores temporales vencidos: {removed}.')

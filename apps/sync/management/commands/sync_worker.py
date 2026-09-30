import time
from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from django.db import connections
from apps.sync.worker import sync_once,backoff
from apps.sync.exceptions import SyncError
from apps.sync.models import SyncRuntimeState

class Command(BaseCommand):
    help='Proceso independiente del POS; lotes con timeout y backoff limitado.'
    def handle(self,*args,**options):
        if not settings.SYNC_ENABLED:
            self.stdout.write('Sync deshabilitado.');return
        if settings.DEPLOYMENT_MODE!='local_node':raise CommandError('LOCAL_WORKER_ONLY')
        failures=0
        try:
            while True:
                try:sync_once();failures=0
                except SyncError:failures+=1
                delay=backoff(max(0,failures-1)) if failures else settings.SYNC_INTERVAL_SECONDS
                end=time.monotonic()+delay
                while time.monotonic()<end:
                    time.sleep(min(1,max(0,end-time.monotonic())))
                    # A manual request never defeats outage backoff.
                    if not failures and SyncRuntimeState.objects.filter(pk=1,sync_requested=True).exists():break
                connections.close_all()
        except KeyboardInterrupt:return

from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from django.utils import timezone
from apps.sync.models import SyncOutboxEvent,SyncInboxEvent

class Command(BaseCommand):
    help='Vuelve a habilitar eventos fallidos; no modifica datos de negocio.'
    def handle(self,*args,**options):
        from apps.core.ops.recovery import status
        if status()["active"]:raise CommandError("RECOVERY_MODE")
        self.retry()

    @transaction.atomic
    def retry(self):
        outbound=SyncOutboxEvent.objects.filter(status='FAILED').update(status='PENDING',last_error='',available_at=timezone.now())
        inbound=SyncInboxEvent.objects.filter(status='FAILED').update(status='DEFERRED',error='')
        self.stdout.write(f'Reintento habilitado: {outbound} salientes / {inbound} entrantes.')

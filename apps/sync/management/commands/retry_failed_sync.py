from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from apps.sync.models import SyncOutboxEvent,SyncInboxEvent

class Command(BaseCommand):
    help='Vuelve a habilitar eventos fallidos; no modifica datos de negocio.'
    @transaction.atomic
    def handle(self,*args,**options):
        outbound=SyncOutboxEvent.objects.filter(status='FAILED').update(status='PENDING',last_error='',available_at=timezone.now())
        inbound=SyncInboxEvent.objects.filter(status='FAILED').update(status='DEFERRED',error='')
        self.stdout.write(f'Reintento habilitado: {outbound} salientes / {inbound} entrantes.')

import json
import uuid
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand,CommandError
from django.db import transaction
from apps.sync.registry import REGISTRY
from apps.sync.models import SyncRuntimeState,SyncIdentity,SyncOutboxEvent,SyncInboxEvent
from apps.sync.services import source_gate,capture_objects,own_authority,origin
from apps.sync.worker import SyncClient,handshake,pull_once,sync_once
from apps.sync.exceptions import SyncError

class Command(BaseCommand):
    help='Baseline explícito y reanudable. Requiere --confirm; nunca borra datos.'
    def add_arguments(self,parser):
        parser.add_argument('--confirm',action='store_true')
        parser.add_argument('--identity-map',help='JSON revisado: model_label, object_pk local, entity_uuid compartido. Solo registros aún sin identidad.')
    def handle(self,*args,**options):
        if not options['confirm']:raise CommandError('Revisa authority/datos y vuelve a ejecutar con --confirm.')
        if not settings.SYNC_ENABLED:raise CommandError('SYNC_DISABLED')
        try:self.bootstrap(options)
        except SyncError as exc:raise CommandError(exc.code) from None
    def bootstrap(self,options):
        if options['identity_map']:
            data=json.loads(Path(options['identity_map']).read_text())
            with transaction.atomic():
                source_gate()
                for row in data:
                    if set(row)!={'model_label','object_pk','entity_uuid'} or row['model_label'] not in REGISTRY:raise CommandError('Mapa inválido.')
                    spec=REGISTRY[row['model_label']]
                    if not spec.model.objects.filter(pk=row['object_pk']).exists():raise CommandError('Entidad inexistente.')
                    existing=SyncIdentity.objects.filter(model_label=spec.label,object_pk=str(row['object_pk'])).first()
                    if existing and str(existing.entity_uuid)!=row['entity_uuid']:raise CommandError('Identidad ya asignada; no se reemplaza.')
                    if not existing:SyncIdentity.objects.create(model_label=spec.label,object_pk=str(row['object_pk']),entity_uuid=uuid.UUID(row['entity_uuid']),origin=('cloud' if spec.authority=='cloud' else (settings.SYNC_NODE_UUID if own_authority()=='cloud' else origin())))
        state,_=SyncRuntimeState.objects.get_or_create(pk=1)
        if own_authority()=='local':
            client=SyncClient(origin());handshake(client)
            state.bootstrap_phase='CLOUD_BASELINE';state.save(update_fields=['bootstrap_phase'])
            while pull_once(client):pass
        state.bootstrap_phase='OWN_BASELINE';state.save(update_fields=['bootstrap_phase'])
        for spec in REGISTRY.values():
            if spec.authority!=own_authority():continue
            last=int(state.bootstrap_progress.get(spec.label,0))
            queryset=spec.model.objects.all()
            if spec.label=='accounts.user':queryset=queryset.filter(remoteactor__isnull=True)
            while True:
                rows=list(queryset.filter(pk__gt=last).order_by('pk')[:settings.SYNC_BATCH_SIZE])
                if not rows:break
                with transaction.atomic():
                    source_gate();capture_objects(rows)
                    last=rows[-1].pk;state.bootstrap_progress[spec.label]=last
                    state.save(update_fields=['bootstrap_progress'])
        if own_authority()=='local':
            from apps.localnode.models import LocalAccessScan
            from apps.sync.services import capture_scan
            last=int(state.bootstrap_progress.get('access.scan',0))
            while True:
                rows=list(LocalAccessScan.objects.filter(pk__gt=last).order_by('pk')[:settings.SYNC_BATCH_SIZE])
                if not rows:break
                with transaction.atomic():
                    source_gate()
                    for row in rows:capture_scan(row)
                    last=rows[-1].pk;state.bootstrap_progress['access.scan']=last
                    state.save(update_fields=['bootstrap_progress'])
            # Bounded rounds; checkpoints and pending queue survive interruption.
            for _ in range(100):
                result=sync_once()
                if not result['pushed'] and not result['pulled']:break
            incomplete=SyncOutboxEvent.objects.exclude(status='SENT').exists() or SyncInboxEvent.objects.exclude(status='APPLIED').exists()
        else:incomplete=False
        state.bootstrap_phase='NEEDS_ATTENTION' if incomplete else 'COMPLETE';state.save(update_fields=['bootstrap_phase'])
        from apps.audit.models import AuditLog
        AuditLog.objects.create(action='sync.bootstrap',entity='sync.runtime',entity_id='1',data={'phase':state.bootstrap_phase})
        self.stdout.write('Bootstrap: '+state.bootstrap_phase)
        if incomplete:raise CommandError('Hay dependencias/conflictos pendientes. Revisa las identidades; no se borró ni fusionó información.')

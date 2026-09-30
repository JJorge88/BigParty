from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from apps.sync.models import SyncRuntimeState, SyncOutboxEvent, SyncInboxEvent
from apps.sync.services import origin
from apps.sync.security import cloud_url
from apps.sync.worker import SyncClient, handshake
from apps.sync.exceptions import SyncError


class Command(BaseCommand):
    help = 'Diagnóstico sin mostrar secretos; --probe comprueba el handshake sin enviar operaciones.'

    def add_arguments(self, parser):
        parser.add_argument('--probe', action='store_true')

    def handle(self, *args, **options):
        self.stdout.write('Sincronización: ' + ('habilitada' if settings.SYNC_ENABLED else 'deshabilitada'))
        if not settings.SYNC_ENABLED:
            return
        try:
            if len(settings.SYNC_SHARED_SECRET.encode()) < 32:
                raise SyncError('SYNC_NOT_CONFIGURED')
            if settings.DEPLOYMENT_MODE == 'local_node':
                cloud_url()
                node = origin()
                if options['probe']:
                    handshake(SyncClient(node))
                    self.stdout.write('Handshake correcto.')
            elif settings.DEPLOYMENT_MODE == 'cloud':
                import uuid
                try:
                    uuid.UUID(settings.SYNC_NODE_UUID)
                except (ValueError, TypeError):
                    raise SyncError('WRONG_NODE')
            else:
                raise SyncError('INVALID_DEPLOYMENT_MODE')
        except SyncError as exc:
            raise CommandError(exc.code) from None
        state = SyncRuntimeState.objects.filter(pk=1).first()
        self.stdout.write('Último contacto: ' + str(state.last_seen_at if state else 'sin contacto'))
        self.stdout.write('Pendientes: ' + str(SyncOutboxEvent.objects.filter(status='PENDING').count()))
        self.stdout.write('Fallidos: ' + str(SyncOutboxEvent.objects.filter(status='FAILED').count() + SyncInboxEvent.objects.filter(status='FAILED').count()))
        self.stdout.write('Esperando dependencias: ' + str(SyncInboxEvent.objects.filter(status='DEFERRED').count()))

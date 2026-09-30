import uuid
from django.conf import settings
from django.core.exceptions import PermissionDenied,ValidationError
from django.db import transaction
from django.utils import timezone
from .models import CloudToLocalCommand,LocalCommandInbox,SyncIdentity
from .services import source_gate,actor_reference,resolve_actor
from .serializers import digest,wire
from .exceptions import SyncError

TYPES={'VERIFY_OPERATIONAL_PAYMENT':'payments.verify_transfer_payment','REJECT_OPERATIONAL_PAYMENT':'payments.reject_transfer_payment'}


@transaction.atomic
def request_payment_command(payment,user,action,reason=''):
    if settings.DEPLOYMENT_MODE!='cloud' or not settings.SYNC_ENABLED:raise SyncError('CLOUD_COMMAND_REQUIRED')
    kind={'confirm':'VERIFY_OPERATIONAL_PAYMENT','reject':'REJECT_OPERATIONAL_PAYMENT'}.get(action)
    if kind not in TYPES or not user.is_active or user.role not in ('GERENTE','PROPIETARIO') or not user.has_perm(TYPES[kind]):raise PermissionDenied
    if payment.status!='PENDING' or payment.method not in ('TRANSFER','DEPOSIT'):raise ValidationError('El pago ya no está pendiente.')
    if action=='reject' and not reason.strip():raise ValidationError('Indica un motivo.')
    source_gate()
    identity=SyncIdentity.objects.filter(model_label='payments.payment',object_pk=str(payment.pk)).first()
    if not identity or identity.origin!=settings.SYNC_NODE_UUID:raise ValidationError('El pago no pertenece al nodo vinculado.')
    if CloudToLocalCommand.objects.filter(payload__payment_uuid=str(identity.entity_uuid),status__in=['PENDING','DELIVERED']).exists():raise ValidationError('Ya existe una solicitud pendiente para este pago.')
    from .services import get_or_create_sync_identity
    actor=get_or_create_sync_identity(user)
    command=CloudToLocalCommand.objects.create(target_node_uuid=settings.SYNC_NODE_UUID,command_type=kind,created_by=user,payload={
        'payment_uuid':str(identity.entity_uuid),'expected_version':identity.version,'actor_uuid':str(actor.entity_uuid),
        'actor':actor_reference(user),'permission':TYPES[kind],'reason':reason.strip()[:1000]})
    from apps.audit.models import AuditLog
    AuditLog.objects.create(user=user,action='sync.remote_payment_command',entity='sync.command',entity_id=str(command.command_uuid),data={'type':kind})
    return command


def command_envelope(command):
    return {'command_uuid':str(command.command_uuid),'target_node_uuid':str(command.target_node_uuid),'command_type':command.command_type,
        'payload':command.payload,'created_at':wire(command.created_at)}


@transaction.atomic
def apply_command(data):
    from apps.localnode.models import LocalNodeIdentity
    from apps.payments import services as payments
    source_gate()
    if not isinstance(data,dict) or set(data)!={'command_uuid','target_node_uuid','command_type','payload','created_at'}:raise SyncError('INVALID_COMMAND')
    if data['target_node_uuid']!=str(LocalNodeIdentity.objects.get(pk=1).node_uuid):raise SyncError('WRONG_NODE')
    kind=data['command_type'];p=data['payload'];checksum=digest(data)
    row,created=LocalCommandInbox.objects.get_or_create(command_uuid=data['command_uuid'],defaults={'envelope_digest':checksum,'command_type':kind,'payload':p})
    if row.envelope_digest!=checksum:raise SyncError('COMMAND_UUID_REUSED')
    if not created:return row
    try:
        with transaction.atomic():
            if kind not in TYPES or not isinstance(p,dict) or set(p)!={'payment_uuid','expected_version','actor_uuid','actor','permission','reason'}:raise SyncError('INVALID_COMMAND')
            if not isinstance(p['actor'],dict) or not isinstance(p['reason'],str) or len(p['reason'])>1000:raise SyncError('INVALID_COMMAND')
            if p['permission']!=TYPES[kind] or not p['actor'].get('active') or p['actor'].get('role') not in ('GERENTE','PROPIETARIO'):raise SyncError('INVALID_ACTOR_PERMISSION')
            identity=SyncIdentity.objects.filter(entity_uuid=p['payment_uuid'],model_label='payments.payment').first()
            if not identity:raise SyncError('REJECTED_STALE')
            from apps.payments.models import Payment
            payment=Payment.objects.select_for_update().get(pk=identity.object_pk)
            if type(p['expected_version']) is not int or identity.version!=p['expected_version'] or payment.status!='PENDING' or payment.order.business_day.status!='OPEN':raise SyncError('REJECTED_STALE')
            actor=resolve_actor(uuid.UUID(p['actor_uuid']),p['actor'],'cloud')
            actor.has_perm=lambda permission: permission==TYPES[kind]
            actor.is_active=True
            if kind=='VERIFY_OPERATIONAL_PAYMENT':payments.confirm_pending_payment(payment,actor)
            else:payments.reject_pending_payment(payment,actor,p['reason'])
    except (ValueError,TypeError,KeyError):row.status='FAILED';row.result_code='INVALID_COMMAND'
    except (PermissionDenied,ValidationError):row.status='REJECTED_STALE';row.result_code='BUSINESS_STATE_CHANGED'
    except SyncError as exc:
        row.status='REJECTED_STALE' if exc.code=='REJECTED_STALE' else 'FAILED';row.result_code=exc.code
    else:row.status='APPLIED';row.applied_at=timezone.now()
    row.save(update_fields=['status','result_code','applied_at'])
    from apps.audit.models import AuditLog
    AuditLog.objects.create(action='sync.command_result',entity='sync.command',entity_id=str(row.command_uuid),data={'status':row.status,'code':row.result_code})
    return row

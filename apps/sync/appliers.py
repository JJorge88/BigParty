"""Replica assignment never invokes sale/payment/stock/printing business services.

The only exceptions are the two explicitly authorized remote payment commands.
Inbox persistence, version check and domain write share the same transaction.
"""
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction, IntegrityError, DatabaseError
from django.db import models as django_models
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from .models import (SyncIdentity, SyncInboxEvent, SyncConflict, CloudAccessScan, CloudTicketDigest,
                     SyncAccessEvent, RemoteActor)
from .registry import REGISTRY, authority
from .serializers import decode_fields, digest, validate_envelope
from .services import applying, source_gate, own_authority, resolve_actor, identity_for, emit, capture_objects
from .exceptions import SyncError, MissingDependency


def resolve_uuid(label,value):
    try:identity=SyncIdentity.objects.get(entity_uuid=uuid.UUID(value),model_label=label)
    except (SyncIdentity.DoesNotExist,ValueError,TypeError,AttributeError):raise MissingDependency()
    from django.apps import apps
    obj=apps.get_model(label).objects.filter(pk=identity.object_pk).first()
    if not obj:raise MissingDependency()
    return obj


def apply_entity(spec,event):
    identity=SyncIdentity.objects.filter(entity_uuid=event.entity_uuid).first()
    if identity and identity.model_label!=spec.label:raise SyncError('IDENTITY_TYPE_MISMATCH')
    if identity and identity.origin!=event.source:raise SyncError('IDENTITY_OWNER_MISMATCH')
    if identity and identity.version>=event.entity_version:return
    if event.operation=='DELETE':
        if spec.label not in ('catalog.combocomponent','catalog.productareaprice'):raise SyncError('DELETE_FORBIDDEN')
        if identity:spec.model.objects.filter(pk=identity.object_pk).delete()
        else:raise MissingDependency()
    else:
        values=decode_fields(spec,event.payload)
        obj=spec.model.objects.filter(pk=identity.object_pk).first() if identity else None
        if obj is None:
            if identity:raise SyncError('MISSING_REPLICA')
            if spec.label=='accounts.user':
                actor=RemoteActor.objects.filter(actor_uuid=event.entity_uuid).select_related('user').first()
                obj=actor.user if actor else spec.model(username='sync-'+str(event.entity_uuid),password='!',pin_hash='!',is_staff=False,is_superuser=False)
            else:obj=spec.model()
        # An arrival already executed locally may never be undone by a stale cloud mirror.
        if spec.label=='reservations.reservation' and obj.pk and obj.order_id:
            if values.get('status') in ('CANCELLED','REJECTED','NO_SHOW'):
                conflict(event,'RESERVATION_ARRIVAL_CONFLICT',{'reference':obj.public_code,'message':'Llegada registrada localmente; Cloud cambió el estado de la reserva.'})
            values['status']='ARRIVED'
            values['arrival_confirmed_at']=obj.arrival_confirmed_at
        for name,value in values.items():setattr(obj,name,value)
        # Assign replica state exactly, bypassing operational side effects and auto_now mutation.
        obj.save_base(raw=True)
        if spec.label=='orders.subaccount':
            # The composite FK requires lines and their subaccount to move together.
            # Their order is derived from this parent; no financial service is replayed.
            from apps.orders.models import OrderLine
            OrderLine.objects.filter(subaccount=obj).exclude(order_id=obj.order_id).update(order_id=obj.order_id)
        if not identity:
            identity=SyncIdentity.objects.create(entity_uuid=event.entity_uuid,model_label=spec.label,object_pk=str(obj.pk),origin=event.source)
    if spec.label=='orders.tableorder' and event.operation=='UPSERT' and obj.primary_table_id:
        from types import SimpleNamespace
        link=event.payload.get('primary_link')
        exact(link,'entity_uuid entity_version payload')
        if type(link['entity_version']) is not int or link['entity_version']<1 or link['payload'].get('order_uuid')!=str(event.entity_uuid) or link['payload'].get('table_uuid')!=event.payload['primary_table_uuid']:raise SyncError('INVALID_PRIMARY_LINK')
        apply_entity(REGISTRY['orders.ordertablelink'],SimpleNamespace(**link,source=event.source,operation='UPSERT'))
    identity.version=event.entity_version;identity.payload_digest=digest(event.payload)
    identity.save(update_fields=['version','payload_digest','updated_at'])


def conflict(event,kind,summary):
    row,created=SyncConflict.objects.get_or_create(event_uuid=event.event_uuid,defaults={
        'entity_type':event.entity_type,'entity_uuid':event.entity_uuid,'conflict_type':kind,
        'remote_version':event.entity_version,'payload_summary':summary})
    if created:
        from apps.audit.models import AuditLog
        AuditLog.objects.create(action='sync.conflict',entity='sync.syncconflict',entity_id=str(row.conflict_uuid),data={'type':kind})
        if own_authority()=='cloud':
            emit(identity_for('sync.conflict',row.pk),{'conflict_uuid':str(row.conflict_uuid),'event_uuid':str(row.event_uuid),
                'entity_type':row.entity_type,'entity_uuid':str(row.entity_uuid),'conflict_type':kind,'summary':summary})
    return row


def stamp(value):
    try:result=parse_datetime(value)
    except (TypeError,ValueError):raise SyncError('INVALID_DATETIME')
    if not result or timezone.is_naive(result):raise SyncError('INVALID_DATETIME')
    return result


def exact(payload,keys):
    if not isinstance(payload,dict) or set(payload)!=set(keys.split()):raise SyncError('INVALID_FIELDS')


def apply_special(event):
    p=event.payload
    identity=SyncIdentity.objects.filter(entity_uuid=event.entity_uuid).first()
    if identity and (identity.model_label!=event.entity_type or identity.origin!=event.source):raise SyncError('IDENTITY_OWNER_MISMATCH')
    if event.operation!='UPSERT':raise SyncError('DELETE_FORBIDDEN')
    if event.entity_type=='inventory.stock_snapshot':
        exact(p,'product_uuid stock minimum generated_at')
        if any(type(p[n]) is not int or not 0<=p[n]<=2147483647 for n in ('stock','minimum')):raise SyncError('INVALID_STOCK')
        stamp(p['generated_at']);product=resolve_uuid('catalog.product',p['product_uuid'])
        identity=SyncIdentity.objects.filter(entity_uuid=event.entity_uuid).first()
        if identity and identity.version>=event.entity_version:return
        type(product).objects.filter(pk=product.pk).update(stock_quantity=p['stock'],minimum_stock=p['minimum'])
        SyncIdentity.objects.update_or_create(entity_uuid=event.entity_uuid,defaults={'model_label':event.entity_type,'object_pk':str(product.pk),'origin':event.source,'version':event.entity_version})
    elif event.entity_type=='events.access_snapshot':
        exact(p,'event_uuid snapshot')
        resolve_uuid('events.event',p['event_uuid'])
        identity=SyncIdentity.objects.filter(entity_uuid=event.entity_uuid).first()
        if identity and identity.version>=event.entity_version:return
        from apps.localnode.snapshots import import_snapshot,validate_snapshot
        from apps.localnode.models import LocalEventAccessSnapshot
        generated=validate_snapshot(p['snapshot'])
        snapshot=LocalEventAccessSnapshot.objects.filter(source=p['snapshot']['source'],event_public_identifier=str(p['snapshot']['event_id'])).first()
        if not snapshot or generated>=snapshot.generated_at:snapshot,_=import_snapshot(p['snapshot'])
        SyncAccessEvent.objects.update_or_create(snapshot=snapshot,defaults={'event_uuid':p['event_uuid']})
        SyncIdentity.objects.update_or_create(entity_uuid=event.entity_uuid,defaults={'model_label':event.entity_type,'object_pk':str(snapshot.pk),'origin':event.source,'version':event.entity_version})
    elif event.entity_type=='access.scan':
        exact(p,'node_uuid event_uuid snapshot_version token_digest result scanned_at guard_uuid guard')
        import re
        if p['node_uuid']!=event.source or not isinstance(p['token_digest'],str) or not re.fullmatch('[a-f0-9]{64}',p['token_digest']) or p['result'] not in ('VALID','USED','CANCELLED','INVALID'):raise SyncError('INVALID_SCAN')
        scanned_at=stamp(p['scanned_at'])
        guard=resolve_actor(uuid.UUID(p['guard_uuid']),p['guard'],event.source)
        mapping=CloudTicketDigest.objects.select_related('ticket').filter(token_digest=p['token_digest']).first()
        ticket=None
        if mapping:
            from apps.events.models import Event,EventTicket
            Event.objects.select_for_update().get(pk=mapping.ticket.event_id)
            ticket=EventTicket.objects.select_for_update().get(pk=mapping.ticket_id)
        if not ticket and p['result']=='VALID':raise MissingDependency()
        if p['event_uuid'] and ticket:
            remote_event=resolve_uuid('events.event',p['event_uuid'])
            if remote_event.pk!=ticket.event_id:raise SyncError('EVENT_MISMATCH')
        previous=CloudAccessScan.objects.filter(scan_uuid=event.entity_uuid).first()
        if previous:
            if previous.node_uuid!=uuid.UUID(event.source) or previous.token_digest!=p['token_digest'] or previous.scanned_at!=scanned_at or previous.result!=p['result']:raise SyncError('SCAN_UUID_REUSED')
            return
        CloudAccessScan.objects.create(scan_uuid=event.entity_uuid,node_uuid=event.source,event_uuid=p['event_uuid'],
            token_digest=p['token_digest'],result=p['result'],scanned_at=scanned_at,guard_uuid=p['guard_uuid'],guard_name=p['guard']['name'])
        if ticket and p['result']=='VALID':
            if ticket.status in ('USED','CANCELLED') or ticket.event.status=='CANCELLED':
                conflict(event,'CANCELLED_ADMISSION' if ticket.status=='CANCELLED' or ticket.event.status=='CANCELLED' else 'DUPLICATE_ADMISSION',{
                    'reference':ticket.ticket_number,'message':'Admisión offline incompatible con el estado conocido en Cloud.',
                    'first_known_at':ticket.used_at.isoformat() if ticket.used_at else None,'local_admission_at':p['scanned_at'],'node_uuid':p['node_uuid']})
            else:
                ticket.status='USED';ticket.used_at=scanned_at;ticket.used_by=guard
                ticket.save(update_fields=['status','used_at','used_by'])
                capture_objects([ticket.event])
    elif event.entity_type=='reservation.arrived':
        exact(p,'reservation_uuid order_uuid arrived_at waiter_uuid waiter node_uuid')
        if p['node_uuid']!=event.source:raise SyncError('WRONG_NODE')
        reservation=resolve_uuid('reservations.reservation',p['reservation_uuid'])
        order=resolve_uuid('orders.tableorder',p['order_uuid'])
        reservation=type(reservation).objects.select_for_update().get(pk=reservation.pk)
        if reservation.status=='ARRIVED' and reservation.order_id==order.pk:return
        if reservation.status!='CONFIRMED':
            conflict(event,'RESERVATION_ARRIVAL_CONFLICT',{'reference':reservation.public_code,'message':'Llegada local recibida con una reserva cancelada, rechazada o ya atendida. La cuenta local se conserva.'})
            return
        if reservation.table_id!=order.primary_table_id:raise SyncError('ARRIVAL_TABLE_MISMATCH')
        waiter=resolve_uuid('accounts.user',p['waiter_uuid'])
        if waiter.pk!=order.responsible_waiter_id:raise SyncError('ARRIVAL_WAITER_MISMATCH')
        reservation.status='ARRIVED';reservation.order=order;reservation.arrival_confirmed_at=stamp(p['arrived_at']);reservation.arrival_confirmed_by=waiter
        reservation.save(update_fields=['status','order','arrival_confirmed_at','arrival_confirmed_by','updated_at'])
        capture_objects([reservation])
    elif event.entity_type=='sync.conflict':
        exact(p,'conflict_uuid event_uuid entity_type entity_uuid conflict_type summary')
        SyncConflict.objects.get_or_create(event_uuid=p['event_uuid'],defaults={'conflict_uuid':p['conflict_uuid'],'entity_type':p['entity_type'],
            'entity_uuid':p['entity_uuid'],'conflict_type':p['conflict_type'],'payload_summary':p['summary'],'remote_version':event.entity_version})
    else:raise SyncError('UNKNOWN_ENTITY')


@transaction.atomic
def receive_event(data,source):
    validate_envelope(data)
    source_gate()
    checksum=digest(data)
    event,created=SyncInboxEvent.objects.get_or_create(event_uuid=data['event_uuid'],defaults={
        **{k:v for k,v in data.items() if k!='event_uuid'},'source':source,'envelope_digest':checksum})
    if event.source!=source or event.envelope_digest!=checksum:raise SyncError('EVENT_UUID_REUSED')
    if event.status=='APPLIED':return event
    if event.status=='FAILED' and not created:return event
    event.last_attempt_at=timezone.now()
    expected='local' if own_authority()=='cloud' else 'cloud'
    try:
        with transaction.atomic(),applying():
            if authority(event.entity_type)!=expected:raise SyncError('WRONG_AUTHORITY')
            if event.schema_version!=1:raise SyncError('UNSUPPORTED_SCHEMA')
            if event.entity_type in REGISTRY:REGISTRY[event.entity_type].apply(event)
            else:apply_special(event)
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
                cursor.execute('SET CONSTRAINTS ALL DEFERRED')
    except MissingDependency:
        event.status='DEFERRED';event.error='MISSING_DEPENDENCY'
    except IntegrityError:
        # A newer predecessor may need to release a uniqueness constraint first.
        event.status='DEFERRED';event.error='DEPENDENCY_OR_CONSTRAINT'
    except SyncError as exc:
        event.status='FAILED';event.error=exc.code
    except (DatabaseError,ValidationError,ValueError,TypeError,KeyError):
        event.status='FAILED';event.error='APPLY_ERROR'
    else:
        event.status='APPLIED';event.error='';event.applied_at=timezone.now()
    event.save(update_fields=['status','error','applied_at','last_attempt_at'])
    return event


def retry_deferred(limit=None):
    from .serializers import envelope
    limit=limit or settings.SYNC_BATCH_SIZE
    for event in SyncInboxEvent.objects.filter(status='DEFERRED').order_by(django_models.F('last_attempt_at').asc(nulls_first=True),'pk')[:limit]:receive_event(envelope(event),event.source)

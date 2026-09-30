"""Durable source capture. No HTTP and no post-save signals.

A reviewed service boundary owns business writes and outbox in one transaction.
A source gate serializes versions/feed allocation through commit, avoiding gaps
caused by transaction commit order. Applying replicas suppresses capture.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import uuid
from django.conf import settings
from django.core.exceptions import PermissionDenied, ObjectDoesNotExist
from django.db import transaction, models
from django.utils import timezone
from .models import SyncIdentity, SyncRuntimeState, SyncOutboxEvent, CloudSyncChange, RemoteActor
from .registry import REGISTRY, authority
from .serializers import digest, wire
from .exceptions import SyncError

_capture=ContextVar('sync_capture',default=None)
_applying=ContextVar('sync_applying',default=False)


def enabled():return settings.SYNC_ENABLED and settings.DEPLOYMENT_MODE in ('cloud','local_node')
def own_authority():return 'cloud' if settings.DEPLOYMENT_MODE=='cloud' else 'local'
def origin():
    if settings.DEPLOYMENT_MODE=='cloud':return 'cloud'
    from apps.localnode.models import LocalNodeIdentity
    node=LocalNodeIdentity.objects.filter(pk=1).first()
    if not node:raise SyncError('NODE_NOT_INITIALIZED')
    return str(node.node_uuid)


def source_gate():
    SyncRuntimeState.objects.get_or_create(pk=1)
    return SyncRuntimeState.objects.select_for_update().get(pk=1)


@contextmanager
def applying():
    token=_applying.set(True)
    try:yield
    finally:_applying.reset(token)


def identity_for(label,pk):
    return SyncIdentity.objects.get_or_create(model_label=label,object_pk=str(pk),defaults={'origin':origin()})[0]

def get_or_create_sync_identity(obj):
    if obj is None:return None
    label=obj._meta.label_lower
    if label not in REGISTRY:raise SyncError('UNREGISTERED_REFERENCE')
    return identity_for(label,obj.pk)


def actor_reference(user):
    return {'name':(user.get_full_name().strip() or user.username)[:200],'role':user.role,'active':user.is_active}


def resolve_actor(actor_uuid,data,source=None):
    """Report/command attribution only. Never imports credentials or permissions."""
    from django.contrib.auth import get_user_model
    if not isinstance(data,dict) or set(data)!={'name','role','active'} or not isinstance(data['name'],str) or len(data['name'])>200 or data['role'] not in ('MESERO','CAJERO','GERENTE','PROPIETARIO','GUARDIA') or type(data['active']) is not bool:raise SyncError('INVALID_ACTOR')
    existing=SyncIdentity.objects.filter(entity_uuid=actor_uuid,model_label='accounts.user').first()
    if existing:
        user=get_user_model().objects.filter(pk=existing.object_pk).first()
        if user:return user
    row=RemoteActor.objects.select_related('user').filter(actor_uuid=actor_uuid).first()
    if row:return row.user
    user=get_user_model()(username='sync-'+str(actor_uuid),first_name=data['name'][:150],role=data['role'],is_active=data['active'],is_staff=False,is_superuser=False,pin_hash='!')
    user.set_unusable_password();models.Model.save(user)
    actor_origin=source or ('cloud' if own_authority()=='local' else settings.SYNC_NODE_UUID)
    RemoteActor.objects.create(actor_uuid=actor_uuid,user=user,origin=actor_origin)
    SyncIdentity.objects.get_or_create(entity_uuid=actor_uuid,defaults={'model_label':'accounts.user','object_pk':str(user.pk),'origin':actor_origin})
    return user


def track(value):
    capture=_capture.get()
    if capture is not None:
        if isinstance(value,models.Model) and value.pk:capture['objects'][(value._meta.label_lower,str(value.pk))]=value
        elif isinstance(value,(list,tuple)):
            for obj in value:track(obj)
    return value


def sync_atomic(authority_name,*,action=''):
    def decorate(function):
        @wraps(function)
        def wrapped(*args,**kwargs):
            from apps.core.ops.recovery import require_operational
            require_operational()
            if not enabled() or _applying.get():return function(*args,**kwargs)
            allowed=(own_authority()=='local') if action=='arrival' else authority_name==own_authority()
            if not allowed:raise PermissionDenied('Administrado desde BIG PARTY '+('Local Node' if authority_name=='local' else 'Cloud')+'.')
            if _capture.get() is not None:
                result=function(*args,**kwargs)
                for obj in (*args,*kwargs.values(),result):track(obj)
                return result
            with transaction.atomic():
                source_gate()
                token=_capture.set({'objects':{},'deletes':[]})
                try:
                    result=function(*args,**kwargs)
                    for obj in (*args,*kwargs.values(),result):track(obj)
                    state=_capture.get()
                    capture_objects(state['objects'].values())
                    for identity in state['deletes']:emit(identity,{},operation='DELETE')
                    return result
                finally:_capture.reset(token)
        return wrapped
    return decorate


def record_delete(obj):
    """Only allowlisted technical configuration deletions, never financial history."""
    if enabled() and not _applying.get():
        if obj._meta.label_lower not in ('catalog.combocomponent','catalog.productareaprice'):raise PermissionDenied('Desactiva la entidad; no se sincronizan borrados de historial.')
        if _capture.get() is None:raise SyncError('MISSING_TRANSACTION_BOUNDARY')
        _capture.get()['deletes'].append(get_or_create_sync_identity(obj))


def emit(identity,payload,*,entity_type=None,operation='UPSERT',content_digest=None):
    entity_type=entity_type or identity.model_label
    checksum=content_digest or digest({'operation':operation,'payload':payload})
    identity=SyncIdentity.objects.select_for_update().get(pk=identity.pk)
    if identity.payload_digest==checksum:return None
    identity.version+=1;identity.payload_digest=checksum;identity.save(update_fields=['version','payload_digest','updated_at'])
    fields=dict(entity_type=entity_type,entity_uuid=identity.entity_uuid,entity_version=identity.version,operation=operation,payload=payload,schema_version=1)
    if own_authority()=='local':return SyncOutboxEvent.objects.create(**fields)
    state=source_gate();state.feed_sequence+=1;state.save(update_fields=['feed_sequence'])
    return CloudSyncChange.objects.create(sequence=state.feed_sequence,**fields)


def capture_objects(objects):
    objects=list(objects);found={};expanded=set();event_ids=set()
    def collect(obj,children=True):
        label=obj._meta.label_lower
        # Source event ticket mutations trigger the existing privacy-preserving snapshot.
        if label.startswith('events.') and label not in ('events.eventsettings','events.guardloginattempt'):
            if label=='events.event':event_ids.add(obj.pk)
            elif hasattr(obj,'event_id'):event_ids.add(obj.event_id)
            elif hasattr(obj,'purchase_id'):event_ids.add(obj.purchase.event_id)
        spec=REGISTRY.get(label)
        if not spec or spec.authority!=own_authority():return
        if label in ('reservations.reservation','reservations.reservationpayment'):
            reservation=obj if label=='reservations.reservation' else obj.reservation
            active=('PENDING_REVIEW','AWAITING_PAYMENT','PAYMENT_REVIEW','CONFIRMED')
            if reservation.ends_at<timezone.now() and reservation.status not in active and not SyncIdentity.objects.filter(model_label='reservations.reservation',object_pk=str(reservation.pk),version__gt=0).exists():return
        if label=='accounts.user' and RemoteActor.objects.filter(user_id=obj.pk).exists():return
        key=(label,str(obj.pk))
        if key in found and (not children or key in expanded):return
        if children:expanded.add(key)
        obj=spec.model.objects.filter(pk=obj.pk).first()
        if obj is None:return
        existed=key in found
        found[key]=(spec,obj)
        for name in (() if existed else spec.fields):
            f=spec.model._meta.get_field(name)
            if f.is_relation and (related:=getattr(obj,name)) is not None:collect(related,False)
        if children:
            for name in spec.children:
                try:related=getattr(obj,name)
                except ObjectDoesNotExist:continue
                if hasattr(related,'all'):
                    for child in related.all().order_by('pk'):collect(child)
                else:collect(related)
    for obj in objects:collect(obj)
    emitted=set()
    def publish(key):
        if key in emitted:return
        emitted.add(key);spec,obj=found[key]
        for name in spec.fields:
            f=spec.model._meta.get_field(name)
            if f.is_relation and (related:=getattr(obj,name)) is not None:
                dep=(related._meta.label_lower,str(related.pk))
                if dep in found:publish(dep)
        if spec.label=='orders.tableorder' and obj.primary_table_id:
            link=obj.table_links.get(table_id=obj.primary_table_id)
            key_link=('orders.ordertablelink',str(link.pk))
            if key_link not in found:found[key_link]=(REGISTRY['orders.ordertablelink'],link)
            publish(key_link)
        identity=get_or_create_sync_identity(obj)
        emit(identity,spec.serialize(obj))
        if spec.label=='catalog.product':
            stock={'product_uuid':str(identity.entity_uuid),'stock':obj.stock_quantity,'minimum':obj.minimum_stock}
            emit(identity_for('inventory.stock_snapshot',obj.pk),{**stock,'generated_at':wire(timezone.now())},content_digest=digest(stock))
    for key in list(found):publish(key)
    if own_authority()=='cloud':
        from apps.events.models import Event
        from apps.localnode.snapshots import signed_snapshot
        for event in Event.objects.filter(pk__in=event_ids).order_by('pk'):
            identity=get_or_create_sync_identity(event)
            snapshot=signed_snapshot(event)
            import hashlib
            from .models import CloudTicketDigest
            from apps.events.models import EventTicket
            CloudTicketDigest.objects.bulk_create([CloudTicketDigest(ticket_id=t.pk,token_digest=hashlib.sha256(t.qr_token.encode()).hexdigest()) for t in EventTicket.objects.filter(event=event).only('pk','qr_token')],ignore_conflicts=True)
            emit(identity_for('events.access_snapshot',event.pk),{'event_uuid':str(identity.entity_uuid),'snapshot':snapshot},content_digest=digest({'event_uuid':str(identity.entity_uuid),'version':snapshot['version']}))


def capture_scan(scan):
    if not enabled() or _applying.get():return
    from .serializers import wire
    from .models import SyncAccessEvent
    source, _, event_key=scan.event_identifier.rpartition(':')
    mapping=SyncAccessEvent.objects.filter(snapshot__source=source,snapshot__event_public_identifier=event_key).first()
    payload={'node_uuid':str(scan.node.node_uuid),'event_uuid':str(mapping.event_uuid) if mapping else None,'snapshot_version':scan.snapshot_version,
        'token_digest':scan.token_digest,'result':scan.result,'scanned_at':wire(scan.scanned_at),
        'guard_uuid':str(get_or_create_sync_identity(scan.scanned_by).entity_uuid),'guard':actor_reference(scan.scanned_by)}
    emit(identity_for('access.scan',scan.pk),payload)


def capture_arrival(reservation):
    if not enabled() or own_authority()!='local' or _applying.get():return
    row=get_or_create_sync_identity(reservation)
    order=get_or_create_sync_identity(reservation.order)
    emit(identity_for('reservation.arrived',reservation.pk),{'reservation_uuid':str(row.entity_uuid),'order_uuid':str(order.entity_uuid),
        'arrived_at':wire(reservation.arrival_confirmed_at),'waiter_uuid':str(get_or_create_sync_identity(reservation.order.responsible_waiter).entity_uuid),
        'waiter':actor_reference(reservation.order.responsible_waiter),'node_uuid':origin()})


def save_tracked(obj,*args,**kwargs):
    result=obj.save(*args,**kwargs)
    track(obj)
    return result


def delete_tracked(obj,*args,**kwargs):
    if enabled() and not _applying.get():
        if obj._meta.label_lower=='orders.orderline':
            obj.status='CANCELLED'
            save_tracked(obj,update_fields=['status','updated_at'])
            return (0,{})
        record_delete(obj)
    return obj.delete(*args,**kwargs)

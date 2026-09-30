"""Wire codec for registry allowlists; unknown fields are rejected, never inferred."""
import hashlib
import json
import math
import uuid
from datetime import datetime, date, time, timezone
from decimal import Decimal, InvalidOperation
from django.core.exceptions import ValidationError
from django.db import models
from .exceptions import SyncError, MissingDependency


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')

def digest(value): return hashlib.sha256(canonical(value)).hexdigest()

def wire(value):
    if isinstance(value,Decimal): return str(value)
    if isinstance(value,datetime):
        if value.tzinfo is None: raise SyncError('NAIVE_DATETIME')
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value,(date,time,uuid.UUID)): return str(value)
    if value is None or type(value) in (str,int,bool): return value
    raise SyncError('UNSUPPORTED_VALUE')


def serialize_entity(spec,obj):
    from .services import get_or_create_sync_identity, actor_reference
    result={}
    for name in spec.fields:
        field=spec.model._meta.get_field(name)
        if field.is_relation:
            related=getattr(obj,name)
            result[name+'_uuid']=str(get_or_create_sync_identity(related).entity_uuid) if related else None
            if related and field.related_model._meta.label_lower=='accounts.user':
                result[name+'_actor']=actor_reference(related)
        elif spec.label=='payments.payment' and name=='metadata':
            result[name]={key:obj.metadata[key] for key in ('received_amount','terminal_approved','rejection_reason','rejected_at') if key in obj.metadata}
        else: result[name]=wire(getattr(obj,name))
    if spec.label=='orders.tableorder':
        result['primary_link']=None
        if obj.primary_table_id:
            from .registry import REGISTRY
            link=obj.table_links.get(table_id=obj.primary_table_id)
            identity=get_or_create_sync_identity(link)
            result['primary_link']={'entity_uuid':str(identity.entity_uuid),'entity_version':identity.version,'payload':serialize_entity(REGISTRY['orders.ordertablelink'],link)}
    return result


def decode_fields(spec,payload):
    from .models import SyncIdentity
    from .services import resolve_actor
    if spec.label=='orders.tableorder':
        if 'primary_link' not in payload:raise SyncError('INVALID_FIELDS')
        payload={k:v for k,v in payload.items() if k!='primary_link'}
    expected=set()
    for name in spec.fields:
        field=spec.model._meta.get_field(name)
        expected.add(name+'_uuid' if field.is_relation else name)
        if field.is_relation and field.related_model._meta.label_lower=='accounts.user':expected.add(name+'_actor')
    # Actor snapshots only accompany non-null UUIDs.
    optional={name+'_actor' for name in spec.fields if spec.model._meta.get_field(name).is_relation}
    if not isinstance(payload,dict) or set(payload)-expected or (expected-optional)-set(payload):raise SyncError('INVALID_FIELDS')
    values={}
    for name in spec.fields:
        field=spec.model._meta.get_field(name)
        value=payload[name+'_uuid' if field.is_relation else name]
        if value is None:
            if not field.null: raise SyncError('INVALID_NULL')
            values[field.attname]=None;continue
        if field.is_relation:
            try: entity_uuid=uuid.UUID(value)
            except (ValueError,TypeError,AttributeError):raise SyncError('INVALID_REFERENCE')
            identity=SyncIdentity.objects.filter(entity_uuid=entity_uuid,model_label=field.related_model._meta.label_lower).first()
            if not identity:
                if field.related_model._meta.label_lower=='accounts.user' and name+'_actor' in payload:
                    actor=resolve_actor(entity_uuid,payload[name+'_actor'])
                    values[field.attname]=actor.pk;continue
                raise MissingDependency()
            if not field.related_model.objects.filter(pk=identity.object_pk).exists():raise MissingDependency()
            values[field.attname]=identity.object_pk;continue
        if spec.label=='payments.payment' and name=='metadata':
            if not isinstance(value,dict) or set(value)-{'received_amount','terminal_approved','rejection_reason','rejected_at'}:raise SyncError('INVALID_PAYMENT_METADATA')
            for key,item in value.items():
                if key=='terminal_approved':
                    if type(item) is not bool:raise SyncError('INVALID_PAYMENT_METADATA')
                elif not isinstance(item,str) or len(item)>2000:raise SyncError('INVALID_PAYMENT_METADATA')
                if key=='received_amount':
                    try:
                        amount=Decimal(item)
                        if not amount.is_finite() or amount<0 or amount!=amount.quantize(Decimal('.01')):raise ValueError
                    except (ValueError,InvalidOperation):raise SyncError('INVALID_PAYMENT_METADATA')
            values[name]=value;continue
        try:
            if isinstance(field,models.DecimalField):
                if not isinstance(value,str) or not Decimal(value).is_finite():raise ValueError
            elif isinstance(field,models.BooleanField):
                if type(value) is not bool:raise ValueError
            elif isinstance(field,models.IntegerField):
                if type(value) is not int:raise ValueError
            elif isinstance(field,(models.DateTimeField,models.DateField,models.TimeField)):
                if not isinstance(value,str):raise ValueError
            elif not isinstance(value,str):raise ValueError
            value=field.to_python(value)
            if isinstance(value,datetime) and value.tzinfo is None:raise ValueError
            field.run_validators(value)
            if field.choices and value not in dict(field.choices):raise ValueError
        except (ValueError,TypeError,ValidationError,InvalidOperation):raise SyncError('INVALID_VALUE')
        values[name]=value
    return values


def envelope(row):
    return {name:wire(getattr(row,name)) for name in ('event_uuid','entity_type','entity_uuid','operation','entity_version','schema_version','payload') if name!='payload'} | {'payload':row.payload}


def validate_envelope(data):
    required={'event_uuid','entity_type','entity_uuid','operation','entity_version','schema_version','payload'}
    if not isinstance(data,dict) or set(data)!=required:raise SyncError('INVALID_ENVELOPE')
    for key in ('event_uuid','entity_uuid'):
        try:uuid.UUID(data[key])
        except (ValueError,TypeError,AttributeError):raise SyncError('INVALID_UUID')
    if not isinstance(data['entity_type'],str) or len(data['entity_type'])>100:raise SyncError('INVALID_ENTITY')
    if data['operation'] not in ('UPSERT','DELETE'):raise SyncError('INVALID_OPERATION')
    for key in ('entity_version','schema_version'):
        if type(data[key]) is not int or not 0<data[key]<2**63:raise SyncError('INVALID_VERSION')
    if not isinstance(data['payload'],dict):raise SyncError('INVALID_PAYLOAD')
    canonical(data)

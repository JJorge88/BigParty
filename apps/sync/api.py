import json
import logging
from functools import wraps
from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from .exceptions import SyncError
from .security import authenticate,response_signature,compatible
from .serializers import canonical,envelope
from .models import CloudSyncChange,CloudToLocalCommand,SyncRuntimeState
from .services import source_gate
from .commands import command_envelope


def no_duplicates(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate')
        result[key]=value
    return result


def private_api(method):
    def decorate(view):
        @csrf_exempt
        @wraps(view)
        def wrapped(request):
            authenticated=False
            try:
                if request.method!=method:raise SyncError('METHOD_NOT_ALLOWED')
                try:length=int(request.META.get('CONTENT_LENGTH') or 0)
                except ValueError:raise SyncError('INVALID_BODY')
                if length>settings.SYNC_MAX_BODY_BYTES:raise SyncError('PAYLOAD_TOO_LARGE')
                body=request.read(settings.SYNC_MAX_BODY_BYTES+1)
                if len(body)>settings.SYNC_MAX_BODY_BYTES:raise SyncError('PAYLOAD_TOO_LARGE')
                node=authenticate(request,body);authenticated=True
                data=json.loads(body,object_pairs_hook=no_duplicates,parse_constant=lambda _:(_ for _ in ()).throw(ValueError())) if body else {}
                if method=='POST':compatible(data)
                value=view(request,node,data);status=200
            except SyncError as exc:
                value={'code':exc.code,'message':'Solicitud de sincronización no disponible.'};status=401 if exc.code=='AUTHENTICATION_FAILED' else 400
            except (ValueError,TypeError,KeyError,UnicodeError):value={'code':'INVALID_BODY','message':'Formato no válido.'};status=400
            except Exception as exc:
                logging.getLogger('apps.sync').error('sync_failed',extra={'sync_code':getattr(getattr(exc.__cause__,'diag',None),'constraint_name',None) or type(exc).__name__})
                value={'code':'SYNC_UNAVAILABLE','message':'Sincronización temporalmente no disponible.'};status=503
            raw=canonical(value);response=HttpResponse(raw,status=status,content_type='application/json')
            response['Cache-Control']='no-store'
            if authenticated:response['X-BP-Response-Signature']=response_signature(request.headers['X-BP-Signature'],raw)
            return response
        return wrapped
    return decorate


@private_api('GET')
def status(request,node,data):
    state=SyncRuntimeState.objects.filter(pk=1).first()
    return {'protocol':settings.SYNC_PROTOCOL_VERSION,'app_version':settings.APP_VERSION,'node_uuid':node,'sequence':state.feed_sequence if state else 0}


@private_api('POST')
def push(request,node,data):
    from .appliers import receive_event,retry_deferred
    rows=data.get('events')
    if not isinstance(rows,list) or len(rows)>settings.SYNC_BATCH_SIZE:raise SyncError('INVALID_BATCH')
    results=[]
    for row in rows:
        event=receive_event(row,node);results.append(str(event.event_uuid))
    retry_deferred()
    from .models import SyncInboxEvent
    values={str(e.event_uuid):e for e in SyncInboxEvent.objects.filter(event_uuid__in=results)}
    return {'results':[{'event_uuid':str(key),'status':values[key].status,'code':values[key].error} for key in results]}


@private_api('POST')
@transaction.atomic
def pull(request,node,data):
    source_gate()
    sequence=data.get('after',0)
    if type(sequence) is not int or not 0<=sequence<2**63:raise SyncError('INVALID_CURSOR')
    changes=[];size=0
    for row in CloudSyncChange.objects.filter(sequence__gt=sequence).order_by('sequence')[:settings.SYNC_BATCH_SIZE]:
        entry={'sequence':row.sequence,'event':envelope(row)};length=len(canonical(entry))
        if length>settings.SYNC_MAX_BODY_BYTES//2:raise SyncError('EVENT_TOO_LARGE')
        if size+length>settings.SYNC_MAX_BODY_BYTES//2:break
        changes.append(entry);size+=length
    from .commands import TYPES
    commands=[]
    for command in CloudToLocalCommand.objects.select_for_update().select_related('created_by').filter(target_node_uuid=node,status__in=['PENDING','DELIVERED']).order_by('pk')[:settings.SYNC_BATCH_SIZE]:
        actor=command.created_by
        if command.status=='PENDING':
            if not actor.is_active or actor.role not in ('GERENTE','PROPIETARIO') or not actor.has_perm(TYPES[command.command_type]):
                command.status='REJECTED';command.result_code='INVALID_ACTOR_PERMISSION';command.save(update_fields=['status','result_code'])
                from apps.audit.models import AuditLog
                AuditLog.objects.create(action='sync.command_result',entity='sync.command',entity_id=str(command.command_uuid),data={'status':command.status,'code':command.result_code})
                continue
            command.status='DELIVERED';command.save(update_fields=['status'])
        commands.append(command_envelope(command))
    return {'changes':changes,'commands':commands,'last_sequence':changes[-1]['sequence'] if changes else sequence}


@private_api('POST')
@transaction.atomic
def ack(request,node,data):
    state=source_gate();pending=data.get('pending',0)
    if type(pending) is not int or pending<0:raise SyncError('INVALID_HEARTBEAT')
    acks=data.get('commands',[])
    if not isinstance(acks,list) or len(acks)>settings.SYNC_BATCH_SIZE:raise SyncError('INVALID_BATCH')
    for result in acks:
        if set(result)!={'command_uuid','status','code'} or result['status'] not in ('APPLIED','FAILED','REJECTED_STALE'):raise SyncError('INVALID_ACK')
        command=CloudToLocalCommand.objects.select_for_update().filter(command_uuid=result['command_uuid'],target_node_uuid=node).first()
        if not command:raise SyncError('UNKNOWN_COMMAND')
        final='REJECTED' if result['status']=='REJECTED_STALE' else result['status']
        if command.status in ('APPLIED','FAILED','REJECTED'):
            if command.status!=final:raise SyncError('ACK_MISMATCH')
            continue
        command.status=final
        command.result_code=result['code'] if result['code'] in ('','REJECTED_STALE','BUSINESS_STATE_CHANGED','INVALID_COMMAND','INVALID_ACTOR_PERMISSION') else 'COMMAND_ERROR'
        command.applied_at=timezone.now();command.save(update_fields=['status','result_code','applied_at'])
        from apps.audit.models import AuditLog
        AuditLog.objects.create(action='sync.command_result',entity='sync.command',entity_id=str(command.command_uuid),data={'status':command.status,'code':command.result_code})
    state.last_seen_at=timezone.now();state.reported_pending=pending;state.reported_app_version=data['app_version'][:100];state.reported_app_commit=str(data.get('app_commit',''))[:100]
    state.save(update_fields=['last_seen_at','reported_pending','reported_app_version','reported_app_commit'])
    return {'status':'ok'}

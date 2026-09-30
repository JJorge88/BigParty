import logging
from contextlib import contextmanager
from django.conf import settings
from django.db import connection,transaction
from django.utils import timezone
from .models import SyncOutboxEvent,SyncInboxEvent,SyncCursor,SyncRuntimeState,LocalCommandInbox
from .services import origin
from .serializers import envelope,canonical
from .exceptions import SyncError
from .client import SyncClient
from .appliers import receive_event,retry_deferred
from .commands import apply_command
from .security import compatible

logger=logging.getLogger('apps.sync')
LOCK_ID=42810401


@contextmanager
def worker_lock():
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s)',[LOCK_ID]);locked=cursor.fetchone()[0]
    if not locked:raise SyncError('WORKER_ALREADY_RUNNING')
    try:yield
    finally:
        with connection.cursor() as cursor:cursor.execute('SELECT pg_advisory_unlock(%s)',[LOCK_ID])


def handshake(client):
    data=client.request('status');compatible(data)
    if data.get('node_uuid')!=client.node:raise SyncError('WRONG_NODE')
    return data


def push_once(client):
    rows=list(SyncOutboxEvent.objects.filter(status='PENDING',available_at__lte=timezone.now()).order_by('attempt_count','pk')[:settings.SYNC_BATCH_SIZE])
    batch=[];size=0
    for row in rows:
        data=envelope(row);length=len(canonical(data))
        if length>settings.SYNC_MAX_BODY_BYTES//2:
            row.status='FAILED';row.last_error='EVENT_TOO_LARGE';row.save(update_fields=['status','last_error']);continue
        if size+length>settings.SYNC_MAX_BODY_BYTES//2:break
        batch.append((row,data));size+=length
    if not batch:return 0
    ids=[row.pk for row,_ in batch]
    from django.db.models import F
    SyncOutboxEvent.objects.filter(pk__in=ids).update(attempt_count=F('attempt_count')+1,last_attempt_at=timezone.now())
    try:response=client.request('push',{'events':[data for _,data in batch]})
    except SyncError as exc:
        SyncOutboxEvent.objects.filter(pk__in=ids).update(last_error=exc.code)
        raise
    results=response.get('results')
    if not isinstance(results,list) or len(results)!=len(batch) or {r.get('event_uuid') for r in results if isinstance(r,dict)}!={str(row.event_uuid) for row,_ in batch}:raise SyncError('INVALID_ACK')
    by_id={str(row.event_uuid):row for row,_ in batch}
    for result in results:
        if set(result)!={'event_uuid','status','code'} or result['status'] not in ('APPLIED','DEFERRED','FAILED'):raise SyncError('INVALID_ACK')
    with transaction.atomic():
        for result in results:
            row=by_id[result['event_uuid']]
            # DEFERRED is durable on cloud, but keep local delivery retryable until APPLIED.
            if result['status']=='APPLIED':row.status='SENT';row.sent_at=timezone.now();row.last_error=''
            elif result['status']=='FAILED':row.status='FAILED';row.last_error='REMOTE_APPLY_FAILED'
            else:row.last_error='REMOTE_DEPENDENCY';row.available_at=timezone.now()+timezone.timedelta(seconds=settings.SYNC_INTERVAL_SECONDS)
            row.save(update_fields=['status','sent_at','last_error','available_at'])
            logger.info('sync_event',extra={'event_uuid':str(row.event_uuid),'entity_type':row.entity_type,'sync_status':row.status,'sync_code':row.last_error})
    return len(batch)


def pull_once(client):
    cursor,_=SyncCursor.objects.get_or_create(source='cloud')
    response=client.request('pull',{'after':cursor.last_sequence})
    changes=response.get('changes');commands=response.get('commands');last=response.get('last_sequence')
    if not isinstance(changes,list) or not isinstance(commands,list) or len(changes)>settings.SYNC_BATCH_SIZE or len(commands)>settings.SYNC_BATCH_SIZE:raise SyncError('INVALID_RESPONSE')
    previous=cursor.last_sequence
    for change in changes:
        if not isinstance(change,dict) or set(change)!={'sequence','event'} or type(change['sequence']) is not int or change['sequence']!=previous+1:raise SyncError('CURSOR_GAP')
        previous=change['sequence']
    if type(last) is not int or last!=previous:raise SyncError('INVALID_CURSOR')
    # Persist each inbox before moving the cursor. A crash replays safely.
    for change in changes:receive_event(change['event'],'cloud')
    SyncCursor.objects.filter(pk=cursor.pk).update(last_sequence=last)
    retry_deferred()
    for command in commands:apply_command(command)
    return len(changes)


def ack_once(client):
    rows=list(LocalCommandInbox.objects.filter(acknowledged_at__isnull=True,status__in=['APPLIED','FAILED','REJECTED_STALE']).order_by('pk')[:settings.SYNC_BATCH_SIZE])
    result=client.request('ack',{'commands':[{'command_uuid':str(c.command_uuid),'status':c.status,'code':c.result_code} for c in rows],
        'pending':SyncOutboxEvent.objects.exclude(status='SENT').count(),'app_commit':settings.APP_COMMIT})
    if result!={'status':'ok'}:raise SyncError('INVALID_ACK')
    LocalCommandInbox.objects.filter(pk__in=[r.pk for r in rows]).update(acknowledged_at=timezone.now())


def sync_once(client=None):
    from apps.core.ops.recovery import status
    if status()['active']:raise SyncError('RECOVERY_MODE')
    if not settings.SYNC_ENABLED:return {'disabled':True}
    if settings.DEPLOYMENT_MODE!='local_node':raise SyncError('LOCAL_WORKER_ONLY')
    with worker_lock():
        state,_=SyncRuntimeState.objects.get_or_create(pk=1)
        state.last_attempt_at=timezone.now();state.sync_requested=False;state.save(update_fields=['last_attempt_at','sync_requested'])
        client=client or SyncClient(origin())
        try:
            handshake(client)
            state.last_seen_at=timezone.now();state.save(update_fields=['last_seen_at'])
            pushed=push_once(client);state.last_push_at=timezone.now();state.save(update_fields=['last_push_at'])
            pulled=pull_once(client);state.last_pull_at=timezone.now();state.save(update_fields=['last_pull_at'])
            ack_once(client)
        except SyncError as exc:
            state.last_error=exc.code;state.save(update_fields=['last_error']);logger.warning('sync_failed',extra={'sync_code':exc.code})
            raise
        except Exception:
            state.last_error='WORKER_ERROR';state.save(update_fields=['last_error']);logger.error('sync_failed',extra={'sync_code':'WORKER_ERROR'})
            raise SyncError('WORKER_ERROR')
        state.last_successful_sync_at=timezone.now();state.last_error='';state.save(update_fields=['last_successful_sync_at','last_error'])
        logger.info('sync_succeeded')
        return {'pushed':pushed,'pulled':pulled}


def backoff(failures):return min(settings.SYNC_INTERVAL_SECONDS*(2**min(failures,10)),settings.SYNC_MAX_BACKOFF_SECONDS)

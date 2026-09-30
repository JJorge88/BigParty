"""Opt-in real PostgreSQL 4D disaster drill. All databases/files are temporary.
Run with .venv/bin/python; requires local CREATE DATABASE, never touches operation DBs.
"""
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import psycopg
from psycopg import sql
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]
BASE={**dotenv_values(ROOT/'.env'),**os.environ}
PREFIX='bigparty_4d_'+secrets.token_hex(5)
NAMES={key:PREFIX+'_'+key for key in ('local','cloud','restored_local','restored_cloud')}
PROCESSES=[]


def discard_temporary_database(connection, name):
    assert name in NAMES.values()
    for attempt in range(40):
        try:
            connection.execute(sql.SQL('DROP DATABASE IF EXISTS {}').format(sql.Identifier(name)))
            return
        except psycopg.errors.ObjectInUse:
            time.sleep(.5)
    raise RuntimeError('Temporary database still in use: '+name)


def execute(environment,code=None,arguments=None):
    prefix="import django;django.setup();\n" if code else ''
    result=subprocess.run([sys.executable,*(['-c',prefix+code] if code else arguments)],cwd=ROOT,env=environment,capture_output=True,text=True)
    if result.returncode:
        print(result.stdout[-2000:]);print(result.stderr[-5000:]);raise RuntimeError('Temporary drill phase failed')
    if result.stdout.strip():print(result.stdout[-3000:].strip(),flush=True)


def main():
    admin=psycopg.connect(dbname='postgres',user=BASE['DB_USER'],password=BASE['DB_PASSWORD'],host=BASE.get('DB_HOST','127.0.0.1'),port=BASE.get('DB_PORT','5432'),autocommit=True)
    temporary=tempfile.TemporaryDirectory(prefix='bigparty-4d-drill-')
    try:
        root=Path(temporary.name);envs={};secret=secrets.token_urlsafe(48);snapshot=secrets.token_urlsafe(48)
        import uuid
        node=str(uuid.uuid4())
        for mode in ('local','cloud'):
            admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(NAMES[mode])))
            work=root/mode;work.mkdir()
            envs[mode]={**BASE,'PYTHONPATH':str(ROOT),'BIGPARTY_ENV_FILE':str(work/'absent'),
                'DJANGO_SETTINGS_MODULE':'config.settings.local_node' if mode=='local' else 'config.settings.prod',
                'DEPLOYMENT_MODE':'local_node' if mode=='local' else 'cloud','DB_NAME':NAMES[mode],
                'DJANGO_SECRET_KEY':secrets.token_urlsafe(64),'DJANGO_DEBUG':'False','ALLOWED_HOSTS':'127.0.0.1,localhost,testserver',
                'CSRF_TRUSTED_ORIGINS':'http://127.0.0.1','PUBLIC_BASE_URL':'http://127.0.0.1','APP_VERSION':'4D-drill','APP_COMMIT':'temporary-drill',
                'SYNC_ENABLED':'false','SYNC_SHARED_SECRET':secret,'SYNC_NODE_UUID':node,'SYNC_ALLOW_HTTP_DEVELOPMENT':'true',
                'SYNC_SHARED_SECRET_PREVIOUS':'','SYNC_SECRET_PREVIOUS_UNTIL':'','SYNC_COMPATIBLE_APP_VERSIONS':'4D-drill',
                'ACCESS_SNAPSHOT_SIGNING_KEY':snapshot,'LOCAL_NODE_HOSTNAME':'127.0.0.1','LOCAL_NODE_HTTPS':'False','SECURE_SSL_REDIRECT':'False',
                'LOCAL_NODE_ALLOW_DEBUG_PRINTER':'True','PRINTER_BACKEND':'debug','PRINTER_DEBUG_DIR':str(work/'prints'),
                'LOCAL_MEDIA_ROOT':str(work/'public'),'PUBLIC_MEDIA_ROOT':str(work/'public'),'LOCAL_PRIVATE_ROOT':str(work/'private'),
                'EVENT_PROOF_ROOT':str(work/'private/event-proofs'),'RESERVATION_PROOF_ROOT':str(work/'private/reservation-proofs'),
                'LOCAL_LOG_ROOT':str(work/'logs'),'SUPPORT_LOG_ROOT':str(work/'logs'),'SYNC_LOG_ROOT':str(work/'logs'),
                'LOCAL_STATIC_ROOT':str(work/'static'),'OPERATIONS_STATE_ROOT':str(work/'state'),'RECOVERY_MODE':'false',
                'BACKUP_ROOT':str(work/'backups'),'BACKUP_SECONDARY_ROOT':str(work/'secondary'),
                'PG_BIN_DIR':'/opt/homebrew/opt/postgresql@17/bin','MIN_FREE_DISK_GB':'0.05',
                'RATE_LIMIT_ENABLED':'false','SIM_ROOT':str(root),'SIM_NODE':node}
            execute(envs[mode],arguments=['manage.py','migrate','--noinput'])
        execute(envs['local'],code='''
import os,json
from pathlib import Path
from datetime import timedelta
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.utils import timezone
from apps.localnode.models import LocalNodeIdentity
from apps.catalog.models import Category,Product
from apps.tables.models import VenueTable
from apps.venues.models import Area
from apps.cash.models import CashRegister
from apps.cash import services as cash
from apps.orders import services as orders
from apps.payments import services as payments
from apps.reservations import services as reservations
from apps.events import services as events
from apps.events.tests.base import picture
from apps.sync.services import capture_objects,source_gate
from apps.sync.models import SyncOutboxEvent
from apps.sync.registry import REGISTRY
from apps.sync.serializers import envelope
from django.db import transaction
from django.test import override_settings
LocalNodeIdentity.objects.create(node_uuid=os.environ['SIM_NODE'])
call_command('prepare_local_node',verbosity=0)
user=get_user_model().objects.create_superuser(username='drill-manager',password='Only-drill-942!',role='GERENTE')
area=Area.objects.get(slug='sport-bar');table=VenueTable.objects.create(area=area,name='Drill table',capacity=4,reservable_web=True)
category=Category.objects.create(name='Drill',slug='drill')
product=Product.objects.create(category=category,name='Drill drink',slug='drill-drink',base_price=25,track_inventory=True,stock_quantity=20,preparation_route='NONE')
day=cash.open_business_day(user);session=cash.open_cash_session(CashRegister.objects.get(area=area),user,100,user)
order=orders.open_table_order(table,user);orders.add_product_to_order(order,product,2,user);orders.send_order(order,user)
payment=payments.pay_full_balance(order,'CASH',user,received_amount=50,cash_session=session);payments.close_order(order,user)
cash.submit_blind_cash_count(session,150,user);cash.close_cash_session(session,user);cash.close_business_day(day,user)
when=timezone.localtime()+timedelta(days=1)
reservations.create_manual_reservation(table,'Drill visitor','+50255555555',when.date(),when.time().replace(tzinfo=None),2,user,payment_required=False)
event=events.create_event(user,name='Drill event',starts_at=timezone.now()+timedelta(days=2),ends_at=timezone.now()+timedelta(days=2,hours=4),image=picture('banner.png'),maximum_capacity=100)
kind=events.save_ticket_type(event,user,name='General',price=100,capacity=100,sale_starts_at=timezone.now()-timedelta(days=1),sale_ends_at=event.starts_at,max_per_purchase=10)
events.publish_event(event,user)
purchase=events.create_purchase(event,'Drill buyer','+50255555555',{kind.pk:2})
events.confirm_event_payment(events.submit_event_payment(purchase,purchase.amount,'DRILL',picture()),user)
with override_settings(SYNC_ENABLED=True):
 with transaction.atomic():
  source_gate()
  for spec in REGISTRY.values():
   if spec.authority=='local':capture_objects(list(spec.model.objects.all()))
rows=[envelope(row) for row in SyncOutboxEvent.objects.all()]
Path(os.environ['SIM_ROOT'],'outbox.json').write_text(json.dumps(rows))
assert rows
print('PASS representative data: orders/payments/cash/stock/reservation/event/tickets and pending sync')
''')
        execute(envs['local'],arguments=['manage.py','collectstatic','--noinput'])
        execute(envs['local'],code='''
import os,json
from pathlib import Path
from apps.core.ops.backups import backup_full,copy_secondary,verify,read_manifest
full=backup_full();copy_secondary(full);verify(full)
info=read_manifest(full)
Path(os.environ['SIM_ROOT'],'local-manifests.json').write_text(json.dumps({'full':str(full),'database':str(full.parent/info['children'][0]['manifest']),'media':str(full.parent/info['children'][1]['manifest'])}))
db=read_manifest(full.parent/info['children'][0]['manifest']);media=read_manifest(full.parent/info['children'][1]['manifest'])
print('MEASURE local database',db['file_size'],'bytes',db['duration_seconds'],'seconds; media',media['file_size'],'bytes',media['duration_seconds'],'seconds')
''')
        envs['cloud']['SYNC_ENABLED']='true'
        execute(envs['cloud'],code='''
import json,os
from pathlib import Path
from apps.sync.appliers import receive_event,retry_deferred
from apps.sync.models import SyncInboxEvent
for row in json.loads(Path(os.environ['SIM_ROOT'],'outbox.json').read_text()):receive_event(row,os.environ['SIM_NODE'])
retry_deferred()
assert not SyncInboxEvent.objects.exclude(status='APPLIED').exists()
from apps.core.ops.backups import backup_full,read_manifest
full=backup_full();info=read_manifest(full)
Path(os.environ['SIM_ROOT'],'cloud-manifests.json').write_text(json.dumps({'database':str(full.parent/info['children'][0]['manifest'])}))
print('PASS fake Cloud received pending UUIDs before disaster')
''')
        for mode in ('local','cloud'):
            # Destruction applies only to random databases created by this script.
            discard_temporary_database(admin, NAMES[mode])
            manifests=json.loads((root/(mode+'-manifests.json')).read_text())
            execute(envs[mode],arguments=['manage.py','restore_database',manifests['database'],'--target-database',NAMES['restored_'+mode],'--confirm'])
            envs[mode]['DB_NAME']=NAMES['restored_'+mode]
            if mode=='local':
                recovered=root/'restored-media'
                execute(envs[mode],arguments=['manage.py','restore_media',manifests['media'],'--target-directory',str(recovered)])
                # Simulate loss of original media only after its restore is verified.
                shutil=__import__('shutil');shutil.rmtree(root/'local/public');shutil.rmtree(root/'local/private')
                envs[mode]['LOCAL_MEDIA_ROOT']=str(recovered/'public');envs[mode]['LOCAL_PRIVATE_ROOT']=str(recovered)
            execute(envs[mode],arguments=['manage.py','migrate','--check'])
            execute(envs[mode],arguments=['manage.py','verify_restored_system','--manifest',manifests['database']])
            execute(envs[mode],code='''
from django.test import Client
from apps.core.ops.recovery import status
from apps.sync.worker import sync_once
from apps.sync.exceptions import SyncError
assert status()['active']
assert Client().post('/operacion/mesas/1/abrir/').status_code==503
try:sync_once()
except SyncError as exc:assert exc.code=='RECOVERY_MODE'
else:raise AssertionError('worker escaped recovery')
print('PASS persistent recovery blocks business and sync')
''')
            execute(envs[mode],arguments=['manage.py','complete_recovery','--confirm','--sync-reviewed'])
            print('PASS real '+mode+' database destruction, restore and exact fingerprint comparison',flush=True)
        execute(envs['local'],arguments=['manage.py','check_local_node'])
        execute(envs['local'],code='''
from django.contrib.auth import get_user_model
from apps.cash.services import reopen_business_day
from apps.cash.models import BusinessDay
from apps.orders.services import open_table_order
from apps.tables.models import VenueTable
from apps.localnode.models import LocalNodeIdentity
import os
assert str(LocalNodeIdentity.objects.get(pk=1).node_uuid)==os.environ['SIM_NODE']
user=get_user_model().objects.get(username='drill-manager');reopen_business_day(BusinessDay.objects.get(),user,'Recovery drill')
open_table_order(VenueTable.objects.get(name='Drill table'),user)
print('PASS same node identity and POS works after recovery')
''')
        execute(envs['cloud'],code='''
import json,os
from pathlib import Path
from apps.sync.appliers import receive_event
from apps.sync.models import SyncInboxEvent
from apps.orders.models import TableOrder
from apps.payments.models import Payment
before=(SyncInboxEvent.objects.count(),TableOrder.objects.count(),Payment.objects.count())
for row in json.loads(Path(os.environ['SIM_ROOT'],'outbox.json').read_text()):assert receive_event(row,os.environ['SIM_NODE']).status=='APPLIED'
assert before==(SyncInboxEvent.objects.count(),TableOrder.objects.count(),Payment.objects.count())
print('PASS restored pending outbox replay against restored fake Cloud: no duplicate orders/payments/events')
''')
        # Restart Cloud on loopback and reconnect the real restored Local worker.
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
        cloud_process=subprocess.Popen([sys.executable,'-c',
            "import django;django.setup();from django.core.wsgi import get_wsgi_application;from waitress import serve;serve(get_wsgi_application(),host='127.0.0.1',port="+str(port)+",expose_tracebacks=False)"],cwd=ROOT,env=envs['cloud'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        PROCESSES.append(cloud_process)
        import urllib.request
        for attempt in range(100):
            try:
                with urllib.request.urlopen('http://127.0.0.1:'+str(port)+'/healthz/',timeout=1) as response:assert response.status==200
                break
            except OSError:time.sleep(.1)
        else:raise RuntimeError('Temporary Cloud did not start')
        envs['local']['SYNC_ENABLED']='true';envs['local']['SYNC_CLOUD_URL']='http://127.0.0.1:'+str(port)
        execute(envs['local'],code="""
from apps.sync.worker import sync_once
from apps.sync.models import SyncOutboxEvent
before=set(SyncOutboxEvent.objects.values_list('event_uuid',flat=True))
result=sync_once()
assert result['pushed']>0 and not SyncOutboxEvent.objects.exclude(status='SENT').exists()
assert before==set(SyncOutboxEvent.objects.values_list('event_uuid',flat=True))
print('PASS restored Local worker reconnects to restored Cloud over HTTP, UUIDs preserved and pending outbox acknowledged')
""")
        execute(envs['cloud'],code="""
from apps.orders.models import TableOrder
from apps.payments.models import Payment
assert TableOrder.objects.count()==1 and Payment.objects.count()==1
print('PASS no duplicate Cloud orders/payments after actual worker replay')
""")
        for mode in ('local','cloud'):
            execute(envs[mode],arguments=['manage.py','run_maintenance'])
            secure={**envs[mode],'SECURE_SSL_REDIRECT':'true','LOCAL_NODE_HTTPS':'True','CSRF_TRUSTED_ORIGINS':'https://127.0.0.1'}
            execute(secure,arguments=['manage.py','check','--deploy','--fail-level','WARNING'])
            execute(secure,code='''
from django.test import Client
r=Client().get('/this-page-does-not-exist/',secure=True)
assert r.status_code==404 and b'BIG PARTY' in r.content
assert "script-src 'self'" in r['Content-Security-Policy']
assert r['Permissions-Policy'].startswith('camera=(self)')
print('PASS production error page, security headers and deploy checks')
''')
        print('4D DISASTER DRILL COMPLETE',flush=True)
    finally:
        for process in PROCESSES:
            if process.poll() is None:process.terminate();process.wait(timeout=10)
        for name in NAMES.values():
            discard_temporary_database(admin, name)
        admin.close();temporary.cleanup()
        print('All 4D temporary databases/files removed.',flush=True)

if __name__=='__main__':main()

"""Opt-in destructive-to-TEMP-data-only integration harness. Never uses operation DBs.

Run from repository root with .venv Python; requires local PostgreSQL CREATE DATABASE.
Creates two randomly named temporary DBs, real HTTP servers, and removes both in finally.
"""
import os,sys,subprocess,tempfile,secrets,socket,time,json,urllib.request
from pathlib import Path
import psycopg
from psycopg import sql
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]
PYTHON=sys.executable
BASE={**dotenv_values(ROOT/'.env'),**os.environ}
PREFIX='bigparty_4c_validation_'+secrets.token_hex(5)
NAMES=[PREFIX+'_cloud',PREFIX+'_local']
PROCESSES=[]


def free_port():
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));return sock.getsockname()[1]


def main():
    admin=psycopg.connect(dbname='postgres',user=BASE['DB_USER'],password=BASE['DB_PASSWORD'],host=BASE.get('DB_HOST','127.0.0.1'),port=BASE.get('DB_PORT','5432'),autocommit=True)
    created=[]
    try:
        with tempfile.TemporaryDirectory(prefix='bigparty-4c-validation-') as directory:
            root=Path(directory);ports={'cloud':free_port(),'local':free_port()};shared=secrets.token_urlsafe(48)
            import uuid
            node=str(uuid.uuid4());envs={}
            for mode,name in zip(('cloud','local'),NAMES):
                admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)));created.append(name)
                work=root/mode;work.mkdir()
                envs[mode]={**BASE,'PYTHONPATH':str(ROOT),'DJANGO_SETTINGS_MODULE':'config.settings.prod' if mode=='cloud' else 'config.settings.local_node',
                    'DEPLOYMENT_MODE':'cloud' if mode=='cloud' else 'local_node','BIGPARTY_ENV_FILE':str(work/'.absent'),
                    'DJANGO_SECRET_KEY':secrets.token_urlsafe(48),'DJANGO_DEBUG':'False','DB_NAME':name,'DB_HOST':'127.0.0.1',
                    'ALLOWED_HOSTS':'127.0.0.1,localhost,testserver','CSRF_TRUSTED_ORIGINS':f'http://127.0.0.1:{ports[mode]}',
                    'SYNC_ENABLED':'true','SYNC_CLOUD_URL':f'http://127.0.0.1:{ports["cloud"]}','SYNC_SHARED_SECRET':shared,'SYNC_NODE_UUID':node,
                    'SECURE_SSL_REDIRECT':'false','RATE_LIMIT_ENABLED':'false','SYNC_ALLOW_HTTP_DEVELOPMENT':'true','SYNC_BATCH_SIZE':'100','SYNC_CONNECT_TIMEOUT':'1','SYNC_READ_TIMEOUT':'3',
                    'APP_VERSION':'4C-validation','SYNC_COMPATIBLE_APP_VERSIONS':'4C-validation','ACCESS_SNAPSHOT_SIGNING_KEY':shared+'-snapshot',
                    'LOCAL_NODE_HOSTNAME':'127.0.0.1','LOCAL_NODE_PORT':str(ports[mode]),'LOCAL_NODE_BIND_HOST':'127.0.0.1','LOCAL_NODE_HTTPS':'False',
                    'PRINTER_BACKEND':'debug','LOCAL_NODE_ALLOW_DEBUG_PRINTER':'True','LOCAL_MEDIA_ROOT':str(work/'media'),'LOCAL_PRIVATE_ROOT':str(work/'private'),
                    'OPERATIONS_STATE_ROOT':str(work/'state'),'SUPPORT_LOG_ROOT':str(work/'logs'),'LOCAL_LOG_ROOT':str(work/'logs'),'SYNC_LOG_ROOT':str(work/'logs'),'LOCAL_STATIC_ROOT':str(work/'static'),'PRINTER_DEBUG_DIR':str(work/'prints'),
                    'SIM_DATA_DIR':str(work),'SIM_SHARED_DIR':str(root),'SIM_NODE':node}
                execute(mode,['manage.py','migrate','--noinput'],envs)
            def phase(mode,label,code):
                setup="""import os,json,uuid
from pathlib import Path
import django;django.setup()
from django.conf import settings
work=Path(os.environ['SIM_DATA_DIR']); shared=Path(os.environ['SIM_SHARED_DIR'])
settings.MEDIA_ROOT=work/'media';settings.EVENT_PROOF_ROOT=work/'private/events';settings.RESERVATION_PROOF_ROOT=work/'private/reservations'
from django.core.management import call_command
from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model
from apps.sync.models import *
from apps.sync.services import source_gate,capture_objects
from apps.sync.worker import sync_once
from apps.sync.exceptions import SyncError
from apps.catalog.models import Category,Product
from apps.venues.models import Area
from apps.tables.models import VenueTable
from apps.orders.models import TableOrder
from apps.cash.models import BusinessDay,CashRegister,CashSession,CashHandoff
from apps.payments.models import Payment
from apps.inventory.models import InventoryMovement
from apps.orders import services as orders
from apps.cash import services as cash
from apps.payments import services as payments
from apps.inventory import services as inventory
User=get_user_model()
"""
                script=root/'phase.py';script.write_text(setup+'\n'+code)
                execute(mode,[str(script)],envs)
                print('PASS:',label,flush=True)
            phase('local','local identity and baseline fixtures',"""
from apps.localnode.models import LocalNodeIdentity
LocalNodeIdentity.objects.create(node_uuid=os.environ['SIM_NODE'])
call_command('prepare_local_node',verbosity=0)
manager=User.objects.create_superuser(username='local-manager',password='Test-only-943!',role='GERENTE')
waiter=User.objects.create_user(username='local-waiter',first_name='Waiter',role='MESERO')
from django.contrib.auth.models import Permission
waiter.user_permissions.set(Permission.objects.all())
guard=User.objects.create_user(username='local-guard',first_name='Guard',role='GUARDIA')
guard.user_permissions.add(Permission.objects.get(codename='scan_event_ticket'))
area=Area.objects.get(slug='sport-bar')
for name in ('Cash','Pending','Stale','Reserve','ReserveConflict','MergeA','MergeB'):VenueTable.objects.create(area=area,name=name,capacity=4,reservable_web=True)
category=Category.objects.create(name='Validation',slug='validation')
Product.objects.create(name='Stock test',slug='stock-test',category=category,base_price=25,track_inventory=True,stock_quantity=20,preparation_route='NONE')
""")
            phase('cloud','cloud fixtures with different integer IDs',"""
User.objects.create_superuser(username='cloud-manager',password='Test-only-943!',role='GERENTE')
Area.objects.create(name='Unrelated existing area',slug='unrelated-existing-area')
call_command('bootstrap_sync',confirm=True)
""")
            execute('local',['manage.py','collectstatic','--noinput'],envs)
            def start(mode):
                code=f"import django;django.setup();from django.core.wsgi import get_wsgi_application;from waitress import serve;serve(get_wsgi_application(),host='127.0.0.1',port={ports[mode]},threads=4,expose_tracebacks=False)"
                process=subprocess.Popen([PYTHON,'-c',code],cwd=ROOT,env=envs[mode],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);PROCESSES.append(process)
                for _ in range(100):
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{ports[mode]}/healthz/',timeout=1) as response:
                            if response.status==200:return process
                    except OSError:time.sleep(.1)
                raise RuntimeError('Temporary server failed to start')
            cloud=start('cloud');local=start('local')
            phase('local','bootstrap and catalog baseline through HTTP',"call_command('bootstrap_sync',confirm=True)")
            phase('cloud','replicas use UUID references, not matching primary keys',"""
assert Product.objects.get(slug='stock-test').stock_quantity==20
assert Area.objects.get(slug='sport-bar').pk!=1
assert not User.objects.get(username__startswith='sync-',first_name='Waiter').has_usable_password()
assert not SyncInboxEvent.objects.exclude(status='APPLIED').exists(),list(SyncInboxEvent.objects.exclude(status='APPLIED').values('entity_type','error'))
""")
            cloud.terminate();cloud.wait(timeout=10)
            phase('local','offline POS and simulated 30-minute outage',"""
from unittest.mock import patch
from apps.sync.worker import backoff
manager=User.objects.get(username='local-manager');waiter=User.objects.get(username='local-waiter')
day=cash.open_business_day(manager)
register=CashRegister.objects.get(area__slug='sport-bar');session=cash.open_cash_session(register,manager,'100',manager)
product=Product.objects.get(slug='stock-test')
order=orders.open_table_order(VenueTable.objects.get(name='Cash'),manager,responsible_waiter=waiter)
orders.add_product_to_order(order,product,2,manager);orders.send_order(order,manager)
payment=payments.pay_full_balance(order,'CASH',waiter,received_amount='50');payments.close_order(order,manager)
cash.confirm_cash_handoff(payment,session,manager);cash.create_cash_withdrawal(session,'10','Change',manager,manager)
inventory.receive_stock(product,10,user=manager);inventory.adjust_stock(product,-1,user=manager,reason='Count')
product.refresh_from_db();assert product.stock_quantity==27
pending=SyncOutboxEvent.objects.filter(status='PENDING').count();assert pending>0
elapsed=0;failures=0
with patch('apps.sync.worker.SyncClient.request',side_effect=SyncError('NETWORK_UNAVAILABLE')):
 while elapsed<1800:
  try:sync_once()
  except SyncError:pass
  elapsed+=backoff(failures);failures+=1
assert SyncOutboxEvent.objects.filter(status='PENDING').count()==pending
""")
            local.terminate();local.wait(timeout=10);local=start('local')
            cloud=start('cloud')
            phase('local','restart and reconnect drain persistent outbox',"""
for _ in range(20):
 result=sync_once()
 if not result['pushed']:break
assert not SyncOutboxEvent.objects.exclude(status='SENT').exists(),list(SyncOutboxEvent.objects.exclude(status='SENT').values('entity_type','last_error'))
""")
            phase('cloud','exact replicated order, cash and stock 27',"""
assert Product.objects.get(slug='stock-test').stock_quantity==27
assert InventoryMovement.objects.count()==3
assert TableOrder.objects.filter(status='CLOSED').count()==1
assert Payment.objects.count()==1
assert CashHandoff.objects.get().status=='DELIVERED'
assert cash.get_expected_cash(CashSession.objects.get())==140
""")
            phase('local','pending transfer for command channel',"""
manager=User.objects.get(username='local-manager')
order=orders.open_table_order(VenueTable.objects.get(name='Pending'),manager)
product=Product.objects.get(slug='stock-test')
# Keep the stock test at exactly 27; this service is not inventory tracked.
from apps.catalog.management_services import save_product
service=save_product({'category':product.category,'name':'Service','slug':'service','base_price':25,'track_inventory':False,'preparation_route':'NONE'},user=manager)
orders.add_product_to_order(order,service,1,manager);orders.send_order(order,manager)
payments.pay_full_balance(order,'TRANSFER',manager,reference='MANUAL-VALIDATION')
sync_once()
""")
            phase('cloud','remote manager requests confirmation without editing replica',"""
from apps.sync.commands import request_payment_command
payment=Payment.objects.get(status='PENDING')
request_payment_command(payment,User.objects.get(username='cloud-manager'),'confirm')
payment.refresh_from_db();assert payment.status=='PENDING'
""")
            phase('local','command applies once through existing payment service',"""
sync_once();sync_once()
assert Payment.objects.get(reference='MANUAL-VALIDATION').status=='CONFIRMED'
assert LocalCommandInbox.objects.get().status=='APPLIED'
payments.close_order(Payment.objects.get(reference='MANUAL-VALIDATION').order,User.objects.get(username='local-manager'))
session=CashSession.objects.get();manager=User.objects.get(username='local-manager')
cash.submit_blind_cash_count(session,'140',manager);cash.close_cash_session(session,manager)
sync_once()
""")
            phase('cloud','ACK and payment replica confirmed',"""
assert CloudToLocalCommand.objects.get().status=='APPLIED'
assert Payment.objects.get(reference='MANUAL-VALIDATION').status=='CONFIRMED'
assert CashSession.objects.get().status=='CLOSED'
assert CashSession.objects.get().difference==0
""")
            phase('local','pending payment for stale command',"""
manager=User.objects.get(username='local-manager')
order=orders.open_table_order(VenueTable.objects.get(name='Stale'),manager)
orders.add_product_to_order(order,Product.objects.get(slug='service'),1,manager);orders.send_order(order,manager)
payments.pay_full_balance(order,'TRANSFER',manager,reference='STALE-VALIDATION');sync_once()
""")
            phase('cloud','queue command with expected pending version',"""
from apps.sync.commands import request_payment_command
request_payment_command(Payment.objects.get(reference='STALE-VALIDATION'),User.objects.get(username='cloud-manager'),'confirm')
""")
            phase('local','local rejection precedes remote command',"""
payments.reject_pending_payment(Payment.objects.get(reference='STALE-VALIDATION'),User.objects.get(username='local-manager'),'Changed locally')
sync_once();sync_once()
assert LocalCommandInbox.objects.order_by('pk').last().status=='REJECTED_STALE'
assert Payment.objects.get(reference='STALE-VALIDATION').status=='REJECTED'
""")
            phase('cloud','stale ACK leaves rejected payment untouched',"""
assert CloudToLocalCommand.objects.order_by('pk').last().status=='REJECTED'
assert Payment.objects.get(reference='STALE-VALIDATION').status=='REJECTED'
""")
            phase('cloud','cloud reservation and ticket sale feed',"""
from datetime import timedelta
from apps.reservations import services as reservations
from apps.events import services as events
from apps.events.tests.base import picture
manager=User.objects.get(username='cloud-manager');when=timezone.localtime()+timedelta(days=1)
reservation=reservations.create_manual_reservation(VenueTable.objects.get(name='Reserve'),'Visitor','+50255555555',when.date(),when.time().replace(tzinfo=None),2,manager,payment_required=False)
assert reservation.status=='CONFIRMED'
event=events.create_event(manager,name='Sync event',starts_at=timezone.now()+timedelta(days=2),ends_at=timezone.now()+timedelta(days=2,hours=4),image=picture('banner.png'),maximum_capacity=100)
kind=events.save_ticket_type(event,manager,name='General',price=100,capacity=100,sale_starts_at=timezone.now()-timedelta(days=1),sale_ends_at=event.starts_at,max_per_purchase=10)
event=events.publish_event(event,manager)
purchase=events.create_purchase(event,'Buyer not synced','+50255555555',{kind.pk:2})
payment=events.submit_event_payment(purchase,purchase.amount,'EVENT-TEST',picture())
tickets=events.confirm_event_payment(payment,manager)
(shared/'qr.json').write_text(json.dumps([ticket.qr_token for ticket in tickets]))
""")
            phase('local','automatic snapshot and reservation mirrors',"""
sync_once()
from apps.reservations.models import Reservation
from apps.localnode.models import LocalAccessTicket
assert Reservation.objects.get().status=='CONFIRMED'
assert LocalAccessTicket.objects.count()==2
assert not SyncInboxEvent.objects.exclude(status='APPLIED').exists(),list(SyncInboxEvent.objects.exclude(status='APPLIED').values('entity_type','error'))
""")
            cloud.terminate();cloud.wait(timeout=10)
            phase('local','offline arrival and ticket admission',"""
from apps.reservations.models import Reservation
from apps.reservations.services import confirm_reservation_arrival
from apps.localnode.access import validate_and_use_local_ticket
row=Reservation.objects.get();manager=User.objects.get(username='local-manager');waiter=User.objects.get(username='local-waiter')
confirm_reservation_arrival(row,manager,waiter)
raw=json.loads((shared/'qr.json').read_text())[0];guard=User.objects.get(username='local-guard')
assert validate_and_use_local_ticket(raw,guard)['result']=='VALID'
assert validate_and_use_local_ticket(raw,guard)['result']=='USED'
""")
            cloud=start('cloud')
            phase('local','arrival and access uploaded after reconnect',"sync_once();sync_once()")
            phase('cloud','arrival has one order; source ticket USED',"""
from apps.reservations.models import Reservation
from apps.events.models import EventTicket
assert Reservation.objects.get().status=='ARRIVED'
assert TableOrder.objects.filter(primary_table__name='Reserve').count()==1
assert EventTicket.objects.get(qr_token=json.loads((shared/'qr.json').read_text())[0]).status=='USED'
""")
            phase('local','response lost after apply, safe retry',"""
from apps.sync.client import SyncClient
manager=User.objects.get(username='local-manager')
from apps.catalog.management_services import save_catalog
save_catalog(Category,{'name':'Retry category','slug':'retry-category','is_active':True},user=manager)
class LostResponse(SyncClient):
 def request(self,endpoint,data=None):
  result=super().request(endpoint,data)
  if endpoint=='push':raise SyncError('NETWORK_UNAVAILABLE')
  return result
try:sync_once(client=LostResponse(os.environ['SIM_NODE']))
except SyncError:pass
assert SyncOutboxEvent.objects.filter(status='PENDING').exists()
sync_once()
""")
            phase('cloud','retry creates no duplicate category',"assert Category.objects.filter(slug='retry-category').count()==1")
            phase('cloud','cancel while local snapshot still VALID',"""
from apps.events.services import cancel_event
from apps.events.models import Event
cancel_event(Event.objects.get(name='Sync event'),User.objects.get(username='cloud-manager'),'Cancelled in cloud')
""")
            phase('local','late offline admission creates conflict on reconnect',"""
from apps.localnode.access import validate_and_use_local_ticket
raw=json.loads((shared/'qr.json').read_text())[1]
assert validate_and_use_local_ticket(raw,User.objects.get(username='local-guard'))['result']=='VALID'
sync_once();sync_once()
assert SyncConflict.objects.filter(conflict_type='CANCELLED_ADMISSION').exists()
from django.test import Client
client=Client();client.post('/gerencia/acceso/',{'username':'local-manager','password':'Test-only-943!'})
response=client.get('/gerencia/configuracion/sincronizacion/')
assert response.status_code==200,response.content[:500]
assert b'Admis' in response.content
""")
            phase('cloud','cancellation and both scan records preserved',"""
from apps.events.models import EventTicket
assert EventTicket.objects.filter(status='CANCELLED').count()==2
assert CloudAccessScan.objects.count()==3
assert SyncConflict.objects.filter(conflict_type='CANCELLED_ADMISSION').exists()
""")
            phase('cloud','second reservation for cancellation race',"""
from datetime import timedelta
from apps.reservations import services as reservations
when=timezone.localtime()+timedelta(days=1)
reservations.create_manual_reservation(VenueTable.objects.get(name='ReserveConflict'),'Second visitor','+50255555555',when.date(),when.time().replace(tzinfo=None),2,User.objects.get(username='cloud-manager'),payment_required=False)
""")
            phase('local','receive second confirmed reservation',"sync_once()")
            phase('cloud','cancel reservation before offline arrival',"""
from apps.reservations.models import Reservation
from apps.reservations.services import cancel_reservation
cancel_reservation(Reservation.objects.get(table__name='ReserveConflict'),User.objects.get(username='cloud-manager'),'Cancelled')
""")
            phase('local','arrival conflict retains local account',"""
from apps.reservations.models import Reservation
from apps.reservations.services import confirm_reservation_arrival
row=Reservation.objects.get(table__name='ReserveConflict')
confirm_reservation_arrival(row,User.objects.get(username='local-manager'),User.objects.get(username='local-waiter'))
sync_once();sync_once()
row.refresh_from_db();assert row.status=='ARRIVED' and row.order_id
assert TableOrder.objects.filter(primary_table__name='ReserveConflict').count()==1
assert SyncConflict.objects.filter(conflict_type='RESERVATION_ARRIVAL_CONFLICT').exists()
""")
            phase('cloud','cancelled reservation remains cancelled with arrival evidence',"""
from apps.reservations.models import Reservation
assert Reservation.objects.get(table__name='ReserveConflict').status=='CANCELLED'
assert TableOrder.objects.filter(primary_table__name='ReserveConflict').count()==1
assert SyncConflict.objects.filter(conflict_type='RESERVATION_ARRIVAL_CONFLICT').exists()
""")
            phase('local','create split orders before merging',"""
manager=User.objects.get(username='local-manager')
first=orders.open_table_order(VenueTable.objects.get(name='MergeA'),manager)
second=orders.open_table_order(VenueTable.objects.get(name='MergeB'),manager,billing_mode='SPLIT')
account=orders.create_subaccount(second,'Guest',manager)
orders.add_product_to_order(second,Product.objects.get(slug='service'),1,manager,subaccount=account)
orders.send_order(second,manager);sync_once()
""")
            phase('local','merge keeps subaccount composite references valid',"""
manager=User.objects.get(username='local-manager')
orders.merge_orders(TableOrder.objects.get(primary_table__name='MergeA'),TableOrder.objects.get(primary_table__name='MergeB'),manager)
sync_once();sync_once()
""")
            phase('cloud','merged split order has no deferred relation cycle',"""
first=TableOrder.objects.get(primary_table__name='MergeA');second=TableOrder.objects.get(primary_table__name='MergeB')
assert second.status=='MERGED' and second.merged_into_id==first.pk
assert first.subaccounts.get().lines.get().order_id==first.pk
assert not SyncInboxEvent.objects.exclude(status='APPLIED').exists(),list(SyncInboxEvent.objects.exclude(status='APPLIED').values('entity_type','error'))
""")
            phase('local','1000 events with batch 100',"""
from apps.sync.services import emit,get_or_create_sync_identity
with transaction.atomic():
 source_gate()
 for n in range(1000):
  obj=Category.objects.create(name=f'Load {n}',slug=f'load-{n}')
  capture_objects([obj])
assert SyncOutboxEvent.objects.filter(status='PENDING').count()==1000
rounds=0
while SyncOutboxEvent.objects.filter(status='PENDING').exists():
 result=sync_once();rounds+=1
 assert result['pushed']<=100
 assert rounds<=10
assert rounds==10
""")
            phase('cloud','1000 events applied exactly once',"""
assert Category.objects.filter(slug__startswith='load-').count()==1000
assert not SyncInboxEvent.objects.exclude(status='APPLIED').exists(),list(SyncInboxEvent.objects.exclude(status='APPLIED').values('entity_type','error'))
""")
            for process in PROCESSES:
                if process.poll() is None:process.terminate();process.wait(timeout=10)
            print('TWO-INSTANCE VALIDATION COMPLETE',flush=True)
    finally:
        for process in PROCESSES:
            if process.poll() is None:process.terminate();process.wait(timeout=10)
        for name in created:admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
        admin.close()
        print('Temporary servers stopped and both temporary databases removed.',flush=True)


def execute(mode,args,envs):
    result=subprocess.run([PYTHON,*args],cwd=ROOT,env=envs[mode],capture_output=True,text=True)
    if result.returncode:
        print(result.stdout[-3000:]);print(result.stderr[-6000:])
        for config in envs.values():
            log=Path(config['SYNC_LOG_ROOT'])/'sync.log'
            if log.exists():print(log.read_text()[-4000:])
        raise RuntimeError('Validation failed in '+mode)

if __name__=='__main__':main()

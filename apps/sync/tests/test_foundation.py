import json
import time
import uuid
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.test import TestCase,override_settings
from django.utils import timezone
from apps.localnode.models import LocalNodeIdentity
from apps.catalog.models import Category,Product
from apps.venues.models import Area
from apps.tables.models import VenueTable
from apps.orders import services as orders
from apps.cash import services as cash
from apps.inventory import services as inventory
from apps.sync.models import SyncIdentity,SyncOutboxEvent,SyncInboxEvent,CloudSyncChange
from apps.sync.services import sync_atomic,track,capture_objects,source_gate
from apps.sync.appliers import receive_event
from apps.sync.serializers import envelope,canonical
from apps.sync.security import signature
from apps.sync.exceptions import SyncError

NODE='535b2c88-8368-4b48-a202-de61244f0a15'
KEY='test-only-sync-secret-that-has-32-bytes'

@override_settings(SYNC_ENABLED=True,DEPLOYMENT_MODE='local_node',SYNC_SHARED_SECRET=KEY,SYNC_NODE_UUID=NODE,APP_VERSION='4C',SYNC_COMPATIBLE_APP_VERSIONS=['4C'],ACCESS_SNAPSHOT_SIGNING_KEY=KEY)
class SyncTests(TestCase):
    def setUp(self):
        LocalNodeIdentity.objects.create(node_uuid=NODE)
        self.user=get_user_model().objects.create_superuser(username='sync-test',password='Only-test-981!',role='GERENTE')
        self.area=Area.objects.create(name='Bar',slug='bar')
        self.table=VenueTable.objects.create(name='Mesa',area=self.area,capacity=4)
        self.category=Category.objects.create(name='Drinks',slug='drinks')
        self.product=Product.objects.create(name='Drink',slug='drink',category=self.category,base_price=25,track_inventory=True,stock_quantity=20,preparation_route='NONE')

    def test_transactional_capture_complete_order_and_no_secrets(self):
        cash.open_business_day(self.user)
        order=orders.open_table_order(self.table,self.user)
        orders.add_product_to_order(order,self.product,2,self.user)
        orders.send_order(order,self.user)
        kinds=set(SyncOutboxEvent.objects.values_list('entity_type',flat=True))
        self.assertTrue({'orders.tableorder','orders.orderline','orders.orderlinecomponent','inventory.inventorymovement','inventory.stock_snapshot','accounts.user'}.issubset(kinds),kinds)
        raw=json.dumps(list(SyncOutboxEvent.objects.values_list('payload',flat=True)))
        for forbidden in ['pin_hash','password','session_key','secret_key','binding_version',self.user.password]:self.assertNotIn(forbidden,raw)
        for payload in SyncOutboxEvent.objects.values_list('payload',flat=True):
            self.assertFalse(any(k.endswith('_id') for k in payload))
        self.product.refresh_from_db();self.assertEqual(self.product.stock_quantity,18)

    def test_rollback_loses_neither_side(self):
        try:
            with transaction.atomic():
                inventory.receive_stock(self.product,10,user=self.user)
                raise RuntimeError('rollback')
        except RuntimeError:pass
        self.product.refresh_from_db();self.assertEqual(self.product.stock_quantity,20)
        self.assertFalse(SyncOutboxEvent.objects.exists())

    def test_versions_increment_and_same_snapshot_does_not_emit(self):
        inventory.receive_stock(self.product,10,user=self.user)
        count=SyncOutboxEvent.objects.count()
        with transaction.atomic():source_gate();capture_objects([self.product])
        self.assertEqual(SyncOutboxEvent.objects.count(),count)
        inventory.adjust_stock(self.product,-1,user=self.user,reason='count')
        rows=SyncOutboxEvent.objects.filter(entity_type='inventory.stock_snapshot')
        self.assertEqual(rows.last().entity_version,2)
        self.assertEqual(rows.last().payload['stock'],29)

    def test_remote_duplicate_old_version_and_authority(self):
        with transaction.atomic():source_gate();capture_objects([self.category])
        row=SyncOutboxEvent.objects.get(entity_type='catalog.category');data=envelope(row)
        identity=SyncIdentity.objects.get(entity_uuid=row.entity_uuid);identity.version=0;identity.save()
        with override_settings(DEPLOYMENT_MODE='cloud'):
            first=receive_event(data,NODE);self.assertEqual(first.status,'APPLIED',first.error)
            self.assertEqual(receive_event(data,NODE).status,'APPLIED')
            self.assertEqual(SyncInboxEvent.objects.count(),1)
            self.assertEqual(Category.objects.count(),1)
            modified={**data,'payload':{**data['payload'],'name':'tampered'}}
            with self.assertRaises(SyncError):receive_event(modified,NODE)
            with self.assertRaises(PermissionDenied):inventory.receive_stock(self.product,1,user=self.user)

    def test_missing_dependency_durable(self):
        with transaction.atomic():source_gate();capture_objects([self.product])
        data=envelope(SyncOutboxEvent.objects.get(entity_type='catalog.product'))
        data['entity_uuid']=str(uuid.uuid4());data['payload']['category_uuid']=str(uuid.uuid4())
        with override_settings(DEPLOYMENT_MODE='cloud'):
            row=receive_event(data,NODE)
        self.assertEqual(row.status,'DEFERRED');self.assertEqual(Product.objects.count(),1)

    def request_sync(self,data,**headers):
        path='/api/sync/v1/push/';body=canonical({'protocol':1,'app_version':'4C',**data});stamp=str(int(time.time()))
        defaults={'HTTP_X_BP_NODE':NODE,'HTTP_X_BP_TIMESTAMP':stamp,'HTTP_X_BP_SIGNATURE':signature('POST',path,stamp,body,NODE)}
        return self.client.post(path,body,content_type='application/json',secure=True,**(defaults|headers))

    @override_settings(DEPLOYMENT_MODE='cloud')
    def test_hmac_signature_timestamp_node_and_browser_session(self):
        self.assertEqual(self.request_sync({'events':[]}).status_code,200)
        for headers in [{'HTTP_X_BP_SIGNATURE':''},{'HTTP_X_BP_SIGNATURE':'bad'},{'HTTP_X_BP_TIMESTAMP':str(int(time.time())-301)},{'HTTP_X_BP_NODE':str(uuid.uuid4())}]:
            self.assertEqual(self.request_sync({'events':[]},**headers).status_code,401)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post('/api/sync/v1/push/',json.dumps({'events':[]}),content_type='application/json',secure=True).status_code,401)

    def test_nonempty_http_batch_ack_and_body_tampering(self):
        with transaction.atomic():source_gate();capture_objects([self.category])
        row=SyncOutboxEvent.objects.get(entity_type='catalog.category');data=envelope(row)
        with override_settings(DEPLOYMENT_MODE='cloud'):
            response=self.request_sync({'events':[data]})
            self.assertEqual(response.status_code,200,response.content)
            self.assertEqual(response.json()['results'][0]['status'],'APPLIED')
            other=canonical({'protocol':1,'app_version':'4C','events':[]})
            stamp=str(int(time.time()))
            bad=signature('POST','/api/sync/v1/push/',stamp,other,NODE)
            self.assertEqual(self.request_sync({'events':[data]},HTTP_X_BP_SIGNATURE=bad,HTTP_X_BP_TIMESTAMP=stamp).status_code,401)

    def test_unsupported_schema_and_apply_error_do_not_change_domain(self):
        with transaction.atomic():source_gate();capture_objects([self.category])
        data=envelope(SyncOutboxEvent.objects.get(entity_type='catalog.category'))
        data['schema_version']=999
        with override_settings(DEPLOYMENT_MODE='cloud'):
            event=receive_event(data,NODE)
            self.assertEqual(event.status,'FAILED');self.assertEqual(event.error,'UNSUPPORTED_SCHEMA')
        self.category.refresh_from_db();self.assertEqual(self.category.name,'Drinks')

    def test_disabled_sync_preserves_pos_and_emits_nothing(self):
        with override_settings(SYNC_ENABLED=False):inventory.receive_stock(self.product,1,user=self.user)
        self.assertFalse(SyncOutboxEvent.objects.exists())
        self.product.refresh_from_db();self.assertEqual(self.product.stock_quantity,21)

    def test_source_failure_rolls_back_business_write(self):
        with patch('apps.sync.services.emit',side_effect=RuntimeError('capture failed')):
            with self.assertRaises(RuntimeError):inventory.receive_stock(self.product,10,user=self.user)
        self.product.refresh_from_db();self.assertEqual(self.product.stock_quantity,20)
        self.assertFalse(self.product.inventory_movements.exists())

    def test_cloud_feed_is_versioned_and_reuses_signed_snapshot(self):
        from apps.events.models import EventSettings
        from apps.events.services import configure_settings
        with override_settings(DEPLOYMENT_MODE='cloud'):
            configure_settings(self.user,purchase_hold_minutes=20,payment_window_minutes=60,transfer_instructions='Local bank')
        self.assertEqual(CloudSyncChange.objects.count(),1)
        self.assertEqual(CloudSyncChange.objects.get().sequence,1)
        self.assertFalse(SyncOutboxEvent.objects.exists())

    def test_client_timeout_dns_500_malformed_and_signature_failure(self):
        import socket
        from unittest.mock import MagicMock
        from apps.sync.client import SyncClient
        from apps.sync.security import response_signature
        with override_settings(SYNC_CLOUD_URL='https://sync.example.invalid'):
            for failure in (TimeoutError(),socket.gaierror()):
                with patch('apps.sync.client.http.client.HTTPSConnection',side_effect=None) as constructor:
                    constructor.return_value.connect.side_effect=failure
                    with self.assertRaisesMessage(SyncError,'NETWORK_UNAVAILABLE'):SyncClient(NODE).request('status')
            for raw,status,expected in [(b'not-json',200,'INVALID_RESPONSE'),(canonical({'code':'SYNC_UNAVAILABLE'}),500,'SYNC_UNAVAILABLE'),(canonical({}),200,'INVALID_RESPONSE_SIGNATURE')]:
                with patch('apps.sync.client.http.client.HTTPSConnection') as constructor,patch('apps.sync.client.time.time',return_value=123):
                    response=constructor.return_value.getresponse.return_value
                    response.status=status;response.read.return_value=raw
                    signed=signature('GET','/api/sync/v1/status/','123',b'',NODE)
                    response.getheader.return_value=response_signature(signed,raw) if expected!='INVALID_RESPONSE_SIGNATURE' else 'bad'
                    with self.assertRaisesMessage(SyncError,expected):SyncClient(NODE).request('status')

    def test_incompatible_handshake_keeps_outbox_and_pos_usable(self):
        from unittest.mock import Mock
        from apps.sync.worker import sync_once,backoff
        with transaction.atomic():source_gate();capture_objects([self.category])
        client=Mock(node=NODE);client.request.return_value={'protocol':999,'app_version':'4C','node_uuid':NODE}
        with self.assertRaisesMessage(SyncError,'INCOMPATIBLE_PROTOCOL_OR_APP'):sync_once(client)
        self.assertEqual(SyncOutboxEvent.objects.get().status,'PENDING')
        inventory.receive_stock(self.product,1,user=self.user)
        self.product.refresh_from_db();self.assertEqual(self.product.stock_quantity,21)
        self.assertEqual([backoff(n) for n in range(6)],[15,30,60,120,240,300])

    def test_database_apply_error_is_durable_and_not_applied(self):
        from django.db import IntegrityError
        from apps.sync.registry import Entity
        with transaction.atomic():source_gate();capture_objects([self.category])
        data=envelope(SyncOutboxEvent.objects.get(entity_type='catalog.category'))
        with override_settings(DEPLOYMENT_MODE='cloud'),patch.object(Entity,'apply',side_effect=IntegrityError('constraint')):
            row=receive_event(data,NODE)
        self.assertEqual(row.status,'DEFERRED');self.assertIsNone(row.applied_at)
        self.assertEqual(Category.objects.count(),1)

    def test_old_entity_version_cannot_overwrite_newer(self):
        with transaction.atomic():source_gate();capture_objects([self.category])
        data=envelope(SyncOutboxEvent.objects.get(entity_type='catalog.category'))
        self.category.name='Newest';self.category.save()
        with transaction.atomic():source_gate();capture_objects([self.category])
        data['event_uuid']=str(uuid.uuid4())
        with override_settings(DEPLOYMENT_MODE='cloud'):self.assertEqual(receive_event(data,NODE).status,'APPLIED')
        self.category.refresh_from_db();self.assertEqual(self.category.name,'Newest')

    def test_remote_command_stale_and_replayed_is_terminal(self):
        from apps.payments import services as payments
        from apps.sync.commands import apply_command
        cash.open_business_day(self.user);order=orders.open_table_order(self.table,self.user)
        orders.add_product_to_order(order,self.product,1,self.user);orders.send_order(order,self.user)
        payment=payments.pay_full_balance(order,'TRANSFER',self.user,reference='Stale')
        identity=SyncIdentity.objects.get(model_label='payments.payment',object_pk=str(payment.pk))
        command={'command_uuid':str(uuid.uuid4()),'target_node_uuid':NODE,'command_type':'VERIFY_OPERATIONAL_PAYMENT','created_at':timezone.now().isoformat(),
            'payload':{'payment_uuid':str(identity.entity_uuid),'expected_version':identity.version,'actor_uuid':str(uuid.uuid4()),'actor':{'name':'Manager','role':'GERENTE','active':True},'permission':'payments.verify_transfer_payment','reason':''}}
        payments.reject_pending_payment(payment,self.user,'Changed locally')
        row=apply_command(command);self.assertEqual(row.status,'REJECTED_STALE')
        self.assertEqual(apply_command(command).pk,row.pk)
        payment.refresh_from_db();self.assertEqual(payment.status,'REJECTED')
        command['command_uuid']=str(uuid.uuid4());command['payload']['actor']='invalid'
        self.assertEqual(apply_command(command).status,'FAILED')

    def test_browser_wrong_authority_posts_are_blocked(self):
        self.client.force_login(self.user)
        with override_settings(DEPLOYMENT_MODE='cloud'):
            for path in ['/gerencia/catalogo/productos/crear/','/gerencia/inventario/','/gerencia/usuarios/','/caja/']:
                self.assertEqual(self.client.post(path).status_code,403,path)
        self.assertEqual(self.client.post('/gerencia/configuracion/bank/').status_code,403)
        self.assertEqual(self.client.post('/gerencia/eventos/crear/').status_code,403)

    def test_deferred_events_do_not_starve_new_dependencies(self):
        from unittest.mock import Mock
        from apps.sync.worker import push_once
        with transaction.atomic():source_gate();capture_objects([self.category])
        first=SyncOutboxEvent.objects.get();first.attempt_count=9;first.save()
        category=Category.objects.create(name='Next',slug='next')
        with transaction.atomic():source_gate();capture_objects([category])
        fresh=SyncOutboxEvent.objects.latest('pk')
        client=Mock();client.request.return_value={'results':[{'event_uuid':str(fresh.event_uuid),'status':'APPLIED','code':''}]}
        with override_settings(SYNC_BATCH_SIZE=1):push_once(client)
        fresh.refresh_from_db();first.refresh_from_db()
        self.assertEqual(fresh.status,'SENT');self.assertEqual(first.status,'PENDING')

    def test_primary_link_snapshot_is_explicit_and_transactional(self):
        cash.open_business_day(self.user);order=orders.open_table_order(self.table,self.user)
        event=SyncOutboxEvent.objects.filter(entity_type='orders.tableorder').last()
        link=event.payload['primary_link']
        self.assertEqual(link['payload']['order_uuid'],str(event.entity_uuid))
        self.assertGreater(link['entity_version'],0)
        self.assertNotIn('order_id',link['payload'])

    def test_batch_query_growth_is_linear(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from apps.sync.registry import REGISTRY
        from apps.sync.serializers import serialize_entity
        template=serialize_entity(REGISTRY['catalog.category'],self.category)
        counts=[]
        with override_settings(DEPLOYMENT_MODE='cloud'):
            for count in (10,100):
                rows=[]
                for n in range(count):
                    rows.append({'event_uuid':str(uuid.uuid4()),'entity_uuid':str(uuid.uuid4()),'entity_type':'catalog.category','operation':'UPSERT','entity_version':1,'schema_version':1,'payload':{**template,'name':f'Batch {count} {n}','slug':f'batch-{count}-{n}'}})
                with CaptureQueriesContext(connection) as queries:
                    response=self.request_sync({'events':rows})
                self.assertEqual(response.status_code,200,response.content)
                self.assertTrue(all(row['status']=='APPLIED' for row in response.json()['results']))
                counts.append(len(queries))
        self.assertLessEqual(counts[1],counts[0]*11)
        print(f' Sync query check: 10 events={counts[0]}, 100 events={counts[1]}.',flush=True)

    def test_cloud_sequence_rolls_back_without_a_gap(self):
        from apps.events.services import configure_settings
        with override_settings(DEPLOYMENT_MODE='cloud'):
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    configure_settings(self.user,purchase_hold_minutes=20)
                    raise RuntimeError('rollback')
            self.assertFalse(CloudSyncChange.objects.exists())
            configure_settings(self.user,purchase_hold_minutes=25)
            self.assertEqual(CloudSyncChange.objects.get().sequence,1)

    def test_status_ui_cloud_commands_and_local_request_only_sets_flag(self):
        from apps.sync.models import CloudToLocalCommand,SyncRuntimeState
        from apps.sync.views import status
        from django.test import RequestFactory
        # Use the existing protected session entry point, not a bypass of view permissions.
        self.client.post('/gerencia/acceso/',{'username':'sync-test','password':'Only-test-981!'})
        CloudToLocalCommand.objects.create(target_node_uuid=NODE,command_type='VERIFY_OPERATIONAL_PAYMENT',created_by=self.user,payload={})
        with override_settings(DEPLOYMENT_MODE='cloud'):
            response=self.client.get('/gerencia/configuracion/sincronizacion/')
            self.assertEqual(response.status_code,200)
            self.assertContains(response,'PENDING')
            self.assertNotContains(response,KEY)
        with patch('apps.sync.client.SyncClient.request',side_effect=AssertionError('HTTP in UI')):
            response=self.client.post('/gerencia/configuracion/sincronizacion/',{'action':'sync'})
        self.assertEqual(response.status_code,302)
        self.assertTrue(SyncRuntimeState.objects.get(pk=1).sync_requested)

    def test_remote_rejection_uses_service_once_without_credentials(self):
        from apps.payments import services as payments
        from apps.sync.commands import apply_command
        from apps.sync.models import RemoteActor
        cash.open_business_day(self.user);order=orders.open_table_order(self.table,self.user)
        orders.add_product_to_order(order,self.product,1,self.user);orders.send_order(order,self.user)
        payment=payments.pay_full_balance(order,'TRANSFER',self.user,reference='Remote rejection')
        identity=SyncIdentity.objects.get(model_label='payments.payment',object_pk=str(payment.pk))
        command={'command_uuid':str(uuid.uuid4()),'target_node_uuid':NODE,'command_type':'REJECT_OPERATIONAL_PAYMENT','created_at':timezone.now().isoformat(),
            'payload':{'payment_uuid':str(identity.entity_uuid),'expected_version':identity.version,'actor_uuid':str(uuid.uuid4()),'actor':{'name':'Cloud manager','role':'GERENTE','active':True},'permission':'payments.reject_transfer_payment','reason':'No transfer found'}}
        self.assertEqual(apply_command(command).status,'APPLIED')
        count=SyncOutboxEvent.objects.count()
        self.assertEqual(apply_command(command).status,'APPLIED')
        self.assertEqual(SyncOutboxEvent.objects.count(),count)
        payment.refresh_from_db();self.assertEqual(payment.status,'REJECTED')
        actor=RemoteActor.objects.get().user
        self.assertFalse(actor.has_usable_password());self.assertEqual(actor.pin_hash,'!')
        self.assertFalse(actor.user_permissions.exists());self.assertFalse(actor.is_staff)

    def test_empty_quick_sale_is_captured_at_its_own_service_boundary(self):
        from apps.cash.models import CashRegister
        from apps.operations.cash_ordering import create_quick_sale
        day=cash.open_business_day(self.user)
        register=CashRegister.objects.create(name='Quick',code='quick',area=self.area)
        session=cash.open_cash_session(register,self.user,100,self.user)
        context={'user':self.user,'day':day,'session':session,'register':register}
        order=create_quick_sale(context)
        identity=SyncIdentity.objects.get(model_label='orders.tableorder',object_pk=str(order.pk))
        event=SyncOutboxEvent.objects.get(entity_uuid=identity.entity_uuid)
        self.assertEqual(event.payload['order_type'],'QUICK_SALE')
        self.assertIsNone(event.payload['primary_link'])
        self.assertFalse(order.lines.exists())

    def test_deferred_retry_rotates_past_unresolved_records(self):
        from apps.sync.appliers import retry_deferred
        with transaction.atomic():source_gate();capture_objects([self.product])
        template=envelope(SyncOutboxEvent.objects.get(entity_type='catalog.product'))
        missing=str(uuid.uuid4());later=str(uuid.uuid4())
        with override_settings(DEPLOYMENT_MODE='cloud'):
            events=[]
            for index,parent in enumerate((missing,later)):
                data={**template,'event_uuid':str(uuid.uuid4()),'entity_uuid':str(uuid.uuid4()),'payload':{**template['payload'],'category_uuid':parent,'slug':f'deferred-{index}'}}
                events.append(receive_event(data,NODE))
            category=Category.objects.create(name='Resolved parent',slug='resolved-parent')
            SyncIdentity.objects.create(entity_uuid=later,model_label='catalog.category',object_pk=str(category.pk),origin=NODE,version=1)
            retry_deferred(limit=1);retry_deferred(limit=1)
        events[0].refresh_from_db();events[1].refresh_from_db()
        self.assertEqual(events[0].status,'DEFERRED');self.assertEqual(events[1].status,'APPLIED')

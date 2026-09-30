import copy
import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from pathlib import Path
from threading import Barrier
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.management import call_command, CommandError
from django.db import connections, transaction, DatabaseError
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from apps.events.tests.base import Fixtures
from apps.localnode.models import LocalNodeIdentity, LocalEventAccessSnapshot, LocalAccessTicket, LocalAccessScan
from apps.localnode.snapshots import signed_snapshot, import_snapshot, canonical, CONTENT_KEYS
from apps.localnode.access import validate_and_use_local_ticket

KEY = 'test-only-snapshot-signing-key-32-bytes'


def resign(data):
    data['checksum'] = data['version'] = hashlib.sha256(canonical({k:data[k] for k in CONTENT_KEYS})).hexdigest()
    data['signature'] = hmac.new(KEY.encode(), canonical({k:v for k,v in data.items() if k != 'signature'}), hashlib.sha256).hexdigest()
    return data


class SnapshotFixtures(Fixtures):
    def setUp(self):
        super().setUp()
        self.tickets = self.confirm()
        with override_settings(DEPLOYMENT_MODE='development'):
            self.payload = signed_snapshot(self.event)
        LocalNodeIdentity.objects.create()


@override_settings(DEPLOYMENT_MODE='local_node', ACCESS_SNAPSHOT_SIGNING_KEY=KEY)
class SnapshotTests(SnapshotFixtures, TestCase):
    def test_existing_format_digest_and_minimal_data(self):
        row = self.payload['tickets'][0]
        self.assertEqual(set(row), {'token_hash','status','ticket_type'})
        raw = json.dumps(self.payload)
        for private in ['Ana Compradora','55555555','portal_token','amount','buyer_name'] + [t.qr_token for t in self.tickets]:
            self.assertNotIn(private, raw)
        self.assertEqual(self.payload['schema_version'],1)
        self.assertEqual(self.payload['version'],self.payload['checksum'])

    def test_import_idempotent(self):
        snapshot, changed = import_snapshot(self.payload)
        self.assertTrue(changed)
        self.assertFalse(import_snapshot(self.payload)[1])
        self.assertEqual(LocalEventAccessSnapshot.objects.count(),1)
        self.assertEqual(snapshot.tickets.count(),len(self.tickets))

    def test_commands_export_import_and_no_overwrite(self):
        file = Path(self.storage.name)/'snapshot.json'
        with override_settings(DEPLOYMENT_MODE='cloud'):
            call_command('export_event_access_snapshot',str(self.event.pk),str(file),stdout=StringIO())
            with self.assertRaises(CommandError):
                call_command('export_event_access_snapshot',str(self.event.pk),str(file),stdout=StringIO())
        call_command('import_event_access_snapshot',str(file),stdout=StringIO())
        call_command('import_event_access_snapshot',str(file),stdout=StringIO())
        file.write_text('{"schema_version":1,"schema_version":2}')
        with self.assertRaises(CommandError): call_command('import_event_access_snapshot',str(file))
        self.assertEqual(LocalAccessTicket.objects.count(),2)

    def test_corrupt_or_unsigned_rejected_without_writes(self):
        variants = []
        for key, value in [('signature','0'*64),('checksum','0'*64),('event','Changed')]:
            data=copy.deepcopy(self.payload);data[key]=value;variants.append(data)
        data=copy.deepcopy(self.payload);data.pop('signature');variants.append(data)
        for data in variants:
            with self.assertRaises(ValidationError): import_snapshot(data)
        self.assertFalse(LocalAccessTicket.objects.exists())

    def test_authenticated_malformed_fields_rejected(self):
        for key, value in [('schema_version',2),('event_id',True),('source','wrong'),('generated_at','bad'),('event_status','OTHER')]:
            data=copy.deepcopy(self.payload);data[key]=value;resign(data)
            with self.subTest(key=key), self.assertRaises(ValidationError): import_snapshot(data)
        data=copy.deepcopy(self.payload);data['tickets'].append(data['tickets'][0]);resign(data)
        with self.assertRaises(ValidationError): import_snapshot(data)

    def test_wrong_key_rejected(self):
        with override_settings(ACCESS_SNAPSHOT_SIGNING_KEY='different-test-key-at-least-thirty-two'), self.assertRaises(ValidationError):
            import_snapshot(self.payload)

    def test_new_version_preserves_used_and_cancellation_wins(self):
        import_snapshot(self.payload)
        self.assertEqual(validate_and_use_local_ticket(self.tickets[0].qr_token,self.guard)['result'],'VALID')
        data=copy.deepcopy(self.payload);data['event']='New event label';data['generated_at']=timezone.now().isoformat();resign(data)
        import_snapshot(data)
        self.assertEqual(validate_and_use_local_ticket(self.tickets[0].qr_token,self.guard)['result'],'USED')
        used=LocalAccessTicket.objects.get(token_digest=hashlib.sha256(self.tickets[0].qr_token.encode()).hexdigest())
        stamp=used.used_at
        for row in data['tickets']: row['status']='CANCELLED'
        data['generated_at']=timezone.now().isoformat();resign(data);import_snapshot(data)
        used.refresh_from_db();self.assertEqual(used.status,'CANCELLED');self.assertEqual(used.used_at,stamp)
        self.assertEqual(validate_and_use_local_ticket(self.tickets[0].qr_token,self.guard)['result'],'CANCELLED')
        for row in data['tickets']: row['status']='VALID'
        data['generated_at']=timezone.now().isoformat();resign(data);import_snapshot(data)
        used.refresh_from_db();self.assertEqual(used.status,'CANCELLED')

    def test_omitted_and_cancelled_event_revoke(self):
        import_snapshot(self.payload)
        data=copy.deepcopy(self.payload);data['tickets']=[];data['generated_at']=timezone.now().isoformat();resign(data);import_snapshot(data)
        self.assertFalse(LocalAccessTicket.objects.exclude(status='CANCELLED').exists())

    def test_replayed_older_snapshot_rejected(self):
        import_snapshot(self.payload)
        data=copy.deepcopy(self.payload);data['event']='Changed';data['generated_at']=timezone.now().isoformat();resign(data);import_snapshot(data)
        with self.assertRaises(ValidationError): import_snapshot(self.payload)

    def test_local_scan_never_looks_up_source_and_logs_minimal(self):
        import_snapshot(self.payload)
        with patch('apps.events.access.validate_and_use_ticket', side_effect=AssertionError('source lookup')):
            self.client.post('/acceso/ingresar/',{'username':self.guard.username,'pin':'123456'})
            for result in ('VALID','USED'):
                response=self.client.post('/acceso/escanear/',json.dumps({'token':self.tickets[0].qr_token}),content_type='application/json')
                self.assertEqual(response.json()['result'],result)
            self.assertEqual(validate_and_use_local_ticket('unknown',self.guard)['result'],'INVALID')
        self.assertEqual(LocalAccessScan.objects.count(),3)
        self.assertNotIn(self.tickets[0].qr_token, str(list(LocalAccessScan.objects.values())))
        scan=LocalAccessScan.objects.first()
        with self.assertRaises(ValidationError): scan.delete()
        with self.assertRaises(ValidationError): scan.save()
        with self.assertRaises(ValidationError): LocalAccessScan.objects.update(result='VALID')
        with self.assertRaises(DatabaseError), transaction.atomic():
            with connections['default'].cursor() as cursor:
                cursor.execute('DELETE FROM localnode_localaccessscan WHERE id = %s',[scan.pk])

    def test_guard_permission_and_source_modes(self):
        import_snapshot(self.payload)
        with self.assertRaises(PermissionDenied): validate_and_use_local_ticket('unknown',self.manager)
        with override_settings(DEPLOYMENT_MODE='cloud'), self.assertRaises(ValidationError): import_snapshot(self.payload)
        with self.assertRaises(ValidationError): signed_snapshot(self.event)


@override_settings(DEPLOYMENT_MODE='local_node', ACCESS_SNAPSHOT_SIGNING_KEY=KEY)
class ConcurrentGuardTests(SnapshotFixtures, TransactionTestCase):
    def test_only_one_guard_admits_same_ticket(self):
        import_snapshot(self.payload)
        other=get_user_model().objects.create_user(username='second-guard',role='GUARDIA')
        other.user_permissions.set(self.guard.user_permissions.all())
        barrier=Barrier(2)
        def scan(pk):
            try:
                guard=get_user_model().objects.get(pk=pk)
                barrier.wait(timeout=10)
                return validate_and_use_local_ticket(self.tickets[0].qr_token,guard)['result']
            finally: connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor:
            self.assertCountEqual(executor.map(scan,[self.guard.pk,other.pk]),['VALID','USED'])
        self.assertEqual(LocalAccessScan.objects.count(),2)

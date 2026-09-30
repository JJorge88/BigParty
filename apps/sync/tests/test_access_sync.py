import hashlib
import uuid
from datetime import timedelta
from django.test import override_settings
from django.utils import timezone
from apps.events.tests.base import EventCase
from apps.events import services
from apps.sync.appliers import receive_event
from apps.sync.models import SyncConflict,CloudAccessScan,CloudSyncChange
from apps.sync.services import get_or_create_sync_identity
from .test_foundation import NODE,KEY


@override_settings(SYNC_ENABLED=True,DEPLOYMENT_MODE='cloud',SYNC_NODE_UUID=NODE,SYNC_SHARED_SECRET=KEY,ACCESS_SNAPSHOT_SIGNING_KEY=KEY,APP_VERSION='4C',SYNC_COMPATIBLE_APP_VERSIONS=['4C'])
class AccessSyncTests(EventCase):
    def scan_event(self,ticket):
        return {'event_uuid':str(uuid.uuid4()),'entity_uuid':str(uuid.uuid4()),'entity_type':'access.scan','operation':'UPSERT','entity_version':1,'schema_version':1,
            'payload':{'node_uuid':NODE,'event_uuid':str(get_or_create_sync_identity(self.event).entity_uuid),'snapshot_version':'snapshot-test',
                'token_digest':hashlib.sha256(ticket.qr_token.encode()).hexdigest(),'result':'VALID','scanned_at':timezone.now().isoformat(),
                'guard_uuid':str(uuid.uuid4()),'guard':{'name':'Local guard','role':'GUARDIA','active':True}}}

    def test_duplicate_admission_retains_both_times_and_cloud_used(self):
        ticket=self.confirm()[0]
        services.validate_and_use_ticket(ticket.qr_token,self.guard)
        event=self.scan_event(ticket)
        self.assertEqual(receive_event(event,NODE).status,'APPLIED')
        self.assertEqual(receive_event(event,NODE).status,'APPLIED')
        ticket.refresh_from_db();self.assertEqual(ticket.status,'USED')
        self.assertEqual(CloudAccessScan.objects.count(),1)
        conflict=SyncConflict.objects.get(conflict_type='DUPLICATE_ADMISSION')
        self.assertEqual(conflict.payload_summary['local_admission_at'],event['payload']['scanned_at'])
        self.assertTrue(conflict.payload_summary['first_known_at'])

    def test_ticket_raw_tokens_and_purchase_secrets_never_enter_feed(self):
        ticket=self.confirm()[0]
        import json
        raw=json.dumps(list(CloudSyncChange.objects.values_list('payload',flat=True)))
        self.assertNotIn(ticket.qr_token,raw)
        self.assertNotIn(ticket.purchase.secure_token,raw)
        self.assertNotIn(self.guard.pin_hash,raw)
        self.assertNotIn('proof_image',raw)
        self.assertIn(hashlib.sha256(ticket.qr_token.encode()).hexdigest(),raw)

    def test_reschedule_emits_a_new_automatic_snapshot(self):
        self.confirm()
        previous=CloudSyncChange.objects.filter(entity_type='events.access_snapshot').count()
        services.reschedule_event(self.event,self.manager,self.event.starts_at+timedelta(days=1),self.event.ends_at+timedelta(days=1),'Schedule change')
        self.assertEqual(CloudSyncChange.objects.filter(entity_type='events.access_snapshot').count(),previous+1)

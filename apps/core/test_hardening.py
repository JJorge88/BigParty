"""Recovery and security regression tests; real PostgreSQL dump drill is separate."""
import hashlib
import json
import logging
import os
import tempfile
import time
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import Mock, patch
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command, CommandError
from django.http import HttpResponse
from django.test import SimpleTestCase, TestCase, RequestFactory, override_settings
from apps.core.ops import backups, recovery, throttle
from apps.core.ops.files import atomic_json, digest_file, private_root, require_space
from apps.core.ops.middleware import OperationsSecurityMiddleware
from apps.core.ops.logging import SafeSupportFilter
from apps.events.tests.base import picture


class PrivateFiles(SimpleTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='bigparty-hardening-');self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name)
        override=override_settings(BACKUP_ROOT=str(self.base/'backups'),BACKUP_SECONDARY_ROOT=str(self.base/'secondary'),
            MEDIA_ROOT=self.base/'media',RESERVATION_PROOF_ROOT=self.base/'proofs',EVENT_PROOF_ROOT=self.base/'eventproofs',
            OPERATIONS_STATE_ROOT=self.base/'state',MIN_FREE_DISK_GB=0,RECOVERY_MODE=False,
            BACKUP_KEEP_HOURLY=0,BACKUP_KEEP_DAILY=1,BACKUP_KEEP_WEEKLY=0,BACKUP_KEEP_MONTHLY=0)
        override.enable();self.addCleanup(override.disable)
        (self.base/'media').mkdir();(self.base/'media/banner.png').write_bytes(picture().read())
        (self.base/'proofs').mkdir();(self.base/'proofs/proof.png').write_bytes(picture().read())

    def test_media_roundtrip_and_secondary(self):
        (self.base/'media/report.pdf').write_bytes(b'temporary')
        (self.base/'media/debug.log').write_text('excluded')
        manifest=backups.backup_media();info=backups.verify(manifest)
        self.assertEqual(set(info['entries']),{'public/banner.png','reservation-proofs/proof.png'})
        destination=self.base/'restored';backups.restore_media(manifest,destination)
        self.assertEqual(digest_file(destination/'public/banner.png'),digest_file(self.base/'media/banner.png'))
        self.assertEqual(backups.verify(backups.copy_secondary(manifest))['sha256'],info['sha256'])
        self.assertTrue(manifest.with_suffix('.verified.json').exists())

    def test_checksum_rejects_tampering(self):
        manifest=backups.backup_media();info=backups.read_manifest(manifest)
        (self.base/'backups/media'/info['file_name']).write_bytes(b'not the backup')
        with self.assertRaisesMessage(CommandError,'CHECKSUM'):backups.verify(manifest)

    def test_existing_restore_requires_both_flags(self):
        manifest=backups.backup_media();destination=self.base/'restored';destination.mkdir()
        (destination/'keep.txt').write_text('keep')
        for kwargs in ({},{'force':True},{'confirm':True}):
            with self.subTest(kwargs=kwargs),self.assertRaises(CommandError):backups.restore_media(manifest,destination,**kwargs)
        backups.restore_media(manifest,destination,force=True,confirm=True)
        self.assertEqual((destination/'keep.txt').read_text(),'keep')

    def test_zip_traversal_even_with_valid_checksum(self):
        manifest=backups.backup_media();info=backups.read_manifest(manifest)
        path=self.base/'backups/media'/info['file_name']
        for name in ('public/../../escape','public/C:/escape','public\\..\\escape','/public/escape'):
            with self.subTest(name=name):
                with zipfile.ZipFile(path,'w') as archive:archive.writestr(name,b'attack')
                info.update(file_size=path.stat().st_size,sha256=digest_file(path),entries={name:{'size':6,'sha256':hashlib.sha256(b'attack').hexdigest()}})
                atomic_json(manifest,info)
                with self.assertRaisesMessage(CommandError,'UNSAFE_ARCHIVE_PATH'):backups.restore_media(manifest,self.base/'output')
        self.assertFalse((self.base/'escape').exists())

    def test_symlink_media_and_restore_rejected(self):
        (self.base/'media/link').symlink_to(self.base/'proofs/proof.png')
        with self.assertRaises(CommandError):backups.backup_media()
        (self.base/'media/link').unlink();manifest=backups.backup_media()
        destination=self.base/'restored';destination.mkdir();(destination/'public').symlink_to(self.base/'media',target_is_directory=True)
        with self.assertRaises(CommandError):backups.restore_media(manifest,destination,True,True)

    def test_private_location_and_disk(self):
        for path in ('relative',settings.MEDIA_ROOT,settings.STATIC_ROOT,settings.BASE_DIR):
            with self.subTest(path=str(path)),self.assertRaises(CommandError):private_root(path)
        with patch('apps.core.ops.files.disk_free',return_value=1),self.assertRaisesMessage(CommandError,'DISK_SPACE_LOW'):
            require_space(self.base,2)

    def test_retention_preserves_latest_and_unknown(self):
        old=backups.backup_media();info=backups.read_manifest(old)
        info['created_at']=(datetime.now(timezone.utc)-timedelta(days=30)).isoformat();atomic_json(old,info)
        newest=backups.backup_media();unknown=old.parent/'unknown.json';unknown.write_text('bad')
        self.assertEqual(backups.retain(),[old.name]);self.assertTrue(old.exists())
        backups.retain(apply=True)
        self.assertFalse(old.exists());self.assertTrue(newest.exists());self.assertTrue(unknown.exists())

    def test_retention_stops_if_latest_corrupt(self):
        old=backups.backup_media();info=backups.read_manifest(old);info['created_at']='2020-01-01T00:00:00+00:00';atomic_json(old,info)
        latest=backups.backup_media();info=backups.read_manifest(latest)
        (self.base/'backups/media'/info['file_name']).write_bytes(b'corrupt')
        with self.assertRaises(CommandError):backups.retain(apply=True)
        self.assertTrue(old.exists())

    def test_pgpass_not_command_or_password_environment(self):
        config={'NAME':'db','USER':'user','PASSWORD':'private:password\\value','HOST':'127.0.0.1','PORT':'5432'}
        with patch.object(backups,'db_parameters',return_value={key:config[value] for key,value in [('dbname','NAME'),('user','USER'),('password','PASSWORD'),('host','HOST'),('port','PORT')]}):
            with backups.pg_environment() as env:
                path=Path(env['PGPASSFILE']);self.assertTrue(path.exists())
                self.assertNotIn('PGPASSWORD',env);self.assertNotIn(config['PASSWORD'],str(env))
                if os.name!='nt':self.assertEqual(path.stat().st_mode&0o777,0o600)
            self.assertFalse(path.exists())

    def test_restore_database_guard_precedes_tools(self):
        with patch.object(backups,'run_tool') as tool,patch.object(backups.psycopg,'connect') as connection:
            for target,confirm in ((settings.DATABASES['default']['NAME'],True),('postgres',True),('target;DROP',True),('new_db',False)):
                with self.subTest(target=target),self.assertRaises(CommandError):backups.restore_database('absent',target,confirm)
            tool.assert_not_called();connection.assert_not_called()

    def test_restore_existing_db_never_drops(self):
        with patch.object(backups,'verify',return_value={'kind':'database','file_name':'safe.dump'}),patch.object(backups.psycopg,'connect') as connect,patch.object(backups,'run_tool') as tool:
            connect.return_value.__enter__.return_value.execute.return_value.fetchone.return_value=(1,)
            with self.assertRaisesMessage(CommandError,'TARGET_ALREADY_EXISTS'):backups.restore_database('manifest.json','test_new_target',True)
            tool.assert_not_called()
            self.assertTrue(recovery.status()['active'])

    def test_recovery_persistent_and_corruption_fails_closed(self):
        recovery.enter('test');self.assertTrue(recovery.status()['active'])
        with self.assertRaises(PermissionDenied):recovery.require_operational()
        recovery.marker().write_text('not json');self.assertTrue(recovery.status()['active'])

    def test_recovery_exit_needs_review_and_good_diagnostics(self):
        recovery.enter()
        with self.assertRaises(CommandError):recovery.complete()
        with patch('apps.core.ops.integrity.restored_report',return_value={'errors':[{'code':'bad'}]}),self.assertRaises(CommandError):recovery.complete(True,True)
        with patch('apps.core.ops.integrity.restored_report',return_value={'errors':[]}):recovery.complete(True,True)
        self.assertFalse(recovery.status()['active'])

    def test_recovery_blocks_worker_and_mutating_commands(self):
        recovery.enter()
        for name in ('sync_worker','bootstrap_sync','retry_failed_sync','run_maintenance','init_local_node','prepare_local_node'):
            with self.subTest(name=name),self.assertRaises(CommandError):call_command(name,stdout=StringIO())
        middleware=OperationsSecurityMiddleware(lambda request:HttpResponse('ok'))
        self.assertEqual(middleware(RequestFactory().post('/operacion/')).status_code,503)
        self.assertEqual(middleware(RequestFactory().get('/gerencia/configuracion/')).status_code,200)
        self.assertEqual(middleware(RequestFactory().get('/healthz/')).status_code,200)

    @override_settings(RATE_LIMIT_ENABLED=True,RATE_LIMIT_LOGIN=2,RATE_LIMIT_WINDOW_SECONDS=300)
    def test_rate_limit_shared_ip_and_window(self):
        middleware=OperationsSecurityMiddleware(lambda request:HttpResponse('ok'))
        factory=RequestFactory()
        for _ in range(2):self.assertEqual(middleware(factory.post('/gerencia/acceso/',REMOTE_ADDR='10.0.0.1')).status_code,200)
        response=middleware(factory.post('/gerencia/acceso/',REMOTE_ADDR='10.0.0.1',HTTP_X_FORWARDED_FOR='random'))
        self.assertEqual(response.status_code,429);self.assertIn('Retry-After',response)
        self.assertEqual(middleware(factory.post('/gerencia/acceso/',REMOTE_ADDR='10.0.0.2')).status_code,200)
        with patch('apps.core.ops.throttle.time.time',return_value=time.time()+301):
            self.assertEqual(middleware(factory.post('/gerencia/acceso/',REMOTE_ADDR='10.0.0.1')).status_code,200)
        for path in (self.base/'state/rate-limits').glob('*.json'):self.assertNotIn('10.0.0.',path.read_text())

    def test_all_abuse_routes_scoped(self):
        for path in ('/gerencia/acceso/','/operacion/acceso/','/caja/acceso/','/acceso/ingresar/','/reservas/datos/','/eventos/night/comprar/','/reservas/r/token/','/eventos/compra/token/','/api/sync/v1/push/'):
            self.assertIsNotNone(throttle.limit_for(path),path)
        self.assertIsNone(throttle.limit_for('/operacion/mesas/'))

    @override_settings(SYNC_ENABLED=True,DEPLOYMENT_MODE='local_node')
    def test_maintenance_local_authority_and_cleanup(self):
        folder=self.base/'state/rate-limits';folder.mkdir(parents=True)
        old=folder/('a'*64+'.json');old.write_text('{}');os.utime(old,(0,0));unrelated=folder/'keep.json';unrelated.write_text('{}')
        with patch('apps.core.management.commands.run_maintenance.call_command') as command:
            call_command('run_maintenance',stdout=StringIO());call_command('run_maintenance',stdout=StringIO())
            self.assertEqual([c.args[0] for c in command.call_args_list],['recover_stale_print_jobs']*2)
        self.assertFalse(old.exists());self.assertTrue(unrelated.exists())

    @override_settings(SYNC_ENABLED=True,DEPLOYMENT_MODE='cloud')
    def test_maintenance_cloud_authority(self):
        with patch('apps.core.management.commands.run_maintenance.call_command') as command:
            call_command('run_maintenance',stdout=StringIO())
            self.assertEqual([c.args[0] for c in command.call_args_list],['expire_reservation_holds','expire_reservation_payments','expire_event_purchases'])


class SecurityCases(SimpleTestCase):
    def test_upload_names_actual_image_type(self):
        from apps.events.services import validate_image
        from apps.reservations.services import validate_proof
        from apps.events.models import image_path
        from apps.reservations.models import proof_path
        for name in ('../../evil.php','imagen.ñ.png.exe','..\\evil.jpg','foto.svg'):
            for validator,path in ((validate_image,image_path),(validate_proof,proof_path)):
                with self.subTest(name=name,validator=validator.__name__):
                    file=picture(name);validator(file);stored=path(None,file.name)
                    self.assertTrue(stored.endswith('.png'));self.assertNotIn('..',stored);self.assertNotIn('evil',stored);self.assertNotIn('ñ',stored)
        for validator in (validate_image,validate_proof):
            with self.assertRaises(ValidationError):validator(SimpleUploadedFile('fake.png',b'<script>bad</script>',content_type='image/png'))

    @override_settings(SECURITY_HEADERS_ENABLED=True,RECOVERY_MODE=False,RATE_LIMIT_ENABLED=False)
    def test_headers_camera_self_and_request_reference(self):
        response=OperationsSecurityMiddleware(lambda request:HttpResponse('ok'))(RequestFactory().get('/'))
        self.assertIn("script-src 'self'",response['Content-Security-Policy'])
        self.assertIn("worker-src 'self' blob:",response['Content-Security-Policy'])
        self.assertEqual(response['Permissions-Policy'],'camera=(self), microphone=(), geolocation=()')
        self.assertRegex(response['X-Request-ID'],r'^[a-f0-9]{12}$')

    def test_error_handlers_do_not_expose_exception(self):
        from apps.core.ops import error_views
        request=RequestFactory().get('/');request.support_reference='012345abcdef'
        for code,view in ((400,error_views.bad_request),(403,error_views.forbidden),(404,error_views.not_found),(500,error_views.server_error)):
            response=view(request) if code==500 else view(request,Exception('sensitive-database-password'))
            self.assertEqual(response.status_code,code);self.assertIn(b'BIG PARTY',response.content)
            self.assertNotIn(b'sensitive-database-password',response.content)

    def test_safe_support_logs_strip_secrets_and_exception(self):
        record=logging.LogRecord('test',40,'',0,'password=%s',('sensitive',),(Exception,Exception('private'),None))
        SafeSupportFilter().filter(record)
        self.assertNotIn('sensitive',record.getMessage());self.assertIsNone(record.exc_info)

    def test_previous_sync_key_bounded_and_response_uses_same_key(self):
        from apps.sync.security import authenticate,signature,response_signature
        from apps.sync.exceptions import SyncError
        node=str(uuid.uuid4());current='current-test-key-'*4;previous='previous-test-key-'*4
        settings_override=dict(SYNC_ENABLED=True,DEPLOYMENT_MODE='cloud',SYNC_SHARED_SECRET=current,SYNC_SHARED_SECRET_PREVIOUS=previous,SYNC_NODE_UUID=node,SYNC_SECRET_PREVIOUS_UNTIL=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
        with override_settings(**settings_override):
            stamp=str(int(time.time()));signed=signature('POST','/api/sync/v1/push/',stamp,b'{}',node,previous)
            request=RequestFactory().post('/api/sync/v1/push/',data=b'{}',content_type='application/json',secure=True,HTTP_X_BP_NODE=node,HTTP_X_BP_TIMESTAMP=stamp,HTTP_X_BP_SIGNATURE=signed)
            self.assertEqual(authenticate(request,b'{}'),node);self.assertEqual(request.sync_signing_key,previous)
            self.assertNotEqual(response_signature(signed,b'ok',previous),response_signature(signed,b'ok',current))
            with override_settings(SYNC_SECRET_PREVIOUS_UNTIL=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()),self.assertRaises(SyncError):authenticate(request,b'{}')

    def test_repo_scan_reports_location_not_value(self):
        from apps.core.ops.repo_safety import scan
        with tempfile.TemporaryDirectory() as directory,override_settings(BASE_DIR=Path(directory)):
            secret='gh'+'p_'+'a'*40;Path(directory,'example.txt').write_text(secret)
            with patch('apps.core.ops.repo_safety.subprocess.run',return_value=Mock(stdout=b'example.txt\0')):findings=scan()
            self.assertEqual(findings,[('example.txt','SECRET_PATTERN')]);self.assertNotIn(secret,str(findings))


class IntegrityTests(TestCase):
    def test_empty_database_integrity_is_readonly(self):
        from apps.core.ops.integrity import integrity
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connection) as queries:report=integrity()
        self.assertFalse(report['errors'])
        self.assertTrue(all(not q['sql'].lstrip().upper().startswith(('INSERT','UPDATE','DELETE')) for q in queries))

    @override_settings(DEPLOYMENT_MODE='local_node')
    def test_invalid_cursor_detected_without_reset(self):
        from apps.core.ops.integrity import integrity
        from apps.sync.models import SyncCursor
        cursor=SyncCursor.objects.create(source='cloud',last_sequence=99)
        self.assertIn('INVALID_CURSOR',[r['code'] for r in integrity()['errors']])
        cursor.refresh_from_db();self.assertEqual(cursor.last_sequence,99)


class BackupPageTests(TestCase):
    def test_status_readonly_private_and_permission_protected(self):
        from django.contrib.auth import get_user_model
        url='/gerencia/configuracion/backups/'
        self.assertEqual(self.client.get(url).status_code,302)
        user=get_user_model().objects.create_superuser(username='backup-manager',password='Manager-test-942!',role='GERENTE')
        self.client.post('/gerencia/acceso/',{'username':user.username,'password':'Manager-test-942!'})
        with tempfile.TemporaryDirectory(prefix='private-backup-location-') as directory,override_settings(BACKUP_ROOT=directory):
            logs=Path(directory,'logs');logs.mkdir();atomic_json(logs/'last-database.json',{'status':'FAILED'})
            response=self.client.get(url)
            self.assertContains(response,'Backups y recuperación');self.assertContains(response,'El último intento falló')
            self.assertNotContains(response,directory)
            self.assertEqual(self.client.post(url).status_code,405)
            self.assertEqual(self.client.get('/healthz/').status_code,200)
        user.is_superuser=False;user.save(update_fields=['is_superuser'])
        self.assertEqual(self.client.get(url).status_code,403)


from apps.payments.tests.base import PaymentsTestCase
class BusinessIntegrityTests(PaymentsTestCase):
    def test_closed_order_with_unpaid_balance_detected_without_repair(self):
        from apps.core.ops.integrity import integrity
        from apps.orders.models import TableOrder
        order,_,_=self.consumption()
        TableOrder.objects.filter(pk=order.pk).update(status='CLOSED')
        report=integrity()
        self.assertIn('CLOSED_ORDER_WITH_BALANCE',[row['code'] for row in report['errors']])
        order.refresh_from_db();self.assertEqual(order.status,'CLOSED')

    def test_domain_service_rejects_direct_mutation_in_recovery(self):
        from apps.orders.services import open_table_order
        with override_settings(RECOVERY_MODE=True),self.assertRaises(PermissionDenied):open_table_order(self.table,self.user)

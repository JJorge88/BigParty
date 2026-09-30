import json
import logging
import os
from pathlib import Path
import subprocess
import sys
from io import StringIO
from tempfile import TemporaryDirectory
from unittest.mock import patch, Mock
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command, CommandError
from django.db import DatabaseError, IntegrityError, transaction
from django.test import TestCase, SimpleTestCase, override_settings
from apps.localnode.models import LocalNodeIdentity
from apps.localnode.logging import SafeEventFilter
from apps.localnode.runtime import wait_for_database


@override_settings(DEPLOYMENT_MODE='local_node',DEBUG=False)
class NodeTests(TestCase):
    def test_identity_idempotent_and_singleton(self):
        call_command('init_local_node',stdout=StringIO())
        original=LocalNodeIdentity.objects.get()
        call_command('init_local_node',name='Do not replace',stdout=StringIO())
        node=LocalNodeIdentity.objects.get()
        self.assertEqual((original.node_uuid,original.name),(node.node_uuid,node.name))
        with self.assertRaises(IntegrityError),transaction.atomic(): LocalNodeIdentity.objects.create(pk=2)

    def test_prepare_twice_no_users_or_overwrites(self):
        call_command('prepare_local_node',stdout=StringIO()); first=LocalNodeIdentity.objects.get().node_uuid
        call_command('prepare_local_node',stdout=StringIO())
        self.assertEqual(first,LocalNodeIdentity.objects.get().node_uuid)
        self.assertFalse(get_user_model().objects.exists())

    def test_health_readiness_and_db_failure(self):
        self.assertEqual(self.client.get('/healthz/').json(),{'status':'ok'})
        self.assertEqual(self.client.get('/readyz/').status_code,200)
        with patch('apps.localnode.diagnostics.connection.cursor',side_effect=DatabaseError('SECRET')):
            response=self.client.get('/readyz/')
        self.assertEqual(response.status_code,503);self.assertNotIn('SECRET',response.content.decode())

    def test_commercial_routes_blocked_for_get_and_post(self):
        for path in ['/','/eventos/','/eventos/example/comprar/','/reservas/','/reservas/pago/','/entrada/token/','/dev/','/dev/scan/']:
            for method in (self.client.get,self.client.post):
                with self.subTest(path=path):
                    response=method(path)
                    self.assertEqual(response.status_code,404)
                    self.assertNotIn('Location',response)

    def test_internal_routes_available(self):
        for path in ['/operacion/','/caja/','/gerencia/','/acceso/','/impresoras/','/admin/']:
            self.assertIn(self.client.get(path).status_code,[200,302])

    def test_status_requires_management_permission_no_secrets(self):
        url='/gerencia/configuracion/nodo-local/'
        self.assertEqual(self.client.get(url).status_code,302)
        user=get_user_model().objects.create_user(username='manager',password='Test-only-32!',role='GERENTE')
        self.client.post('/gerencia/acceso/',{'username':user.username,'password':'Test-only-32!'})
        self.assertEqual(self.client.get(url).status_code,403)
        user.user_permissions.add(Permission.objects.get(codename='view_configuration',content_type__app_label='core'))
        call_command('init_local_node',stdout=StringIO())
        response=self.client.get(url)
        self.assertContains(response,'Nodo local')
        for secret in [settings.SECRET_KEY,settings.DATABASES['default']['PASSWORD']]:
            if secret:self.assertNotIn(secret,response.content.decode())
        with override_settings(DEPLOYMENT_MODE='cloud'): self.assertEqual(self.client.get(url).status_code,404)

    def test_check_is_read_only_and_exit_code(self):
        with self.assertRaises(CommandError): call_command('check_local_node',stdout=StringIO())
        self.assertFalse(LocalNodeIdentity.objects.exists())
        with TemporaryDirectory() as directory:
            assets=['css/operations/base.css','js/events/scanner.js','vendor/qr-scanner/qr-scanner.min.js','vendor/qr-scanner/qr-scanner-worker.min.js']
            for asset in assets:
                path=Path(directory,asset);path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture')
            Path(directory,'staticfiles.json').write_text(json.dumps({'paths':{asset:asset for asset in assets}}))
            call_command('init_local_node',stdout=StringIO())
            with override_settings(STATIC_ROOT=directory,PRINTER_BACKEND='network',ACCESS_SNAPSHOT_SIGNING_KEY='x'*32,CSRF_TRUSTED_ORIGINS=['https://pos.example.lan']):
                call_command('check_local_node',stdout=StringIO())
                Path(directory,assets[-1]).unlink()
                with self.assertRaises(CommandError): call_command('check_local_node',stdout=StringIO())


class RuntimeTests(SimpleTestCase):
    def profile(self,module,**extra):
        with TemporaryDirectory() as directory:
            env={**os.environ,'BIGPARTY_ENV_FILE':str(Path(directory)/'absent'), 'DJANGO_SETTINGS_MODULE':module,
                 'DJANGO_SECRET_KEY':'test-only-key-'+'a'*50,'DB_NAME':'test','DB_USER':'test','DB_PASSWORD':'test',
                 'DB_HOST':'127.0.0.1','DEPLOYMENT_MODE':'local_node','LOCAL_NODE_HOSTNAME':'pos.example.lan',
                 'ALLOWED_HOSTS':'pos.example.lan,localhost','CSRF_TRUSTED_ORIGINS':'https://pos.example.lan',
                 'LOCAL_MEDIA_ROOT':directory+'/media','LOCAL_PRIVATE_ROOT':directory+'/private','LOCAL_LOG_ROOT':directory+'/logs',
                 'ACCESS_SNAPSHOT_SIGNING_KEY':'test-only-'+'b'*32,'PRINTER_BACKEND':'network',**extra}
            return subprocess.run([sys.executable,'-c',"import django; django.setup(); from django.conf import settings as s; import json; print(json.dumps({'mode':s.DEPLOYMENT_MODE,'debug':s.DEBUG,'secure':s.SESSION_COOKIE_SECURE,'domain':s.SESSION_COOKIE_DOMAIN,'proxy':s.SECURE_PROXY_SSL_HEADER}))"],env=env,capture_output=True,text=True,timeout=15)

    def test_profiles_and_debug_independent(self):
        for module,mode in [('dev','development'),('prod','cloud'),('local_node','local_node')]:
            result=self.profile('config.settings.'+module,DEPLOYMENT_MODE=mode,DJANGO_DEBUG='True')
            self.assertEqual(result.returncode,0,result.stderr)
            data=json.loads(result.stdout);self.assertEqual(data['mode'],mode)
            self.assertEqual(data['debug'],mode=='development')
            if mode=='local_node':self.assertTrue(data['secure']);self.assertIsNone(data['domain']);self.assertIsNone(data['proxy'])

    def test_unsafe_local_configuration_rejected(self):
        for extra in [dict(ALLOWED_HOSTS='*'),dict(CSRF_TRUSTED_ORIGINS='https://*.example.lan'),dict(DB_HOST='db.example.com'),dict(ACCESS_SNAPSHOT_SIGNING_KEY='short'),dict(PRINTER_BACKEND='debug'),dict(LOCAL_NODE_BIND_HOST='0.0.0.0'),dict(DEPLOYMENT_MODE='invalid')]:
            with self.subTest(extra=extra):self.assertNotEqual(self.profile('config.settings.local_node',**extra).returncode,0)

    def test_db_wait_bounded_and_recovers(self):
        connection=Mock();connection.cursor.side_effect=DatabaseError('private')
        times=iter([0,0,2,4]); sleeps=[]
        self.assertFalse(wait_for_database(connection,3,clock=lambda:next(times),sleep=sleeps.append))
        self.assertEqual(sleeps,[2,1])
        connection=Mock();connection.cursor.return_value.__enter__=Mock();connection.cursor.return_value.__exit__=Mock()
        self.assertTrue(wait_for_database(connection,0))

    def test_rotating_log_filter_removes_sensitive_material(self):
        record=logging.LogRecord('django.request',logging.ERROR,'',0,'PIN 123456 /entrada/secret password',(),None)
        SafeEventFilter().filter(record)
        self.assertNotIn('secret',record.getMessage());self.assertNotIn('123456',record.getMessage())

    def test_local_scanner_assets_license_and_no_cdn(self):
        scanner=Path(settings.BASE_DIR,'static/js/events/scanner.js').read_text()
        self.assertNotIn('https://',scanner)
        self.assertTrue(Path(settings.BASE_DIR,'static/vendor/qr-scanner/qr-scanner.min.js').is_file())
        self.assertTrue(Path(settings.BASE_DIR,'static/vendor/qr-scanner/LICENSE').is_file())
        for path in (Path(settings.BASE_DIR)/'templates/operations').rglob('*.html'):
            text=path.read_text()
            self.assertNotRegex(text,r'(?:src|href)=[\"\']https?://(?:fonts\.|cdn\.|unpkg\.|cdnjs\.)')

    def test_windows_scripts_structure_only(self):
        root=Path(settings.BASE_DIR)/'deploy/windows'
        common=(root/'local-node-common.ps1').read_text()
        self.assertIn('& $PythonExe @Arguments',common)
        self.assertIn('$LASTEXITCODE',common)
        for name in ['install','start','check']:
            text=(root/f'{name}-local-node.ps1').read_text()
            self.assertIn('Join-Path $PSScriptRoot',text)
            self.assertIn('Set-Location -LiteralPath $ProjectRoot',text)
            self.assertIn('exit 1',text)
            self.assertNotIn('runserver',text)
            self.assertNotIn('Invoke-Expression',text)

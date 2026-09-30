import json
import os
import secrets
import subprocess
import sys
import tempfile
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth.models import Permission
from django.core.management import call_command, CommandError
from django.test import TestCase, SimpleTestCase, override_settings
from apps.accounts.models import User
from apps.accounts.permissions import PRESETS
from apps.audit.models import AuditLog
from apps.cash.models import BusinessDay, CashSession, CashRegister
from apps.catalog.models import Product, Category, ModifierGroup, ModifierOption, ComboComponent, ProductAreaPrice
from apps.catalog.services import get_product_price
from apps.inventory.models import InventoryMovement
from apps.operations.models import OperationalDevice
from apps.operations.queries import get_operational_map
from apps.orders.models import TableOrder
from apps.venues.models import Area, Zone
from apps.tables.models import VenueTable
from apps.core.management.commands.seed_pilot_demo import USERS, PRODUCTS


@override_settings(DEBUG=True, DEPLOYMENT_MODE='development', SYNC_ENABLED=False, PRINTER_BACKEND='debug', RECOVERY_MODE=False,
                   PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class PilotTests(TestCase):
    def setUp(self):
        self.name_patch=patch('apps.core.management.commands.seed_pilot_demo.database_name',return_value='bigparty_pilot')
        self.name_patch.start();self.addCleanup(self.name_patch.stop)
        self.pin=str(secrets.randbelow(900000)+100000)
        self.password=secrets.token_urlsafe(32)

    def seed(self, **options):
        output=StringIO();call_command('seed_pilot_demo',stdout=output,**options);return output.getvalue()

    def populated(self):
        return self.seed(pin=self.pin,manager_password=self.password)

    def test_debug_false_rejected_before_writes(self):
        with override_settings(DEBUG=False),self.assertRaisesMessage(CommandError,'DEBUG=True'):self.seed()
        self.assertFalse(User.objects.exists());self.assertFalse(Area.objects.exists())

    def test_wrong_database_rejected(self):
        with patch('apps.core.management.commands.seed_pilot_demo.database_name',return_value='bigparty'),self.assertRaisesMessage(CommandError,'bigparty_pilot'):self.seed()
        self.assertFalse(User.objects.exists())

    def test_remote_database_rejected(self):
        from django.db import connection
        with patch.dict(connection.settings_dict, {'HOST':'cloud.invalid'}),self.assertRaisesMessage(CommandError,'loopback'):
            self.seed()
        self.assertFalse(User.objects.exists())

    def test_cloud_sync_network_and_recovery_rejected(self):
        for extra in ({'DEPLOYMENT_MODE':'cloud'},{'DEPLOYMENT_MODE':'local_node'},{'SYNC_ENABLED':True},{'PRINTER_BACKEND':'network'},{'RECOVERY_MODE':True}):
            with self.subTest(extra=extra),override_settings(**extra),self.assertRaises(CommandError):self.seed()
        self.assertFalse(Area.objects.exists())

    def test_credentials_optional_never_invented(self):
        output=self.seed()
        self.assertIn('--pin',output);self.assertIn('--manager-password',output)
        for user in User.objects.all():
            self.assertFalse(user.pin_hash);self.assertFalse(user.has_usable_password());self.assertTrue(user.is_active)

    def test_pin_hash_password_and_user_roles(self):
        output=self.populated()
        self.assertNotIn(self.pin,output);self.assertNotIn(self.password,output)
        self.assertEqual(User.objects.count(),5)
        for username,first,last,role in USERS:
            user=User.objects.get(username=username)
            self.assertEqual((user.first_name,user.last_name,user.role),(first,last,role))
            self.assertTrue(user.check_pin(self.pin));self.assertNotEqual(user.pin_hash,self.pin)
            self.assertFalse(user.is_superuser)
            self.assertEqual(user.is_staff,role=='GERENTE')
        self.assertTrue(User.objects.get(username='gerente_demo').check_password(self.password))
        self.assertNotIn(self.password,str(list(AuditLog.objects.values('data'))))

    def test_invalid_credentials_leave_no_partial_seed(self):
        for options in ({'pin':'bad'},{'pin':'1'},{'pin':'1234567'},{'manager_password':'short'}):
            with self.subTest(option=list(options)),self.assertRaises(CommandError):self.seed(**options)
        self.assertFalse(Area.objects.exists())

    def test_idempotence_preserves_hashes_counts_and_binding(self):
        self.populated()
        models=(User,Area,Zone,VenueTable,Product,ModifierGroup,ModifierOption,ComboComponent,ProductAreaPrice,AuditLog,InventoryMovement,OperationalDevice,CashRegister)
        counts=[m.objects.count() for m in models]
        credentials=list(User.objects.values_list('password','pin_hash'))
        binding=OperationalDevice.objects.get().binding_version
        self.populated()
        self.assertEqual([m.objects.count() for m in models],counts)
        self.assertEqual(credentials,list(User.objects.values_list('password','pin_hash')))
        self.assertEqual(binding,OperationalDevice.objects.get().binding_version)

    def test_rerun_preserves_manual_stock_prices_names_and_status(self):
        self.populated()
        product=Product.objects.get(slug='pilot-gallo');product.stock_quantity=91;product.base_price=29;product.name='Nombre ajustado';product.save()
        table=VenueTable.objects.get(area__slug='discoteca',name='Mesa 01');table.name='Mesa personalizada';table.is_active=False;table.save()
        self.seed()
        product.refresh_from_db();table.refresh_from_db()
        self.assertEqual((product.stock_quantity,product.base_price,product.name),(91,Decimal('29'),'Nombre ajustado'))
        self.assertFalse(table.is_active);self.assertEqual(VenueTable.objects.count(),19)

    def test_non_demo_username_collision_is_not_claimed(self):
        user=User.objects.create_user(username='carlos_demo',first_name='Ajeno')
        original=user.password
        with self.assertRaisesMessage(CommandError,'ajeno'):self.populated()
        user.refresh_from_db();self.assertEqual(user.first_name,'Ajeno');self.assertEqual(user.password,original)
        self.assertFalse(Area.objects.exists())

    def test_unrelated_objects_and_defaults_are_preserved(self):
        area=Area.objects.create(name='Sport Bar',slug='sport-bar',description='Conservar')
        category=Category.objects.create(name='Cervezas',slug='cervezas',sort_order=99)
        user=User.objects.create_user(username='other')
        self.seed();area.refresh_from_db();category.refresh_from_db()
        self.assertEqual(area.description,'Conservar');self.assertEqual(category.sort_order,99)
        self.assertFalse(user.user_permissions.exists())
        self.assertEqual(Area.objects.count(),3)

    def test_products_stock_routes_premium_and_combo(self):
        self.populated();self.assertEqual(Product.objects.count(),12)
        premium=Area.objects.get(slug='premium')
        overrides={'Gallo':30,'Corona':35,'Whisky':50}
        for name,category,price,stock,route in PRODUCTS:
            product=Product.objects.get(name=name)
            self.assertEqual((product.base_price,product.stock_quantity,product.preparation_route),(Decimal(price),stock or 0,route))
            self.assertEqual(product.track_inventory,stock is not None)
            self.assertEqual(get_product_price(product,premium),Decimal(overrides.get(name,price)))
        self.assertFalse(Product.objects.get(name='Hielo').visible_in_pos)
        combo=Product.objects.get(name='Combo BIG');self.assertFalse(combo.track_inventory);self.assertTrue(combo.is_combo)
        self.assertEqual(set(combo.combo_components.values_list('component__name','quantity')), {('Hamburguesa',1),('Papas fritas',1),('Gallo',1)})
        self.assertEqual(InventoryMovement.objects.count(),9)

    def test_modifiers(self):
        self.populated()
        self.assertEqual(ModifierGroup.objects.count(),4);self.assertEqual(ModifierOption.objects.count(),9)
        group=ModifierGroup.objects.get(product__name='Hamburguesa',name='Extras')
        self.assertEqual((group.selection_type,group.max_selections),('MULTIPLE',2))
        self.assertEqual(set(group.options.values_list('name','price_delta')),{('Extra queso',Decimal('10')),('Extra tocino',Decimal('15'))})
        for group in ModifierGroup.objects.filter(name='Preparación'):
            self.assertEqual((group.selection_type,group.max_selections),('SINGLE',1))

    def test_tables_layout_and_initial_free_state(self):
        self.populated();self.assertEqual(Zone.objects.count(),7);self.assertEqual(VenueTable.objects.count(),19)
        for slug,count in (('discoteca',10),('sport-bar',5),('premium',4)):
            data=get_operational_map(Area.objects.get(slug=slug))
            self.assertEqual(data['table_count'],count);self.assertEqual(data['available_count'],count)
            for group in data['groups']:
                self.assertTrue(group['has_layout'])
                for table in group['tables']:
                    layout=table['layout'];self.assertLessEqual(layout['x']+layout['width'],100);self.assertLessEqual(layout['y']+layout['height'],100)
                    self.assertGreaterEqual(layout['height']*5.8,145)
        self.assertFalse(VenueTable.objects.filter(reservable_web=False).exists())
        self.assertEqual(set(VenueTable.objects.filter(name__startswith='VIP ').values_list('capacity',flat=True)),{6})

    def test_permissions_least_privilege_and_manager_not_superuser(self):
        self.populated()
        for username,_,_,role in USERS:
            user=User.objects.get(username=username)
            if role!='GERENTE':self.assertEqual(user.get_all_permissions(),PRESETS[role] | ({'orders.add_order_line','orders.send_order'} if role=='CAJERO' else set()))
            else:
                for code in ('cash.open_business_day','core.view_reports','core.export_reports_pdf','accounts.manage_user_permissions','audit.view_audit_log','operations.configure_operational_device','cash.configure_cash_register_device','inventory.receive_inventory','events.create_event','reservations.create_reservation'):
                    self.assertTrue(user.has_perm(code),code)
                self.assertFalse(user.has_perm('audit.delete_auditlog'));self.assertFalse(user.is_superuser)

    def test_device_and_defaults_no_day_order_or_node(self):
        from apps.localnode.models import LocalNodeIdentity
        from apps.sync.models import SyncOutboxEvent
        from apps.events.models import Event,EventTicket
        from apps.printing.models import Printer
        self.populated();device=OperationalDevice.objects.get()
        self.assertEqual((device.name,device.code,device.area.slug,device.device_type),('Tablet Discoteca Demo','TAB-DISCO-DEMO','discoteca','WAITER_TABLET'))
        self.assertTrue(device.is_active);self.assertEqual(CashRegister.objects.count(),3);self.assertEqual(Printer.objects.count(),4)
        self.assertFalse(Printer.objects.exclude(host='').exists())
        for model in (BusinessDay,CashSession,TableOrder,LocalNodeIdentity,SyncOutboxEvent,Event,EventTicket):self.assertFalse(model.objects.exists(),model.__name__)

    def test_cashier_can_create_quick_sale_and_send_products(self):
        from apps.cash.services import open_business_day,open_cash_session
        from apps.operations.cash_ordering import create_quick_sale
        from apps.orders.services import add_product_to_order
        from apps.operations.models import CashAccessSession
        self.populated()
        manager=User.objects.get(username='gerente_demo');cashier=User.objects.get(username='luis_caja_demo')
        day=open_business_day(manager);register=CashRegister.objects.get(code='DISCO')
        session=open_cash_session(register,cashier,0,cashier)
        access=CashAccessSession.objects.create(token_hash=secrets.token_hex(32),binding_hash=secrets.token_hex(32),auth_hash=secrets.token_hex(32),register=register,user=cashier,business_day=day,cash_session=session)
        context={'user':cashier,'day':day,'register':register,'session':session,'access':access}
        order=create_quick_sale(context)
        product=Product.objects.get(name='Gallo')
        add_product_to_order(order,product,1,cashier)
        # Quick sale fulfillment is deliberately controlled by the existing payment flow.
        self.assertTrue(order.lines.exists());self.assertTrue(cashier.has_perm('orders.send_order'))
        self.assertFalse(cashier.has_perm('cash.approve_cash_withdrawal'))

    def test_existing_flows_can_login_and_bind_with_demo_permissions(self):
        self.populated();manager=User.objects.get(username='gerente_demo')
        response=self.client.post('/gerencia/acceso/',{'username':manager.username,'password':self.password})
        self.assertEqual(response.status_code,302);self.assertEqual(self.client.get('/gerencia/').status_code,200)
        self.client.force_login(manager)
        self.assertEqual(self.client.post('/dispositivo/configurar/',{'device':OperationalDevice.objects.get().pk}).status_code,302)
        waiter=User.objects.get(username='carlos_demo')
        self.assertEqual(self.client.post('/operacion/acceso/',{'user_id':waiter.pk,'pin':self.pin},HTTP_ACCEPT='application/json').status_code,200)
        self.assertEqual(self.client.get('/operacion/mesas/').status_code,200)
        self.assertEqual(self.client.post('/caja/configurar/',{'register':CashRegister.objects.get(code='DISCO').pk}).status_code,302)
        cashier=User.objects.get(username='luis_caja_demo')
        self.assertEqual(self.client.post('/caja/acceso/',{'user_id':cashier.pk,'pin':self.pin},HTTP_ACCEPT='application/json').status_code,200)


class LanSettingsTests(SimpleTestCase):
    def profile(self, host):
        with tempfile.TemporaryDirectory() as directory:
            env={**os.environ,'BIGPARTY_ENV_FILE':str(Path(directory)/'absent'), 'DJANGO_SECRET_KEY':secrets.token_urlsafe(48),
                 'DJANGO_SETTINGS_MODULE':'config.settings.dev','DEPLOYMENT_MODE':'development','DJANGO_DEBUG':'true',
                 'DB_NAME':'bigparty_pilot','DB_USER':'unused','DB_PASSWORD':'unused','SYNC_ENABLED':'false',
                 'ALLOWED_HOSTS':'localhost,127.0.0.1','CSRF_TRUSTED_ORIGINS':'http://localhost:8000','DEV_LAN_HOST':host}
            return subprocess.run([sys.executable,'-c',"from config.settings import dev as s; import json; print(json.dumps([s.ALLOWED_HOSTS,s.CSRF_TRUSTED_ORIGINS]))"],env=env,capture_output=True,text=True,timeout=15)

    def test_only_exact_optional_host_and_origin_added(self):
        for host,expected in (('',''),('192.168.1.25','192.168.1.25'),('fd00::25','[fd00::25]')):
            result=self.profile(host);self.assertEqual(result.returncode,0,result.stderr)
            hosts,origins=json.loads(result.stdout)
            self.assertEqual(hosts,['localhost','127.0.0.1']+([expected] if expected else []))
            self.assertEqual(origins,['http://localhost:8000']+([f'http://{expected}:8000'] if expected else []))

    def test_wildcards_urls_ports_and_unspecified_rejected(self):
        for host in ('*','0.0.0.0','http://192.168.1.25','192.168.1.25:8000','192.168.1.25/','192.168.1.25,evil'):
            self.assertNotEqual(self.profile(host).returncode,0,host)

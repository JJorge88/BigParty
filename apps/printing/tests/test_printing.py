from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Event
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import uuid

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db import transaction, connections, IntegrityError, connection
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.cash import services as cash
from apps.catalog.models import Product
from apps.orders import services as orders
from apps.orders.tests.base import OrdersTestCase
from apps.orders.models import PreparationTicketItem
from apps.payments import services as payments
from apps.tables.models import VenueTable
from apps.venues.models import Area
from apps.printing.models import Printer, PrintJob
from apps.printing import services, rendering, backends


class PrinterAndRoutingTests(OrdersTestCase):
    def setUp(self):
        self.bar = Printer.objects.create(name='Barra 1', code='BAR-SPORT', printer_type='BAR', area=self.area)
        self.kitchen = Printer.objects.create(name='Cocina', code='KITCHEN', printer_type='KITCHEN')
        self.food = Product.objects.create(name='Hamburguesa', slug='burger', category=self.category, base_price=50, preparation_route='KITCHEN')

    def mixed(self):
        order = self.open()
        bar = orders.add_product_to_order(order, self.product, 2, self.user)
        food = orders.add_product_to_order(order, self.food, 1, self.user, notes='Bien cocida')
        ticket = orders.send_order(order, self.user)
        return order, bar, food, ticket

    def test_bar_requires_area(self):
        with self.assertRaises(ValidationError):
            Printer.objects.create(name='Invalid', code='INVALID', printer_type='BAR')

    def test_kitchen_rejects_area(self):
        with self.assertRaises(ValidationError):
            Printer.objects.create(name='Invalid', code='INVALID', printer_type='KITCHEN', area=self.area)

    def test_unique_code(self):
        with self.assertRaises(ValidationError):
            Printer.objects.create(name='Duplicate', code=self.bar.code, printer_type='BAR', area=self.other_area)

    def test_only_one_active_bar_per_area(self):
        with self.assertRaises(ValidationError):
            Printer.objects.create(name='Duplicate', code='SECOND', printer_type='BAR', area=self.area)
        Printer.objects.create(name='Spare', code='SPARE', printer_type='BAR', area=self.area, is_active=False)

    def test_only_one_active_kitchen(self):
        with self.assertRaises(ValidationError):
            Printer.objects.create(name='Duplicate', code='SECOND', printer_type='KITCHEN')

    def test_host_port_paper_validation(self):
        for field, value in [('host','https://printer:9100'),('port',0),('port',65536),('paper_width','79'),('encoding','invalid'),('codepage',256)]:
            with self.subTest(field=field, value=value):
                printer=Printer(name='Other', code='OTHER', printer_type='BAR', area=self.other_area)
                setattr(printer,field,value)
                with self.assertRaises(ValidationError): printer.full_clean()

    def test_database_constraints(self):
        for change in [{'area':None},{'port':0},{'paper_width':'42'}]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                Printer.objects.filter(pk=self.bar.pk).update(**change)

    def test_seed_idempotent_preserves_configuration(self):
        Area.objects.create(name='Discoteca', slug='discoteca')
        self.bar.host='printer.local'; self.bar.port=9200; self.bar.save()
        call_command('seed_printer_defaults',stdout=StringIO())
        call_command('seed_printer_defaults',stdout=StringIO())
        self.assertEqual(Printer.objects.count(),4)
        self.bar.refresh_from_db(); self.assertEqual((self.bar.host,self.bar.port),('printer.local',9200))
        self.assertEqual(Printer.objects.exclude(pk=self.bar.pk).filter(host='').count(),3)

    def test_three_area_routes_and_shared_kitchen(self):
        disco=Area.objects.create(name='Discoteca',slug='discoteca')
        call_command('seed_printer_defaults',stdout=StringIO())
        for area, name in [(self.area,'Barra 1'),(disco,'Barra 2'),(self.other_area,'Barra 3')]:
            table=VenueTable.objects.create(area=area,name='Mesa 07',capacity=4)
            order=self.open(table)
            orders.add_product_to_order(order,self.product,1,self.user)
            orders.add_product_to_order(order,self.food,1,self.user)
            ticket=orders.send_order(order,self.user)
            self.assertCountEqual(ticket.print_jobs.values_list('printer__name',flat=True),[name,'Cocina'])

    def test_mixed_snapshot_contains_only_station_items(self):
        order, _, _, ticket = self.mixed()
        bar=ticket.print_jobs.get(printer=self.bar).payload_snapshot
        kitchen=ticket.print_jobs.get(printer=self.kitchen).payload_snapshot
        self.assertIn('2  CERVEZA',bar['text']); self.assertNotIn('HAMBURGUESA',bar['text'])
        self.assertIn('1  HAMBURGUESA',kitchen['text']); self.assertNotIn('CERVEZA',kitchen['text'])
        self.assertIn('Bien cocida',kitchen['text'])
        self.assertEqual(bar['timestamp'],kitchen['timestamp'])
        self.assertEqual(bar['order_number'],order.order_number)
        self.assertFalse(order.print_jobs.filter(job_type='RECEIPT').exists())

    def test_none_ignored(self):
        self.product.preparation_route='NONE'; self.product.save()
        order=self.open(); orders.add_product_to_order(order,self.product,1,self.user)
        self.assertIsNone(orders.send_order(order,self.user))
        self.assertFalse(PrintJob.objects.exists())

    def test_addition_only_new_items(self):
        order,_,_,_=self.mixed()
        corona=Product.objects.create(name='Corona',slug='corona',category=self.category,base_price=30,preparation_route='AREA_BAR')
        orders.add_product_to_order(order,corona,1,self.user)
        ticket=orders.send_order(order,self.user)
        text=ticket.print_jobs.get().payload_snapshot['text']
        self.assertIn('*** ADICIÓN ***',text); self.assertIn('CORONA',text)
        self.assertNotIn('CERVEZA',text); self.assertNotIn('HAMBURGUESA',text)

    def test_cancel_only_affected_station_with_reason(self):
        order,bar,_,_=self.mixed()
        orders.cancel_sent_line(bar,self.user,'Cliente cambió de idea')
        job=order.print_jobs.get(job_type='CANCELLATION')
        self.assertEqual(job.printer,self.bar)
        self.assertIn('*** CANCELACIÓN ***',job.payload_snapshot['text'])
        self.assertIn('CANCELAR:',job.payload_snapshot['text'])
        self.assertIn('Cliente cambió de idea',job.payload_snapshot['text'])
        self.assertNotIn('HAMBURGUESA',job.payload_snapshot['text'])

    def test_update_only_affected_station_and_new_note(self):
        order,_,food,_=self.mixed()
        orders.update_sent_line_note(food,'Sin salsa',self.user)
        job=order.print_jobs.get(job_type='UPDATE')
        self.assertEqual(job.printer,self.kitchen)
        self.assertIn('*** ACTUALIZACIÓN ***',job.payload_snapshot['text'])
        self.assertIn('NUEVA NOTA:\nSin salsa',job.payload_snapshot['text'])

    def test_take_at_bar_only_kitchen(self):
        order=self.open()
        orders.add_product_to_order(order,self.product,1,self.user)
        orders.add_product_to_order(order,self.food,1,self.user)
        ticket=orders.send_order(order,self.user,fulfillment_mode='TAKE_AT_BAR')
        self.assertEqual(ticket.print_jobs.get().printer,self.kitchen)

    def test_same_ticket_does_not_duplicate_or_reschedule(self):
        _,_,_,ticket=self.mixed()
        with self.captureOnCommitCallbacks() as callbacks:
            jobs=services.create_print_jobs_for_ticket(ticket)
        self.assertEqual(len(jobs),2); self.assertEqual(ticket.print_jobs.count(),2); self.assertEqual(callbacks,[])

    def test_original_constraint_survives_printer_replacement(self):
        _,_,_,ticket=self.mixed()
        original=ticket.print_jobs.get(printer=self.bar)
        with self.assertRaises(IntegrityError), transaction.atomic():
            PrintJob.objects.create(printer=None,destination_key=original.destination_key,preparation_ticket=ticket,order=ticket.order,job_type='PREPARATION')

    def test_missing_printer_keeps_order_and_failure(self):
        self.bar.is_active=False; self.bar.save()
        order,_,_,ticket=self.mixed()
        job=ticket.print_jobs.get(destination_key=f'bar:{self.area.pk}')
        self.assertEqual(job.status,'FAILED'); self.assertIsNone(job.printer); self.assertEqual(job.attempt_count,0)
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity,98)
        self.assertIn('Pedido registrado',services.order_print_status(order)['message'])

    def test_receipt_is_explicit_and_snapshot_has_totals(self):
        order,_,_,_=self.mixed()
        payments.apply_order_adjustment(order,self.user,amount='10',reason='Promoción')
        payments.pay_full_balance(order,'CARD',self.user,card_approved=True)
        payments.close_order(order,self.user)
        self.assertFalse(order.print_jobs.filter(job_type='RECEIPT').exists())
        job=services.print_receipt(order,None,self.user)
        text=job.payload_snapshot['text']
        for expected in ['SUBTOTAL Q100.00','DESCUENTO -Q10.00','TOTAL Q90.00','Tarjeta Q90.00','SALDO Q0.00']:
            self.assertIn(expected,text)
        self.assertNotIn('FEL',text); self.assertNotIn('NIT',text)
        self.assertEqual(job.printer,self.bar)

    def test_receipt_refuses_open_order_and_wrong_bar(self):
        order,_,_,_=self.mixed()
        with self.assertRaises(ValidationError): services.print_receipt(order,None,self.user)
        payments.pay_full_balance(order,'CARD',self.user,card_approved=True); payments.close_order(order,self.user)
        with self.assertRaises(ValidationError): services.print_receipt(order,self.kitchen,self.user)

    def test_receipt_repeated_while_pending_keeps_original(self):
        order,_,_,_=self.mixed()
        payments.pay_full_balance(order,'CARD',self.user,card_approved=True); payments.close_order(order,self.user)
        a=services.print_receipt(order,None,self.user)
        b=services.print_receipt(order,None,self.user)
        self.assertEqual(a.pk,b.pk)

    def test_receipt_copy_and_signed_request_replay(self):
        order,_,_,_=self.mixed()
        payments.pay_full_balance(order,'CARD',self.user,card_approved=True); payments.close_order(order,self.user)
        key=uuid.uuid4(); original=services.print_receipt(order,None,self.user,request_key=key)
        PrintJob.objects.filter(pk=original.pk).update(status='PRINTED')
        self.assertEqual(services.print_receipt(order,None,self.user,request_key=key).pk,original.pk)
        copy=services.print_receipt(order,None,self.user)
        self.assertEqual(copy.reprint_of,original)
        self.assertIn('REIMPRESIÓN',copy.payload_snapshot['text'])
        self.assertTrue(AuditLog.objects.filter(action='printing.created',entity_id=str(copy.pk),data__reprint_of=original.pk).exists())

    def test_reprint_requires_permission_reason_relationship_and_printed(self):
        _,_,_,ticket=self.mixed()
        user=get_user_model().objects.create_user(username='mesero',role='MESERO')
        with self.assertRaises(PermissionDenied): services.reprint_ticket(ticket,self.bar,user,'Copia',scope_area=self.area)
        with self.assertRaises(ValidationError): services.reprint_ticket(ticket,self.bar,self.user,'')
        with self.assertRaises(ValidationError): services.reprint_ticket(ticket,self.bar,self.user,'Copia')
        other=Printer.objects.create(name='Otra barra',code='OTHER',printer_type='BAR',area=self.other_area)
        with self.assertRaises(ValidationError): services.reprint_ticket(ticket,other,self.user,'Copia')

    def test_scope_blocks_other_area_unless_administrative_permission(self):
        _,_,_,ticket=self.mixed()
        user=get_user_model().objects.create_user(username='cajero',role='CAJERO')
        user.user_permissions.add(Permission.objects.get(codename='reprint_preparation_ticket'))
        ticket.print_jobs.update(status='PRINTED')
        with self.assertRaises(PermissionDenied): services.reprint_ticket(ticket,self.bar,user,'Copia',scope_area=self.other_area)
        with self.assertRaises(PermissionDenied): services.reprint_ticket(ticket,self.bar,user,'Copia')
        copy=services.reprint_ticket(ticket,self.bar,user,'Papel ilegible',scope_area=self.area)
        self.assertIsNotNone(copy.reprint_of)

    def test_retry_missing_configuration_same_job(self):
        self.bar.is_active=False; self.bar.save()
        _,_,_,ticket=self.mixed(); job=ticket.print_jobs.get(status='FAILED')
        with self.assertRaises(ValidationError): services.retry_print_job(job,self.user)
        self.bar.is_active=True; self.bar.save()
        renewed=services.retry_print_job(job,self.user)
        self.assertEqual(renewed.pk,job.pk); self.assertEqual(renewed.printer,self.bar)
        with self.assertRaises(ValidationError): services.retry_print_job(renewed,self.user)

    def test_snapshot_keeps_history_after_catalog_or_note_changes(self):
        _,_,food,ticket=self.mixed(); original=ticket.print_jobs.get(printer=self.kitchen)
        snapshot=original.payload_snapshot
        self.food.name='Nuevo nombre'; self.food.save()
        orders.update_sent_line_note(food,'Sin sal',self.user)
        original.refresh_from_db(); self.assertEqual(original.payload_snapshot,snapshot)

    def test_configuration_uses_business_permission_and_test_requires_post(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/impresoras/').status_code,200)
        self.assertEqual(self.client.get(f'/impresoras/{self.bar.pk}/prueba/').status_code,405)
        self.assertEqual(self.client.post(f'/impresoras/{self.bar.pk}/prueba/').status_code,302)
        self.assertEqual(PrintJob.objects.get().job_type,'TEST')
        user=get_user_model().objects.create_user(username='staff',is_staff=True,role='CAJERO')
        self.client.force_login(user)
        self.assertEqual(self.client.get('/impresoras/').status_code,403)
        user.user_permissions.add(Permission.objects.get(codename='manage_printers'))
        self.assertEqual(self.client.get('/impresoras/').status_code,200)

    def test_manager_can_create_network_printer_without_admin(self):
        self.client.force_login(self.user)
        response = self.client.post('/impresoras/nueva/', {
            'name': 'Disco', 'printer_type': 'BAR', 'area': self.other_area.pk,
            'host': '192.168.1.80', 'paper_width': '80', 'port': 9100,
            'encoding': 'ascii', 'transliterate': 'on', 'is_active': 'on'})
        self.assertRedirects(response, '/impresoras/')
        printer = Printer.objects.get(name='Disco')
        self.assertEqual((printer.area, printer.host, printer.code), (self.other_area, '192.168.1.80', 'disco'))

    def test_csrf_enforced_on_test_action(self):
        from django.test import Client
        client=Client(enforce_csrf_checks=True); client.force_login(self.user)
        self.assertEqual(client.post(f'/impresoras/{self.bar.pk}/prueba/').status_code,403)
        self.assertFalse(PrintJob.objects.exists())


class BackendTests(SimpleTestCase):
    def printer(self,**kwargs):
        return SimpleNamespace(encoding='ascii',transliterate=True,codepage=None,supports_cut=False,host='127.0.0.1',port=9200,**kwargs)

    def job(self):
        return SimpleNamespace(pk=123,attempt_count=1,printer=self.printer(),payload_snapshot={'text':'Cóctel · Adición · Cancelación\n'})

    def test_debug_file_retains_unicode_and_refuses_overwrite(self):
        with TemporaryDirectory() as root, override_settings(PRINTER_DEBUG_DIR=root):
            job=self.job(); path=backends.DebugPrinterBackend().send(job)
            self.assertEqual(Path(path).read_text(),job.payload_snapshot['text'])
            with self.assertRaises(FileExistsError): backends.DebugPrinterBackend().send(job)
            job.attempt_count=2; self.assertNotEqual(path,backends.DebugPrinterBackend().send(job))

    def test_encoding_accents_transliteration_and_fallback(self):
        job=self.job()
        for encoding in ['ascii','cp850','cp858','utf-8']:
            job.printer.encoding=encoding
            self.assertIsInstance(backends.escpos_payload(job),bytes)
        job.printer.encoding='ascii'; self.assertIn(b'Coctel',backends.escpos_payload(job))
        job.printer.transliterate=False; job.printer.encoding='utf-8'
        self.assertIn('Cóctel'.encode(),backends.escpos_payload(job))
        self.assertIn('Cóctel',job.payload_snapshot['text'])

    def test_cut_and_codepage_only_when_configured(self):
        job=self.job(); self.assertNotIn(b'\x1dV',backends.escpos_payload(job))
        job.printer.supports_cut=True; job.printer.codepage=19
        payload=backends.escpos_payload(job)
        self.assertTrue(payload.startswith(b'\x1b@\x1bt\x13')); self.assertTrue(payload.endswith(b'\x1dV\x00'))

    def test_notes_cannot_inject_escpos_commands(self):
        job=self.job(); job.payload_snapshot['text']='Nota\x1b@\x1dV\x00fin'
        self.assertEqual(backends.escpos_payload(job).count(b'\x1b'),1)
        self.assertNotIn(b'\x1d',backends.escpos_payload(job))

    def test_width_58_and_80_wrap_long_notes(self):
        for width, columns in [('58',32),('80',48)]:
            result=rendering.render(['--','PALABRALARGA'*12,'Nota para la cocina '*10],width)
            self.assertTrue(all(len(line)<=columns for line in result.splitlines()))
            self.assertEqual(len(result.splitlines()[0]),columns)

    @override_settings(PRINTER_CONNECT_TIMEOUT=0.2,PRINTER_WRITE_TIMEOUT=0.3)
    def test_network_uses_configured_host_port_and_timeout(self):
        job=self.job(); sock=MagicMock()
        with patch.object(backends,'connect',return_value=sock) as connect:
            self.assertEqual(backends.NetworkEscPosBackend().send(job),'')
        connect.assert_called_once_with('127.0.0.1',9200,0.2)
        sock.settimeout.assert_called_once_with(0.3)
        sock.sendall.assert_called_once_with(backends.escpos_payload(job))

    def test_network_empty_host_fails_without_connection(self):
        job=self.job(); job.printer.host=''
        with patch.object(backends,'connect') as connect, self.assertRaises(backends.PrinterError):
            backends.NetworkEscPosBackend().send(job)
        connect.assert_not_called()

    def test_connection_failure_is_certain_but_send_failure_uncertain(self):
        with patch.object(backends,'connect',side_effect=TimeoutError('offline')):
            with self.assertRaises(backends.PrinterError) as exc: backends.NetworkEscPosBackend().send(self.job())
        self.assertFalse(exc.exception.uncertain)
        sock=MagicMock(); sock.sendall.side_effect=TimeoutError('partial')
        with patch.object(backends,'connect',return_value=sock):
            with self.assertRaises(backends.PrinterError) as exc: backends.NetworkEscPosBackend().send(self.job())
        self.assertTrue(exc.exception.uncertain)

    def test_hostname_resolution_timeout_is_bounded(self):
        gate=Event()
        def dns(*args,**kwargs):
            gate.wait(1)
            return []
        try:
            with patch.object(backends.socket,'getaddrinfo',side_effect=dns):
                with self.assertRaises(TimeoutError): backends.connect('printer.local',9100,0.01)
        finally:
            gate.set()


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DeliveryTransactionTests(TransactionTestCase):
    def setUp(self):
        OrdersTestCase.setUpTestData.__func__(type(self))
        self.tmp=TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        settings=override_settings(PRINTER_BACKEND='debug',PRINTER_DEBUG_DIR=self.tmp.name)
        settings.enable(); self.addCleanup(settings.disable)
        self.bar=Printer.objects.create(name='Barra 1',code='BAR',printer_type='BAR',area=self.area)
        self.kitchen=Printer.objects.create(name='Cocina',code='KITCHEN',printer_type='KITCHEN')
        self.food=Product.objects.create(name='Hamburguesa',slug='food',category=self.category,base_price=50,preparation_route='KITCHEN')

    def order(self):
        order=orders.open_table_order(self.table,self.user)
        orders.add_product_to_order(order,self.product,2,self.user)
        orders.add_product_to_order(order,self.food,1,self.user)
        return order

    def test_automatic_delivery_only_after_commit_outside_atomic(self):
        order=self.order(); observed=[]
        backend=backends.DebugPrinterBackend()
        def send(job):
            observed.append(connection.in_atomic_block)
            return backend.send(job)
        with patch.object(services,'get_backend',return_value=SimpleNamespace(send=send)):
            with transaction.atomic():
                ticket=orders.send_order(order,self.user)
                self.assertEqual(ticket.print_jobs.filter(status='PENDING').count(),2)
                self.assertEqual(observed,[])
        self.assertEqual(observed,[False,False])
        self.assertEqual(ticket.print_jobs.filter(status='PRINTED',attempt_count=1).count(),2)
        self.assertEqual(len(list(Path(self.tmp.name).glob('*.txt'))),2)

    def test_rollback_leaves_no_jobs_tickets_stock_or_output(self):
        order=self.order()
        with self.assertRaises(ValueError):
            with transaction.atomic():
                orders.send_order(order,self.user)
                raise ValueError('rollback')
        self.assertFalse(PrintJob.objects.exists()); self.assertFalse(order.tickets.exists())
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity,100)
        self.assertEqual(list(Path(self.tmp.name).glob('*')),[])

    def test_failed_kitchen_does_not_revert_order_or_repeat_bar(self):
        order=self.order(); backend=backends.DebugPrinterBackend()
        def send(job):
            if job.printer_id==self.kitchen.pk: raise backends.PrinterError('Sin papel')
            return backend.send(job)
        with patch.object(services,'get_backend',return_value=SimpleNamespace(send=send)):
            ticket=orders.send_order(order,self.user)
        bar=ticket.print_jobs.get(printer=self.bar); kitchen=ticket.print_jobs.get(printer=self.kitchen)
        self.assertEqual(bar.status,'PRINTED'); self.assertEqual(kitchen.status,'FAILED')
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity,98)
        services.retry_print_job(kitchen,self.user)
        kitchen.refresh_from_db(); bar.refresh_from_db()
        self.assertEqual((kitchen.status,kitchen.attempt_count),('PRINTED',2))
        self.assertEqual(bar.attempt_count,1); self.assertEqual(ticket.print_jobs.count(),2)
        self.assertEqual(len(list(Path(self.tmp.name).glob('*.txt'))),2)

    def test_two_workers_send_same_job_only_once(self):
        with patch.object(services,'schedule'):
            job=services.print_test_page(self.bar,self.user)
        barrier=Barrier(2)
        def run():
            try:
                barrier.wait(timeout=5)
                return services.print_job(job.pk).status
            finally: connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(lambda _:run(),range(2)))
        job.refresh_from_db(); self.assertEqual(job.status,'PRINTED'); self.assertEqual(job.attempt_count,1)
        self.assertEqual(len(list(Path(self.tmp.name).glob('*.txt'))),1)
        self.assertIn('PRINTED',results)

    def test_concurrent_original_job_creation(self):
        order=self.order()
        # Suppress only the receiver's create call to simulate an existing imported ticket.
        with patch('apps.printing.signals.create_print_jobs_for_ticket'):
            ticket=orders.send_order(order,self.user)
        barrier=Barrier(2)
        def run():
            try:
                barrier.wait(timeout=5)
                return [j.pk for j in services.create_print_jobs_for_ticket(ticket)]
            finally: connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(lambda _:run(),range(2)))
        self.assertEqual(results[0],results[1]); self.assertEqual(ticket.print_jobs.count(),2)
        self.assertEqual(len(list(Path(self.tmp.name).glob('*.txt'))),2)

    def test_explicit_copy_has_new_job_and_audit(self):
        ticket=orders.send_order(self.order(),self.user)
        key=uuid.uuid4()
        copy=services.reprint_ticket(ticket,self.bar,self.user,'Papel ilegible',request_key=key)
        repeated=services.reprint_ticket(ticket,self.bar,self.user,'Papel ilegible',request_key=key)
        self.assertEqual(copy.pk,repeated.pk)
        copy.refresh_from_db(); self.assertEqual(copy.status,'PRINTED')
        self.assertEqual(ticket.print_jobs.count(),3)
        self.assertEqual(copy.reprint_of.attempt_count,1)

    def test_recover_stale_marks_failed_without_delivery(self):
        with patch.object(services,'schedule'):
            job=services.print_test_page(self.bar,self.user)
        PrintJob.objects.filter(pk=job.pk).update(status='PRINTING',printing_started_at=timezone.now()-timedelta(minutes=10),attempt_count=1)
        call_command('recover_stale_print_jobs',stdout=StringIO())
        job.refresh_from_db(); self.assertEqual(job.status,'FAILED'); self.assertTrue(job.delivery_uncertain)
        self.assertEqual(job.attempt_count,1); self.assertEqual(list(Path(self.tmp.name).glob('*')),[])
        services.retry_print_job(job,self.user)
        job.refresh_from_db(); self.assertEqual(job.attempt_count,2)

    def test_recovery_skips_live_worker_even_when_old(self):
        with patch.object(services,'schedule'):
            job=services.print_test_page(self.bar,self.user)
        entered, release=Event(),Event()
        def send(current):
            entered.set(); release.wait(5); return ''
        def run():
            try: return services.print_job(job.pk)
            finally: connections.close_all()
        with patch.object(services,'get_backend',return_value=SimpleNamespace(send=send)), ThreadPoolExecutor(max_workers=1) as executor:
            future=executor.submit(run)
            try:
                self.assertTrue(entered.wait(5))
                PrintJob.objects.filter(pk=job.pk).update(printing_started_at=timezone.now()-timedelta(minutes=10))
                self.assertEqual(services.recover_stale_jobs(),[])
            finally: release.set()
            self.assertEqual(future.result(timeout=5).status,'PRINTED')

    def test_pending_batch_is_bounded_and_skips_failed(self):
        with patch.object(services,'schedule'):
            for _ in range(3): services.print_test_page(self.bar,self.user)
        PrintJob.objects.filter(pk=PrintJob.objects.first().pk).update(status='FAILED')
        call_command('process_print_jobs',limit=1,stdout=StringIO())
        self.assertEqual(PrintJob.objects.filter(status='PRINTED').count(),1)
        self.assertEqual(PrintJob.objects.filter(status='PENDING').count(),1)
        self.assertEqual(PrintJob.objects.filter(status='FAILED').count(),1)

    def test_transport_forbidden_inside_transaction(self):
        with transaction.atomic(), self.assertRaises(RuntimeError): services.print_job(123)

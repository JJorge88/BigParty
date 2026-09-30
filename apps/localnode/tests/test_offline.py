from decimal import Decimal
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
from threading import Thread
from types import SimpleNamespace
from django.contrib.auth.models import Permission
from django.test import Client, SimpleTestCase, TransactionTestCase, override_settings
from apps.operations.tests.base import OperationsTestCase
from apps.orders.models import TableOrder
from apps.orders import services as orders
from apps.payments import services as payments
from apps.payments.models import Payment
from apps.cash import services as cash
from apps.cash.models import CashRegister
from apps.printing.models import Printer, PrintJob
from apps.printing.backends import NetworkEscPosBackend
from apps.localnode.tests.offline import offline_network


@override_settings(DEPLOYMENT_MODE='local_node',DEBUG=False,ALLOWED_HOSTS=['pos.bigparty.lan','testserver'],SESSION_COOKIE_SECURE=True)
class OfflineOperationTests(TransactionTestCase):
    bind = OperationsTestCase.bind
    login = OperationsTestCase.login
    enter = OperationsTestCase.enter
    open_table = OperationsTestCase.open_table
    make_waiter = classmethod(OperationsTestCase.make_waiter.__func__)

    def setUp(self):
        from apps.orders.tests.base import OrdersTestCase
        from apps.operations.models import OperationalDevice
        OrdersTestCase.setUpTestData.__func__(type(self))
        self.user.role='GERENTE';self.user.save()
        self.other_user.role='PROPIETARIO';self.other_user.save()
        self.waiter=self.make_waiter('carlos','Carlos','Mendez','2580')
        self.device=OperationalDevice.objects.create(name='Tablet LAN',code='TAB-LAN',area=self.area)

    def test_complete_lan_workday_without_external_connections(self):
        self.waiter.user_permissions.add(*Permission.objects.filter(codename__in=['add_order_line','send_order','manage_subaccounts','view_payment','record_payment','close_order']))
        self.client=Client(HTTP_HOST='pos.bigparty.lan',wsgi_url_scheme='https')
        with TemporaryDirectory() as directory, override_settings(PRINTER_BACKEND='debug',PRINTER_DEBUG_DIR=directory), offline_network() as attempted:
            Printer.objects.create(name='Bar LAN',code='bar-lan',printer_type='BAR',area=self.area,host='192.168.10.20')
            register=CashRegister.objects.create(name='Caja LAN',code='SPORT',area=self.area)
            # Existing browser/register binding and PIN sessions work under a LAN hostname.
            cashier=Client(HTTP_HOST='pos.bigparty.lan')
            self.user.set_pin('654321');self.user.save()
            cashier.force_login(self.user)
            response=cashier.post('/caja/configurar/',{'register':register.pk})
            self.assertEqual(response.status_code,302)
            from apps.operations.cash_security import REGISTER_COOKIE,ACCESS_COOKIE
            binding=cashier.cookies[REGISTER_COOKIE]
            self.assertEqual(binding['domain'],'');self.assertEqual(binding['path'],'/caja/');self.assertTrue(binding['secure'])
            cashier.logout();cashier.cookies[REGISTER_COOKIE]=binding
            response=cashier.post('/caja/acceso/',{'user_id':self.user.pk,'pin':'654321'},HTTP_ACCEPT='application/json')
            self.assertEqual(response.status_code,200,response.content)
            self.assertTrue(response.cookies[ACCESS_COOKIE]['secure'])
            response=cashier.post('/caja/accion/abrir/',{'opening_float':'100'},HTTP_ACCEPT='application/json')
            self.assertEqual(response.status_code,200,response.content)
            session=register.sessions.get(status='OPEN')
            self.enter()
            from apps.operations.security import SESSION_COOKIE,DEVICE_COOKIE
            for name in (SESSION_COOKIE,DEVICE_COOKIE):
                self.assertTrue(self.client.cookies[name]['secure']);self.assertEqual(self.client.cookies[name]['domain'],'')
            self.assertEqual(self.open_table().status_code,201)
            order=TableOrder.objects.get(status='OPEN')
            prefix=f'/operacion/orden/{order.pk}/'
            response=self.client.post(prefix+'pedido/agregar/',{'product':self.product.pk,'quantity':4},HTTP_ACCEPT='application/json')
            self.assertEqual(response.status_code,200,response.content)
            response=self.client.post(prefix+'pedido/enviar/',{},HTTP_ACCEPT='application/json')
            self.assertEqual(response.status_code,200,response.content)
            self.product.refresh_from_db();self.assertEqual(self.product.stock_quantity,96)
            self.assertTrue(PrintJob.objects.filter(status='PRINTED').exists())
            self.assertTrue(list(Path(directory).glob('*.txt')))
            # Cash + manually acknowledged terminal card; no banking API.
            paid=payments.create_amount_payment(order,Decimal('50'),'CASH',self.waiter,received_amount=Decimal('50'))
            payments.create_amount_payment(order,Decimal('50'),'CARD',self.waiter,card_approved=True)
            response=self.client.post(prefix+'cuenta/cerrar/',{},HTTP_ACCEPT='application/json')
            self.assertEqual(response.status_code,200,response.content)
            order.refresh_from_db();self.assertEqual(order.status,'CLOSED')
            cash.confirm_cash_handoff(paid,session,self.user)
            cash.create_cash_withdrawal(session,Decimal('10'),'Cambio',self.user,self.other_user)
            cash.submit_blind_cash_count(session,Decimal('140'),self.user)
            cash.close_cash_session(session,self.user)
            cash.close_business_day(self.day,self.user)
            session.refresh_from_db();self.assertEqual(session.status,'CLOSED')
            self.client.post('/gerencia/acceso/',{'username':self.user.username,'password':'Test-only-981!'})
            self.assertEqual(self.client.get('/gerencia/').status_code,200)
            self.assertEqual(self.client.get('/gerencia/inventario/').status_code,200)
            self.assertEqual(attempted,[])

    def test_offline_transfer_and_deposit_remain_pending(self):
        with offline_network() as attempted:
            order=orders.open_table_order(self.table,self.user);orders.add_product_to_order(order,self.product,4,self.user);orders.send_order(order,self.user)
            for method in ('TRANSFER','DEPOSIT'):
                payment=payments.create_amount_payment(order,Decimal('25'),method,self.user,reference='manual-reference')
                self.assertEqual(payment.status,'PENDING')
            self.assertEqual(Payment.objects.filter(status='CONFIRMED').count(),0)
            self.assertEqual(attempted,[])


class NetworkPrinterOfflineTests(SimpleTestCase):
    def test_network_backend_sends_to_lan_without_public_dns(self):
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(5)
        received=[]
        def collect():
            try:
                client,_=listener.accept()
                with client:
                    client.settimeout(5)
                    while chunk:=client.recv(65536):received.append(chunk)
            finally: listener.close()
        worker=Thread(target=collect);worker.start()
        printer=SimpleNamespace(host='127.0.0.1',port=listener.getsockname()[1],codepage=None,transliterate=True,encoding='ascii',supports_cut=False)
        with offline_network() as attempted:
            NetworkEscPosBackend().send(SimpleNamespace(printer=printer,payload_snapshot={'text':'Comanda offline'}))
            worker.join(timeout=6)
            self.assertEqual(attempted,[])
        self.assertIn(b'Comanda offline',b''.join(received))

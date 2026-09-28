from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TransactionTestCase, override_settings

from apps.cash.models import CashRegister, CashSession, CashMovement
from apps.cash.services import open_business_day
from apps.catalog.models import Category, Product
from apps.operations.cash_security import REGISTER_COOKIE
from apps.operations.models import CashPinAttempt
from apps.orders import services as orders
from apps.payments import services as payments
from apps.tables.models import VenueTable
from apps.venues.models import Area
from . import test_concurrency as access_tests


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class CashWorkstationConcurrencyTests(TransactionTestCase):
    concurrent = access_tests.OperationalConcurrencyTests.concurrent

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(username="admin", role="GERENTE")
        self.admin.set_pin("654321"); self.admin.save()
        self.day = open_business_day(self.admin)
        self.area = Area.objects.create(name="Discoteca", slug="discoteca")
        self.clients, self.users, self.registers = [], [], []
        for n in range(2):
            user = get_user_model().objects.create_user(username=f"cashier{n}", role="CAJERO")
            user.set_pin("2580"); user.save()
            user.user_permissions.add(*Permission.objects.filter(codename__in=["open_cash_session", "receive_waiter_cash", "close_cash_session", "request_cash_withdrawal"]))
            register = CashRegister.objects.create(name=f"Caja {n}", code=f"C{n}", area=self.area)
            client = Client(); client.force_login(self.admin)
            client.post("/caja/configurar/", {"register": register.pk})
            binding = client.cookies[REGISTER_COOKIE].value
            client.logout(); client.cookies[REGISTER_COOKIE] = binding
            self.assertEqual(client.post("/caja/acceso/", {"user_id": user.pk, "pin": "2580"}, HTTP_ACCEPT="application/json").status_code, 200)
            self.clients.append(client); self.users.append(user); self.registers.append(register)

    def open_all(self):
        for client in self.clients:
            self.assertEqual(client.post("/caja/accion/abrir/", {"opening_float": "500"}, HTTP_ACCEPT="application/json").status_code, 200)

    def test_two_stations_receive_same_handoff_only_once(self):
        self.open_all()
        waiter = get_user_model().objects.create_superuser(username="waiter", role="MESERO")
        table = VenueTable.objects.create(area=self.area, name="Mesa 07", capacity=4)
        category = Category.objects.create(name="Bebidas", slug="bebidas")
        product = Product.objects.create(category=category, name="Gallo", slug="gallo", base_price=25)
        order = orders.open_table_order(table, waiter)
        orders.add_product_to_order(order, product, 4, waiter); orders.send_order(order, waiter)
        handoff = payments.create_amount_payment(order, "100", "CASH", waiter).cash_handoff
        sessions = [CashSession.objects.get(register=register) for register in self.registers]
        results = self.concurrent([lambda c=c, s=s: c.post("/caja/accion/recibir/", {"cash_session": s.pk, "handoff": handoff.pk}, HTTP_ACCEPT="application/json") for c, s in zip(self.clients, sessions)])
        self.assertCountEqual([r.status_code for r in results], [200, 409])
        loser = next(r for r in results if r.status_code == 409)
        self.assertEqual(loser.json()["message"], "Este efectivo ya fue recibido en otra caja.")
        self.assertEqual(CashMovement.objects.count(), 1)
        winner = next(i for i, r in enumerate(results) if r.status_code == 200)
        self.assertEqual(CashMovement.objects.get().created_by, self.users[winner])

    def test_simultaneous_pin_failures_keep_all_five_attempts(self):
        clients = [Client() for _ in range(5)]
        for client in clients: client.cookies.update(self.clients[0].cookies)
        results = self.concurrent([lambda c=c: c.post("/caja/acceso/", {"user_id": self.users[0].pk, "pin": "1111"}, HTTP_ACCEPT="application/json") for c in clients])
        self.assertCountEqual([r.status_code for r in results], [400, 400, 400, 400, 429])
        self.assertEqual(CashPinAttempt.objects.get(register=self.registers[0], user=self.users[0]).failed_attempts, 5)

    def test_duplicate_withdrawal_in_parallel_only_records_once(self):
        self.open_all()
        client = self.clients[0]
        token = client.get("/caja/retiro/", HTTP_ACCEPT="application/json").json()["withdrawal_token"]
        duplicate = Client(); duplicate.cookies.update(client.cookies)
        session = CashSession.objects.get(register=self.registers[0])
        data = {"cash_session": session.pk, "withdrawal_token": token, "amount": "100", "reason": "Cambio", "approver_id": self.admin.pk, "approver_pin": "654321"}
        results = self.concurrent([lambda c=c: c.post("/caja/accion/retirar/", data, HTTP_ACCEPT="application/json") for c in (client, duplicate)])
        self.assertCountEqual([r.status_code for r in results], [200, 409])
        self.assertEqual(CashMovement.objects.count(), 1)

    def test_same_station_concurrent_open_creates_single_session(self):
        client = self.clients[0]
        duplicate = Client(); duplicate.cookies.update(client.cookies)
        results = self.concurrent([lambda c=c: c.post("/caja/accion/abrir/", {"opening_float": "500"}, HTTP_ACCEPT="application/json") for c in (client, duplicate)])
        self.assertCountEqual([r.status_code for r in results], [200, 409])
        self.assertEqual(CashSession.objects.count(), 1)

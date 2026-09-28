from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connections
from django.test import Client, TransactionTestCase, override_settings

from apps.cash.services import open_business_day
from apps.operations.models import OperationalDevice, PinAttempt
from apps.operations.security import DEVICE_COOKIE
from apps.orders.models import TableOrder
from apps.tables.models import VenueTable
from apps.venues.models import Area


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class OperationalConcurrencyTests(TransactionTestCase):
    def setUp(self):
        admin = get_user_model().objects.create_superuser(username="admin", role="GERENTE")
        open_business_day(admin)
        area = Area.objects.create(name="Área", slug="area")
        self.table = VenueTable.objects.create(area=area, name="Mesa", capacity=4)
        self.clients, self.users = [], []
        for n in range(2):
            user = get_user_model().objects.create_user(username=f"mesero{n}", role="MESERO")
            user.set_pin("2580"); user.save()
            user.user_permissions.add(Permission.objects.get(codename="view_venuetable", content_type__app_label="tables"), Permission.objects.get(codename="open_table_order", content_type__app_label="orders"))
            self.users.append(user)
            device = OperationalDevice.objects.create(name=f"Tablet {n}", code=f"T{n}", area=area)
            client = Client()
            client.force_login(admin)
            self.assertEqual(client.post("/dispositivo/configurar/", {"device": device.pk}).status_code, 302)
            binding = client.cookies[DEVICE_COOKIE].value
            client.logout()
            client.cookies[DEVICE_COOKIE] = binding
            self.clients.append(client)

    def concurrent(self, calls):
        barrier = Barrier(len(calls))
        def worker(call):
            try:
                barrier.wait(timeout=10)
                return call()
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=len(calls)) as executor:
            futures = [executor.submit(worker, call) for call in calls]
            return [future.result(timeout=20) for future in futures]

    def test_two_devices_open_same_table_once_with_real_actor(self):
        for client, user in zip(self.clients, self.users):
            self.assertEqual(client.post("/operacion/acceso/", {"user_id": user.pk, "pin": "2580"}, HTTP_ACCEPT="application/json").status_code, 200)
        results = self.concurrent([lambda client=client: client.post(f"/operacion/mesas/{self.table.pk}/abrir/", {"billing_mode": "SINGLE"}, HTTP_ACCEPT="application/json") for client in self.clients])
        self.assertCountEqual([r.status_code for r in results], [201, 409])
        order = TableOrder.objects.get()
        winner = next(i for i, r in enumerate(results) if r.status_code == 201)
        self.assertEqual(order.opened_by, self.users[winner])
        self.assertEqual(order.responsible_waiter, self.users[winner])
        self.assertIn("acaba de ser ocupada", next(r for r in results if r.status_code == 409).json()["message"])

    def test_concurrent_failed_pins_cannot_lose_attempts(self):
        clients = [Client() for _ in range(5)]
        for client in clients:
            client.cookies.update(self.clients[0].cookies)
        results = self.concurrent([lambda client=client: client.post("/operacion/acceso/", {"user_id": self.users[0].pk, "pin": "9999"}, HTTP_ACCEPT="application/json") for client in clients])
        self.assertCountEqual([r.status_code for r in results], [400, 400, 400, 400, 429])
        attempt = PinAttempt.objects.get()
        self.assertEqual(attempt.failed_attempts, 5)
        self.assertIsNotNone(attempt.locked_until)

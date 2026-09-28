from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings, Client

from apps.orders.tests.base import OrdersTestCase
from apps.operations.models import OperationalDevice
from apps.operations.security import DEVICE_COOKIE, SESSION_COOKIE


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class OperationsTestCase(OrdersTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.user.role = "GERENTE"
        cls.user.save()
        cls.other_user.role = "PROPIETARIO"
        cls.other_user.save()
        cls.waiter = cls.make_waiter("carlos", "Carlos", "Méndez", "2580")
        cls.second_waiter = cls.make_waiter("ana", "Ana", "López", "4632")
        cls.device = OperationalDevice.objects.create(name="Tablet Sport 01", code="TAB-SPORT-01", area=cls.area)

    @classmethod
    def make_waiter(cls, username, first_name, last_name, pin):
        user = get_user_model().objects.create_user(username=username, first_name=first_name, last_name=last_name, role="MESERO")
        user.set_pin(pin)
        user.save()
        user.user_permissions.add(Permission.objects.get(codename="view_venuetable", content_type__app_label="tables"), Permission.objects.get(codename="open_table_order", content_type__app_label="orders"))
        return user

    def bind(self, client=None, device=None, *, keep_admin=False):
        client = client or self.client
        client.force_login(self.user)
        response = client.post("/dispositivo/configurar/", {"device": (device or self.device).pk})
        self.assertEqual(response.status_code, 302)
        if not keep_admin:
            binding = client.cookies[DEVICE_COOKIE]
            client.logout()
            client.cookies[DEVICE_COOKIE] = binding
        return client

    def login(self, client=None, user=None, pin="2580"):
        client = client or self.client
        return client.post("/operacion/acceso/", {"user_id": (user or self.waiter).pk, "pin": pin}, HTTP_ACCEPT="application/json")

    def enter(self):
        self.bind()
        self.assertEqual(self.login().status_code, 200)

    def open_table(self, table=None, mode="SINGLE", **extra):
        return self.client.post(f"/operacion/mesas/{(table or self.table).pk}/abrir/", {"billing_mode": mode, **extra}, HTTP_ACCEPT="application/json")

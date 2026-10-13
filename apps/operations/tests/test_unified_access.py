from django.test import Client
from django.urls import reverse

from apps.operations.models import OperationalDevice
from apps.operations.security import DEVICE_COOKIE
from .test_administration import AdministrationCase, PASSWORD
from .base import OperationsTestCase


class UnifiedAccessTests(AdministrationCase):
    def test_access_page_routes_pin_to_cash_and_password_to_management(self):
        client = Client()
        self.assertContains(client.get('/ingresar/'), 'PIN o contraseña')
        self.worker.role = 'CAJERO'
        self.worker.save(update_fields=['role'])
        pin = client.post('/ingresar/', {'username': self.worker.username, 'credential': PASSWORD})
        self.assertEqual((pin.status_code, pin['Location']), (307, '/caja/acceso/'))
        password = client.post('/ingresar/', {'username': self.manager.username, 'credential': '2580'})
        self.assertEqual((password.status_code, password['Location']), (307, '/gerencia/acceso/'))

    def test_unknown_or_non_daily_role_gets_generic_error(self):
        response = Client().post('/ingresar/', {'username': 'no-existe', 'credential': '2580'})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'Revisa tu usuario y credencial', status_code=400)

    def test_management_accepts_unified_credential_and_uses_role_redirect(self):
        client = Client()
        response = client.post(reverse('management:login'), {
            'username': self.manager.username, 'credential': PASSWORD})
        self.assertRedirects(response, reverse('management:home'))

class TabletAccessTests(OperationsTestCase):
    def test_tablet_accepts_username_and_pin(self):
        client = self.bind(Client())
        response = client.post('/tablet/', {'username': self.waiter.username, 'pin': '2580'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('operations:tables'))

    def test_tablet_login_creates_internal_device_when_none_exists(self):
        OperationalDevice.objects.all().delete()
        client = Client()

        response = client.post('/tablet/', {'username': self.waiter.username, 'pin': '2580'})

        self.assertEqual((response.status_code, response['Location']), (302, reverse('operations:tables')))
        self.assertIn(DEVICE_COOKIE, response.cookies)
        self.assertEqual(OperationalDevice.objects.count(), 1)
        self.assertEqual(OperationalDevice.objects.get().code, 'tablet-web')

    def test_two_new_browsers_do_not_create_duplicate_tablets(self):
        OperationalDevice.objects.all().delete()

        for _ in range(2):
            response = Client().post('/tablet/', {'username': self.waiter.username, 'pin': '2580'})
            self.assertEqual(response.status_code, 302)

        self.assertEqual(OperationalDevice.objects.count(), 1)

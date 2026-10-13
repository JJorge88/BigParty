from django.test import Client
from django.urls import reverse

from .test_administration import AdministrationCase, PASSWORD
from .base import OperationsTestCase


class UnifiedAccessTests(AdministrationCase):
    def test_access_page_routes_pin_to_cash_and_password_to_management(self):
        client = Client()
        self.assertContains(client.get('/ingresar/'), 'PIN o contraseña')
        pin = client.post('/ingresar/', {'username': 'cashier', 'credential': '2580'})
        self.assertEqual((pin.status_code, pin['Location']), (307, '/caja/acceso/'))
        password = client.post('/ingresar/', {'username': self.manager.username, 'credential': PASSWORD})
        self.assertEqual((password.status_code, password['Location']), (307, '/gerencia/acceso/'))

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

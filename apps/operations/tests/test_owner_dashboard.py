from django.test import TestCase, Client
from django.contrib.auth.models import Permission
from apps.accounts.models import User
from apps.accounts.permissions import suggested


class OwnerDashboardTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username='owner-graphs', password='Owner-test-593!', role='PROPIETARIO')
        self.owner.user_permissions.set(Permission.objects.all())
        self.client.post('/gerencia/acceso/', {'username': self.owner.username, 'password': 'Owner-test-593!'})

    def test_owner_only_sees_graphs_even_with_legacy_permissions(self):
        response = self.client.get('/gerencia/')
        self.assertContains(response, 'Gráficas del negocio')
        self.assertContains(response, 'Todavía no hay ventas')
        self.assertNotContains(response, 'href="/gerencia/usuarios/"')
        for path in ['/gerencia/usuarios/', '/gerencia/inventario/', '/gerencia/cierres/', '/gerencia/reportes/', '/gerencia/eventos/']:
            self.assertEqual(self.client.get(path).status_code, 403, path)
        self.assertEqual(self.client.post('/gerencia/usuarios/crear/', {}).status_code, 403)
        self.assertFalse(self.owner.has_perm('accounts.add_user'))
        self.assertFalse(self.owner.has_module_perms('accounts'))
        self.assertEqual(suggested('PROPIETARIO'), {'core.view_reports'})

    def test_dates_validated_and_logout_available(self):
        self.assertEqual(self.client.get('/gerencia/?period=range&start=invalid').status_code, 400)
        self.assertEqual(self.client.post('/gerencia/actividad/').status_code, 200)
        self.assertEqual(self.client.post('/gerencia/salir/').status_code, 302)

    def test_admin_keeps_operational_home(self):
        User.objects.create_superuser(username='admin-check', password='Admin-test-593!', role='GERENTE')
        client = Client()
        client.post('/gerencia/acceso/', {'username': 'admin-check', 'password': 'Admin-test-593!'})
        self.assertContains(client.get('/gerencia/'), '¿Qué necesitas hacer?')
        self.assertEqual(client.get('/gerencia/usuarios/').status_code, 200)

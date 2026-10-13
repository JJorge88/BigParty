from django.contrib.auth.models import Permission
from django.test import Client

from apps.cash import services
from apps.cash.models import CashRegister
from apps.venues.models import Area
from .test_administration import AdministrationCase


class RegisterSetupTests(AdministrationCase):
    def setUp(self):
        super().setUp()
        CashRegister.objects.all().delete()

    def test_empty_installation_creates_first_area_and_register_only_on_submit(self):
        Area.objects.all().delete()
        response = self.client.get(self.url('register-create'))
        self.assertContains(response, 'Nombre de la primera área')
        self.assertFalse(Area.objects.exists())
        self.assertFalse(CashRegister.objects.exists())
        response = self.client.post(self.url('register-create'), {
            'name': 'Caja 1', 'area_name': 'Discoteca', 'is_active': 'on',
        })
        self.assertRedirects(response, self.url('registers'))
        register = CashRegister.objects.get()
        self.assertEqual((register.name, register.area.name, register.code), ('Caja 1', 'Discoteca', 'caja-1'))

    def test_single_area_is_selected_existing_rows_render_and_duplicates_rejected(self):
        response = self.client.get(self.url('register-create'))
        self.assertEqual(response.context['form'].initial['area'], self.area)
        self.client.post(self.url('register-create'), {'name': 'Caja 1', 'area': self.area.pk, 'is_active': 'on'})
        response = self.client.get(self.url('registers'))
        self.assertContains(response, 'Caja 1')
        response = self.client.post(self.url('register-create'), {'name': 'caja 1', 'area': self.area.pk, 'is_active': 'on'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(CashRegister.objects.count(), 1)

    def test_edit_preserves_history_and_open_session_protections(self):
        register = CashRegister.objects.create(name='Caja 1', code='caja-1', area=self.area)
        response = self.client.post(self.url('register-edit', register.pk), {
            'name': 'Caja Principal', 'area': self.area.pk, 'is_active': 'on'})
        self.assertRedirects(response, self.url('registers'))
        cashier = self.worker
        cashier.role = 'CAJERO'; cashier.save()
        cashier.user_permissions.add(Permission.objects.get(codename='open_cash_session'),
                                     Permission.objects.get(codename='close_cash_session'))
        session = services.open_cash_session(register, cashier, '100', cashier)
        response = self.client.post(self.url('register-edit', register.pk), {
            'name': 'Caja Principal', 'area': self.area.pk})
        self.assertEqual(response.status_code, 400)
        register.refresh_from_db(); self.assertTrue(register.is_active)
        services.submit_blind_cash_count(session, '100', cashier)
        services.close_cash_session(session, cashier, '')
        response = self.client.post(self.url('register-edit', register.pk), {
            'name': 'Caja Principal', 'area': self.area.pk})
        self.assertRedirects(response, self.url('registers'))
        register.refresh_from_db(); self.assertFalse(register.is_active)

    def test_cashier_cannot_use_register_administration(self):
        cashier = self.worker
        cashier.role = 'CAJERO'; cashier.save()
        client = Client(); client.force_login(cashier)
        session = client.session
        from django.utils import timezone
        session['management_last_activity'] = timezone.now().timestamp(); session.save()
        self.assertEqual(client.get(self.url('registers')).status_code, 302)

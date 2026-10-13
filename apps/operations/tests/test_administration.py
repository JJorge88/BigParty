"""Contratos HTTP, seguridad y servicios de la Fase 3D sobre PostgreSQL real."""
import json
from concurrent.futures import ThreadPoolExecutor
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from apps.accounts.models import User
from apps.accounts import management_services as users, permissions
from apps.audit.models import AuditLog
from apps.catalog.models import Category, Product, ProductAreaPrice, ModifierGroup, ModifierOption, ComboComponent
from apps.catalog import management_services as catalog, services as prices
from apps.inventory.models import InventoryMovement
from apps.inventory.services import receive_stock
from apps.operations.models import OperationalSession, CashAccessSession, OperationalDevice
from apps.operations import security, cash_security
from apps.venues.models import Area
from apps.cash.models import CashRegister

PASSWORD = 'Secure-administration-76!'


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AdministrationCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = User.objects.create_user(username='manager3d', password=PASSWORD, role='GERENTE')
        cls.manager.user_permissions.add(*Permission.objects.all())
        cls.category = Category.objects.create(name='Cervezas', slug='cervezas')
        cls.product = Product.objects.create(name='Gallo', slug='gallo', category=cls.category, base_price=25,
            track_inventory=True, stock_quantity=4, minimum_stock=6)
        cls.area = Area.objects.create(name='Premium', slug='premium')
        cls.worker = User.objects.create_user(username='carlos', role='MESERO', first_name='Carlos', last_name='Méndez')
        cls.worker.set_pin('1234'); cls.worker.save()
        cls.worker.user_permissions.add(Permission.objects.get(codename='view_venuetable'))
        cls.owner = User.objects.create_user(username='owner3d', role='PROPIETARIO', password=PASSWORD)

    def setUp(self):
        self.client.post('/gerencia/acceso/', {'username': self.manager.username, 'password': PASSWORD})

    def url(self, name, *args):
        return reverse('management:' + name, args=args)

    def revoke(self, code):
        self.manager.user_permissions.remove(Permission.objects.get(codename=code))
        self.manager = User.objects.get(pk=self.manager.pk)

    def product_data(self, **extra):
        return {'name': 'Gallo', 'slug': 'gallo', 'category': self.category.pk, 'last_unit_cost': '12', 'base_price': '25',
                'minimum_stock': 6, 'preparation_route': 'NONE', 'track_inventory': 'on', 'is_active': 'on',
                'visible_in_pos': 'on', **extra}


class InventoryInterfaceTests(AdministrationCase):
    def test_inventory_states_search_and_filters(self):
        Product.objects.create(name='Agua', slug='agua', category=self.category, track_inventory=True)
        Product.objects.create(name='Servicio', slug='servicio', category=self.category)
        Product.objects.create(name='Disponible', slug='disponible', category=self.category, track_inventory=True, stock_quantity=10)
        page = self.client.get(self.url('inventory'))
        for label in ('Stock bajo', 'Agotado', 'No necesita conteo', 'Disponible'):
            self.assertContains(page, label)
        for state, name in [('low', 'Gallo'), ('out', 'Agua'), ('untracked', 'Servicio')]:
            response = self.client.get(self.url('inventory'), {'state': state})
            self.assertEqual([p.name for p in response.context['rows']], [name])
        self.assertEqual(self.client.get(self.url('inventory'), {'q': 'gall'}).context['rows'].paginator.count, 1)
        self.assertEqual(self.client.get(self.url('inventory'), {'category': 99999}).context['rows'].paginator.count, 0)
        self.assertEqual(page.context['attention'][0].name, 'Agua')

    def test_inventory_requires_session_and_permission(self):
        self.assertEqual(Client().get(self.url('inventory')).status_code, 302)
        self.revoke('view_inventory')
        for path in [self.url('inventory'), self.url('product', self.product.pk), self.url('inventory-movements'), self.url('categories')]:
            self.assertEqual(self.client.get(path).status_code, 403)

    def test_receive_and_adjust_movements_and_audit(self):
        for route, data, confirmation_route in [
            ('stock-receive', {'quantity': 24, 'reason': 'Entrega'}, 'inventory-receive'),
            ('stock-adjust', {'direction': 'minus', 'quantity': 2, 'reason': 'Rotura'}, 'inventory-count'),
            ('stock-adjust', {'direction': 'plus', 'quantity': 1, 'reason': 'Conteo'}, 'inventory-count'),
        ]:
            response = self.client.post(self.url(route, self.product.pk), data)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(self.client.post(self.url(confirmation_route), {'confirmation': response.context['review']['signed']}).status_code, 302)
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity, 27)
        self.assertEqual(InventoryMovement.objects.count(), 3)
        self.assertEqual(AuditLog.objects.filter(action__startswith='inventory.').count(), 3)
        move = InventoryMovement.objects.get(reason__endswith='Rotura')
        self.assertEqual((move.quantity_delta, move.stock_before, move.stock_after), (-2, 28, 26))

    def test_stock_validation_and_permissions(self):
        for name, data in [('stock-receive', {'quantity': 0}), ('stock-receive', {'quantity': -3}),
            ('stock-adjust', {'direction': 'minus', 'quantity': 6, 'reason': 'Rotura'}),
            ('stock-adjust', {'direction': 'minus', 'quantity': 1, 'reason': '  '})]:
            self.assertEqual(self.client.post(self.url(name, self.product.pk), data).status_code, 400)
        self.assertFalse(InventoryMovement.objects.exists())
        self.revoke('receive_inventory')
        self.assertEqual(self.client.post(self.url('stock-receive', self.product.pk), {'quantity': 1}).status_code, 403)
        self.revoke('adjust_inventory')
        self.assertEqual(self.client.post(self.url('stock-adjust', self.product.pk), {'quantity': 1}).status_code, 403)

    def test_prices_general_override_remove_and_history(self):
        url = self.url('product-price', self.product.pk)
        self.assertEqual(self.client.post(url, {'price': '30'}).status_code, 302)
        self.assertEqual(self.client.post(url, {'area': self.area.pk, 'price': '40'}).status_code, 302)
        self.assertEqual(self.client.post(url, {'area': self.area.pk, 'price': '45'}).status_code, 302)
        self.assertEqual(self.client.post(url, {'area': self.area.pk, 'use_base': 'on'}).status_code, 302)
        self.assertFalse(ProductAreaPrice.objects.exists())
        self.assertEqual(self.product.price_history.count(), 4)
        self.assertEqual(self.product.price_history.first().new_price, 30)
        self.assertTrue(AuditLog.objects.filter(action='catalog.area_price_removed').exists())
        self.assertContains(self.client.get(self.url('product', self.product.pk)), 'Usar precio general')
        self.revoke('change_product_price')
        self.assertEqual(self.client.post(url, {'price': '90'}).status_code, 403)

    def test_create_and_edit_cannot_set_stock_or_technical_fields(self):
        data = self.product_data(name='Nuevo', slug='nuevo', stock_quantity=999, id=self.product.pk)
        response = self.client.post(self.url('product-create'), data)
        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(slug='nuevo')
        self.assertEqual(product.stock_quantity, 0)
        self.assertEqual(product.base_price, 25)
        self.assertEqual(product.price_history.count(), 1)
        data = self.product_data(stock_quantity=888, base_price='35')
        self.assertEqual(self.client.post(self.url('product-edit', self.product.pk), data).status_code, 302)
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity, 4)
        self.assertEqual(self.product.base_price, 35)
        self.assertEqual(self.product.price_history.count(), 1)

    def test_product_activation_and_price_permission_not_bypassed(self):
        data = self.product_data(); data.pop('is_active')
        self.assertEqual(self.client.post(self.url('product-edit', self.product.pk), data).status_code, 302)
        self.product.refresh_from_db(); self.assertFalse(self.product.is_active)
        self.revoke('change_product_price')
        self.assertEqual(self.client.post(self.url('product-edit', self.product.pk), self.product_data(base_price=900)).status_code, 302)
        self.product.refresh_from_db(); self.assertEqual(self.product.base_price, 25); self.assertTrue(self.product.is_active)

    def test_product_invalid_image_rejected(self):
        data = self.product_data(name='Image', slug='image', image=SimpleUploadedFile('fake.png', b'not an image', content_type='image/png'))
        self.assertEqual(self.client.post(self.url('product-create'), data).status_code, 400)
        self.assertFalse(Product.objects.filter(slug='image').exists())

    def test_category_management_no_delete(self):
        self.assertEqual(self.client.post(self.url('category-create'), {'name': 'Snacks', 'slug': 'snacks', 'sort_order': 9, 'is_active': 'on'}).status_code, 302)
        row = Category.objects.get(slug='snacks'); self.assertEqual(row.sort_order, 9)
        self.assertEqual(self.client.post(self.url('category-edit', self.category.pk), {'name': 'Bebidas', 'slug': 'cervezas', 'sort_order': 2}).status_code, 302)
        self.category.refresh_from_db(); self.assertFalse(self.category.is_active)
        self.assertEqual(self.client.post(f'/gerencia/inventario/categorias/{self.category.pk}/eliminar/').status_code, 404)
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())

    def test_modifiers_options_validations_and_scope(self):
        url = self.url('group-create', self.product.pk)
        data = {'name': 'Extras', 'selection_type': 'MULTIPLE', 'min_selections': 0, 'max_selections': 2, 'sort_order': 0, 'is_active': 'on'}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        group = ModifierGroup.objects.get()
        url = self.url('option-create', self.product.pk, group.pk)
        self.assertEqual(self.client.post(url, {'name': 'Queso', 'price_delta': 10, 'sort_order': 0, 'is_active': 'on'}).status_code, 302)
        self.assertEqual(ModifierOption.objects.get().price_delta, 10)
        self.assertEqual(self.client.post(url, {'name': 'Mal', 'price_delta': -1, 'sort_order': 0}).status_code, 400)
        self.assertEqual(self.client.post(self.url('group-edit', self.product.pk, group.pk), {**data, 'selection_type': 'SINGLE'}).status_code, 400)
        other = Product.objects.create(name='Otro', slug='otro', category=self.category)
        self.assertEqual(self.client.get(self.url('group-edit', other.pk, group.pk)).status_code, 404)

    def test_combo_no_nested_self_and_availability(self):
        combo = Product.objects.create(name='Combo', slug='combo', category=self.category, is_combo=True)
        url = self.url('component-create', combo.pk)
        self.assertEqual(self.client.post(url, {'component': self.product.pk, 'quantity': 2, 'sort_order': 0}).status_code, 302)
        self.assertEqual(prices.get_combo_max_available(prices.catalog_products().get(pk=combo.pk)), 2)
        self.assertContains(self.client.get(self.url('product', combo.pk)), 'Máximo disponible: 2')
        self.assertEqual(self.client.post(url, {'component': combo.pk, 'quantity': 1, 'sort_order': 0}).status_code, 400)
        nested = Product.objects.create(name='Nested', slug='nested', category=self.category, is_combo=True)
        self.assertEqual(self.client.post(url, {'component': nested.pk, 'quantity': 1, 'sort_order': 0}).status_code, 400)
        row = ComboComponent.objects.get()
        self.assertEqual(self.client.get(self.url('component-remove', combo.pk, row.pk)).status_code, 405)
        self.assertEqual(self.client.post(self.url('component-remove', combo.pk, row.pk)).status_code, 302)

    def test_readonly_movements_filters(self):
        receive_stock(self.product, 1, user=self.manager, reason='Compra')
        response = self.client.get(self.url('inventory-movements'), {'product': self.product.pk, 'type': 'RECEIPT'})
        self.assertEqual(response.context['rows'].paginator.count, 1)
        self.assertContains(response, 'Compra')
        self.assertEqual(self.client.post(self.url('inventory-movements'), {}).status_code, 405)

    def test_no_n_plus_one_inventory(self):
        with CaptureQueriesContext(connection) as small:
            self.client.get(self.url('inventory'))
        for i in range(15):
            category = Category.objects.create(name=f'C{i}', slug=f'c{i}')
            Product.objects.create(name=f'P{i}', slug=f'p{i}', category=category)
        with CaptureQueriesContext(connection) as large:
            self.client.get(self.url('inventory'))
        self.assertLessEqual(len(large), len(small) + 1)


class UserInterfaceTests(AdministrationCase):
    def test_list_filters_search_and_no_secrets(self):
        response = self.client.get(self.url('users'), {'q': 'Méndez'})
        self.assertEqual([u.pk for u in response.context['rows']], [self.worker.pk])
        self.assertContains(response, 'Configurado')
        self.assertNotContains(response, self.worker.pin_hash)
        self.assertNotContains(response, self.manager.password)
        self.assertEqual(self.client.get(self.url('users'), {'role': 'MESERO'}).context['rows'].paginator.count, 1)
        self.worker.is_active = False; self.worker.save()
        self.assertEqual(self.client.get(self.url('users'), {'role': 'inactive'}).context['rows'].paginator.count, 1)
        self.revoke('view_user'); self.assertEqual(self.client.get(self.url('users')).status_code, 403)

    def test_create_daily_roles_hashes_credentials_and_applies_role_permissions(self):
        for role in ('GERENTE', 'CAJERO', 'PROPIETARIO'):
            with self.subTest(role=role):
                value = PASSWORD if role in ('GERENTE', 'PROPIETARIO') else '0523'
                response = self.client.post(self.url('user-create'), {'username': 'new_' + role, 'first_name': 'Nueva',
                    'role': role, 'is_active': 'on', 'password': value if role in ('GERENTE', 'PROPIETARIO') else '',
                    'pin': value if role not in ('GERENTE', 'PROPIETARIO') else '', 'confirm': value,
                    'is_staff': 'on', 'is_superuser': 'on'})
                self.assertEqual(response.status_code, 302)
                row = User.objects.get(username='new_' + role)
                self.assertFalse(row.is_staff); self.assertFalse(row.is_superuser)
                self.assertEqual(users.codes(row), permissions.suggested(role))
                self.assertTrue(row.check_password(value) if role in ('GERENTE', 'PROPIETARIO') else row.check_pin(value))
                self.assertNotIn(value, json.dumps(list(AuditLog.objects.filter(entity_id=str(row.pk), entity='accounts.user').values('data'))))

    def test_create_validates_credentials_and_unique_name(self):
        for data in [dict(role='MESERO', pin='12', confirm='12'), dict(role='MESERO', pin='1234567', confirm='1234567'),
                     dict(role='GERENTE', password='12345678', confirm='12345678'), dict(role='GUARDIA', pin='1234', confirm='1111')]:
            self.assertEqual(self.client.post(self.url('user-create'), {'username': 'invalid', 'is_active': 'on', **data}).status_code, 400)
        self.assertFalse(User.objects.filter(username='invalid').exists())

    def test_creation_form_offers_waiter_area_and_hides_guard(self):
        response = self.client.get(self.url('user-create'), {'role': 'CAJERO'})
        self.assertContains(response, 'Cajero')
        self.assertContains(response, 'Mesero')
        self.assertContains(response, 'Área del mesero')
        self.assertContains(response, 'El cajero es la persona')
        self.assertNotContains(response, '<option value="GUARDIA"')

    def test_create_waiter_with_area_and_show_it_in_users(self):
        response = self.client.post(self.url('user-create'), {'username': 'luis.disco', 'first_name': 'Luis',
            'role': 'MESERO', 'work_area': self.area.pk, 'is_active': 'on', 'pin': '1470', 'confirm': '1470'})
        self.assertEqual(response.status_code, 302)
        waiter = User.objects.get(username='luis.disco')
        self.assertEqual(waiter.work_area, self.area)
        self.assertContains(self.client.get(self.url('users'), {'role': 'MESERO'}), self.area.name)
        self.assertContains(self.client.get(self.url('user', waiter.pk)), 'Área asignada')

    def test_reset_pin_hash_secret_free_and_post_only(self):
        url = self.url('user-pin', self.worker.pk)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url, {'value': '543210', 'confirm': '543210'}).status_code, 302)
        self.worker.refresh_from_db(); self.assertTrue(self.worker.check_pin('543210')); self.assertFalse(self.worker.check_pin('1234'))
        log = AuditLog.objects.get(action='accounts.pin_reset')
        self.assertEqual(log.data, {}); self.assertEqual(log.entity_id, str(self.worker.pk)); self.assertEqual(log.user_id, self.manager.pk)
        page = self.client.get(self.url('user', self.worker.pk)); self.assertNotContains(page, self.worker.pin_hash); self.assertNotContains(page, '543210')
        self.revoke('reset_user_pin'); self.assertEqual(self.client.post(url, {'value': '2222', 'confirm': '2222'}).status_code, 403)

    def test_password_validation_reset_and_session_invalidation(self):
        url = self.url('user-password', self.owner.pk)
        self.assertEqual(self.client.post(url, {'value': '123', 'confirm': '123'}).status_code, 400)
        client = Client(); client.post('/gerencia/acceso/', {'username': self.owner.username, 'password': PASSWORD})
        new = 'Another-strong-password-980!'
        self.assertEqual(self.client.post(url, {'value': new, 'confirm': new}).status_code, 302)
        self.owner.refresh_from_db(); self.assertTrue(self.owner.check_password(new))
        self.assertEqual(AuditLog.objects.get(action='accounts.password_reset').data, {})
        self.assertEqual(client.get('/gerencia/').status_code, 302)
        self.revoke('change_user_credentials'); self.assertEqual(self.client.post(url, {'value': new, 'confirm': new}).status_code, 403)

    def test_pin_reset_does_not_end_management_session(self):
        self.assertEqual(self.client.post(self.url('user-pin', self.manager.pk), {'value': '3333', 'confirm': '3333'}).status_code, 302)
        self.assertEqual(self.client.get('/gerencia/').status_code, 200)

    def test_role_change_preserves_permissions_and_audits(self):
        before = users.codes(self.worker)
        response = self.client.post(self.url('user-edit', self.worker.pk), {'username': self.worker.username,
            'first_name': 'Carlos', 'last_name': 'Méndez', 'role': 'CAJERO', 'work_area': self.area.pk,
            'revision': users.revision(self.worker)})
        self.assertEqual(response.status_code, 302)
        self.worker.refresh_from_db(); self.assertEqual(self.worker.role, 'CAJERO'); self.assertIsNone(self.worker.work_area)
        self.assertEqual(users.codes(self.worker), before)
        self.assertTrue(AuditLog.objects.filter(action='accounts.role_changed').exists())

    def test_guard_role_requires_explicit_incompatible_permission_removal(self):
        with self.assertRaises(ValidationError):
            users.save_user({'role': 'GUARDIA'}, actor=self.manager, pk=self.worker.pk)
        self.worker.user_permissions.clear()
        users.save_user({'role': 'GUARDIA'}, actor=self.manager, pk=self.worker.pk)
        self.worker.refresh_from_db()
        page = self.client.get(self.url('user-permissions', self.worker.pk))
        self.assertContains(page, 'Escanear entrada'); self.assertNotContains(page, 'value="inventory.view_inventory"')
        with self.assertRaises(ValidationError):
            users.update_permissions(self.worker.pk, ['inventory.view_inventory'], actor=self.manager, expected=users.revision(self.worker))

    def test_permissions_add_remove_whitelist_and_audit(self):
        url = self.url('user-permissions', self.worker.pk)
        response = self.client.post(url, {'revision': users.revision(self.worker), 'permission': ['orders.send_order', 'tables.view_venuetable']})
        self.assertEqual(response.status_code, 302)
        self.worker.refresh_from_db(); self.assertIn('orders.send_order', users.codes(self.worker))
        self.assertEqual(self.client.post(url, {'revision': users.revision(self.worker), 'permission': []}).status_code, 302)
        self.assertEqual(users.codes(self.worker), set())
        self.assertTrue(AuditLog.objects.filter(action='accounts.permission_added').exists())
        self.assertTrue(AuditLog.objects.filter(action='accounts.permission_removed').exists())
        self.assertEqual(self.client.post(url, {'revision': users.revision(self.worker), 'permission': ['auth.add_permission']}).status_code, 409)
        self.assertEqual(set(permissions.permission_map()), permissions.whitelist())

    def test_stale_permission_edit_conflicts(self):
        before = users.revision(self.worker)
        users.update_permissions(self.worker.pk, ['orders.send_order'], actor=self.manager, expected=before)
        with self.assertRaises(ValidationError):
            users.update_permissions(self.worker.pk, [], actor=self.manager, expected=before)
        self.assertEqual(users.codes(self.worker), {'orders.send_order'})

    def test_preset_requires_confirmation_and_is_additive(self):
        url = self.url('user-permissions', self.worker.pk)
        self.assertEqual(self.client.post(url, {'action': 'preset', 'revision': users.revision(self.worker)}).status_code, 409)
        page = self.client.get(url)
        self.assertEqual(self.client.post(url, {'action': 'preset', 'revision': page.context['revision'],
            'confirmation': page.context['preset_confirmation'], 'confirmed': 'yes'}).status_code, 302)
        self.assertTrue(permissions.suggested('MESERO').issubset(users.codes(self.worker)))
        self.assertTrue(AuditLog.objects.filter(action='accounts.preset_applied').exists())

    def test_no_privilege_escalation_or_technical_account_takeover(self):
        limited = User.objects.create_user(username='limited', role='GERENTE')
        limited.user_permissions.add(*Permission.objects.filter(codename__in=['manage_user_permissions', 'reset_user_pin', 'change_user', 'change_user_role']))
        fresh = User.objects.create_user(username='fresh', role='MESERO')
        with self.assertRaises(PermissionDenied):
            users.update_permissions(fresh.pk, ['inventory.adjust_inventory'], actor=limited, expected=users.revision(fresh))
        with self.assertRaises(PermissionDenied):
            users.reset_credential(self.manager.pk, '4321', actor=limited, kind='pin')
        technical = User.objects.create_superuser(username='technical', password=PASSWORD)
        with self.assertRaises(PermissionDenied):
            users.save_user({'username': 'takeover'}, actor=self.manager, pk=technical.pk)

    def test_deactivate_confirmation_preserves_history_and_last_owner_protected(self):
        url = self.url('user-state', self.worker.pk)
        self.assertEqual(self.client.post(url).status_code, 409)
        data = self.client.get(self.url('user', self.worker.pk)).context
        self.assertEqual(self.client.post(url, {'confirmation': data['state_confirmation'], 'confirmed': 'yes'}).status_code, 302)
        self.worker.refresh_from_db(); self.assertFalse(self.worker.is_active)
        self.assertTrue(AuditLog.objects.filter(action='accounts.deactivated').exists())
        for changes in ({'is_active': False}, {'role': 'GERENTE'}):
            with self.assertRaises(ValidationError):
                users.save_user(changes, actor=self.manager, pk=self.owner.pk)
        self.owner.refresh_from_db(); self.assertTrue(self.owner.is_active)

    def test_csrf_mutations_and_no_get_effects(self):
        client = Client(enforce_csrf_checks=True)
        for url in [self.url('user-pin', self.worker.pk), self.url('user-password', self.worker.pk),
                    self.url('user-state', self.worker.pk), self.url('user-permissions', self.worker.pk),
                    self.url('stock-receive', self.product.pk)]:
            self.assertEqual(client.post(url, {}).status_code, 403)
        for name in ('user-pin', 'user-password', 'user-state'):
            self.assertEqual(self.client.get(self.url(name, self.worker.pk)).status_code, 405)

    def test_role_change_needs_explicit_permission(self):
        self.revoke('change_user_role')
        with self.assertRaises(PermissionDenied):
            users.save_user({'role': 'CAJERO'}, actor=self.manager, pk=self.worker.pk)

    def test_inactive_privileged_account_cannot_be_taken_over(self):
        limited = User.objects.create_user(username='limited-reset', role='GERENTE')
        limited.user_permissions.add(*Permission.objects.filter(codename__in=['reset_user_pin', 'activate_user']))
        self.manager.is_active = False; self.manager.save()
        with self.assertRaises(PermissionDenied):
            users.reset_credential(self.manager.pk, '6543', actor=limited, kind='pin')
        with self.assertRaises(PermissionDenied):
            users.save_user({'is_active': True}, actor=limited, pk=self.manager.pk)

    def test_username_case_collision_rejected(self):
        with self.assertRaises(ValidationError):
            users.save_user({'username': self.worker.username.upper(), 'role': 'MESERO', 'pin': '9516'}, actor=self.manager)

    def test_credential_errors_do_not_echo_secret_or_duplicate_ids(self):
        page = self.client.post(self.url('user-pin', self.worker.pk), {'value': '734925', 'confirm': '654321'})
        self.assertEqual(page.status_code, 400)
        self.assertNotContains(page, '734925', status_code=400)
        self.assertNotContains(page, '654321', status_code=400)
        self.assertContains(page, 'id="pin_id_value"', status_code=400)
        self.assertContains(page, 'id="password_id_value"', status_code=400)

    def test_permission_edit_preserves_permissions_outside_whitelist(self):
        technical = Permission.objects.get(content_type__app_label='auth', codename='view_group')
        self.worker.user_permissions.add(technical)
        users.update_permissions(self.worker.pk, ['orders.send_order'], actor=self.manager, expected=users.revision(self.worker))
        self.assertEqual(users.codes(self.worker), {'orders.send_order', 'auth.view_group'})

    def test_activation_does_not_require_identity_edit_permission(self):
        self.revoke('change_user')
        target = users.save_user({'is_active': False}, actor=self.manager, pk=self.worker.pk)
        self.assertFalse(target.is_active)

    def test_users_and_permissions_no_n_plus_one(self):
        with CaptureQueriesContext(connection) as small:
            self.client.get(self.url('users'))
        User.objects.bulk_create([User(username=f'list{i}', role='MESERO') for i in range(15)])
        with CaptureQueriesContext(connection) as large:
            self.client.get(self.url('users'))
        self.assertLessEqual(len(large), len(small) + 1)
        with CaptureQueriesContext(connection) as queries:
            self.client.get(self.url('user-permissions', self.worker.pk))
        self.assertLess(len(queries), 25)


class OperationalCredentialTests(AdministrationCase):
    def waiter_client(self):
        from django.http import HttpResponse
        device = OperationalDevice.objects.create(name='Tablet', code='tablet-3d', area=self.area)
        response = HttpResponse(); security.set_device_cookie(response, device)
        client = Client(); client.cookies.update(response.cookies)
        self.assertEqual(client.post('/operacion/acceso/', {'user_id': self.worker.pk, 'pin': '1234'}, HTTP_ACCEPT='application/json').status_code, 200)
        return client

    def cash_client(self):
        from django.http import HttpResponse
        self.worker.role = 'CAJERO'; self.worker.save()
        self.worker.user_permissions.add(Permission.objects.get(codename='open_cash_session'))
        register = CashRegister.objects.create(name='Caja', code='CAJA3D', area=self.area)
        response = HttpResponse(); cash_security.set_register(response, register)
        client = Client(); client.cookies.update(response.cookies)
        self.assertEqual(client.post('/caja/acceso/', {'user_id': self.worker.pk, 'pin': '1234'}, HTTP_ACCEPT='application/json').status_code, 200)
        return client

    def test_waiter_reset_old_pin_fails_new_pin_works_and_old_session_rejected(self):
        client = self.waiter_client()
        users.reset_credential(self.worker.pk, '5678', actor=self.manager, kind='pin')
        self.assertFalse(OperationalSession.objects.filter(user=self.worker, revoked_at__isnull=True).exists())
        self.assertEqual(client.get('/operacion/').status_code, 302)
        self.assertEqual(client.post('/operacion/acceso/', {'user_id': self.worker.pk, 'pin': '1234'}, HTTP_ACCEPT='application/json').status_code, 400)
        self.assertEqual(client.post('/operacion/acceso/', {'user_id': self.worker.pk, 'pin': '5678'}, HTTP_ACCEPT='application/json').status_code, 200)

    def test_waiter_deactivation_blocks_existing_and_new_access(self):
        client = self.waiter_client()
        users.save_user({'is_active': False}, actor=self.manager, pk=self.worker.pk)
        self.assertEqual(client.get('/operacion/').status_code, 302)
        self.assertEqual(client.post('/operacion/acceso/', {'user_id': self.worker.pk, 'pin': '1234'}, HTTP_ACCEPT='application/json').status_code, 403)
        self.assertTrue(OperationalSession.objects.filter(user=self.worker).exists())
        self.assertNotIn(self.worker.pk, [u['id'] for u in security.visible_waiters()])

    def test_cash_reset_invalidates_cookie_and_old_pin(self):
        client = self.cash_client()
        users.reset_credential(self.worker.pk, '5678', actor=self.manager, kind='pin')
        self.assertFalse(CashAccessSession.objects.filter(user=self.worker, revoked_at__isnull=True).exists())
        self.assertEqual(client.get('/caja/').status_code, 302)
        self.assertEqual(client.post('/caja/acceso/', {'user_id': self.worker.pk, 'pin': '1234'}, HTTP_ACCEPT='application/json').status_code, 400)
        self.assertEqual(client.post('/caja/acceso/', {'user_id': self.worker.pk, 'pin': '5678'}, HTTP_ACCEPT='application/json').status_code, 200)

    def test_cash_deactivation_blocks_cookie_and_login(self):
        client = self.cash_client()
        users.save_user({'is_active': False}, actor=self.manager, pk=self.worker.pk)
        self.assertEqual(client.get('/caja/').status_code, 302)
        self.assertEqual(client.post('/caja/acceso/', {'user_id': self.worker.pk, 'pin': '1234'}, HTTP_ACCEPT='application/json').status_code, 403)

    def guard_client(self):
        self.worker.role = 'GUARDIA'; self.worker.save()
        self.worker.user_permissions.set([Permission.objects.get(codename='scan_event_ticket')])
        client = Client()
        self.assertEqual(client.post('/acceso/ingresar/', {'username': self.worker.username, 'pin': '1234'}).status_code, 302)
        self.assertEqual(client.get('/acceso/').status_code, 200)
        return client

    def test_guard_reset_invalidates_session_and_dev_hidden(self):
        client = self.guard_client()
        with override_settings(DEBUG=False):
            page = client.get('/acceso/')
            for text in ('Prueba de desarrollo', 'dev-token', 'dev-qr-image'):
                self.assertNotContains(page, text)
        users.reset_credential(self.worker.pk, '5678', actor=self.manager, kind='pin')
        self.assertEqual(client.get('/acceso/').status_code, 302)
        client.post('/acceso/ingresar/', {'username': self.worker.username, 'pin': '1234'})
        self.assertEqual(client.get('/acceso/').status_code, 302)
        client.post('/acceso/ingresar/', {'username': self.worker.username, 'pin': '5678'})
        self.assertEqual(client.get('/acceso/').status_code, 200)

    def test_inactive_user_rejected_even_without_explicit_session_revocation(self):
        client = self.waiter_client()
        User.objects.filter(pk=self.worker.pk).update(is_active=False)
        self.assertEqual(client.get('/operacion/').status_code, 302)
        self.assertFalse(OperationalSession.objects.filter(user=self.worker, revoked_at__isnull=True).exists())

    def test_guard_deactivation_blocks_existing_and_new_login(self):
        client = self.guard_client()
        users.save_user({'is_active': False}, actor=self.manager, pk=self.worker.pk)
        self.assertEqual(client.get('/acceso/').status_code, 302)
        client.post('/acceso/ingresar/', {'username': self.worker.username, 'pin': '1234'})
        self.assertEqual(client.get('/acceso/').status_code, 302)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class UserConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.actor = User.objects.create_superuser(username='concurrency-admin', password=PASSWORD, role='GERENTE')
        self.one = User.objects.create_user(username='owner-one', password=PASSWORD, role='PROPIETARIO')
        self.two = User.objects.create_user(username='owner-two', password=PASSWORD, role='PROPIETARIO')

    def run_thread(self, fn):
        connections.close_all()
        try:
            fn(User.objects.get(pk=self.actor.pk))
            return 'ok'
        except ValidationError:
            return 'conflict'
        finally:
            connections.close_all()

    def test_two_concurrent_owner_deactivations_leave_one_active(self):
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(self.run_thread, lambda actor, pk=pk: users.save_user({'is_active': False}, actor=actor, pk=pk)) for pk in (self.one.pk, self.two.pk)]
            results = [f.result(timeout=15) for f in futures]
        self.assertCountEqual(results, ['ok', 'conflict'])
        self.assertEqual(User.objects.filter(role='PROPIETARIO', is_active=True).count(), 1)

    def test_concurrent_permission_edits_do_not_silently_overwrite(self):
        self.one.role = 'GERENTE'
        self.one.save(update_fields=['role'])
        expected = users.revision(self.one)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(self.run_thread, lambda actor, code=code: users.update_permissions(self.one.pk, [code], actor=actor, expected=expected))
                       for code in ('inventory.view_inventory', 'events.scan_event_ticket')]
            results = [f.result(timeout=15) for f in futures]
        self.assertCountEqual(results, ['ok', 'conflict'])
        self.assertEqual(self.one.user_permissions.count(), 1)

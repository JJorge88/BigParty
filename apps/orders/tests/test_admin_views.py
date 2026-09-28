from importlib import reload

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, override_settings
from django.urls import Resolver404, clear_url_caches, resolve, reverse

from apps.orders import services as s
from apps.orders.models import (TableOrder, OrderLine, SubAccount, PreparationTicket,
                               PreparationTicketItem, OrderActivity, OrderTableLink, OrderLineComponent)
from .base import OrdersTestCase


class OrderAdminTests(OrdersTestCase):
    def test_operational_admin_is_readonly_even_for_superuser(self):
        order = self.open(split=True)
        subaccount = s.create_subaccount(order, "Jorge", self.user)
        line = s.add_product_to_order(order, self.product, 1, self.user, subaccount=subaccount)
        ticket = s.send_order(order, self.user)
        self.client.force_login(self.user)
        objects = [order, subaccount, line, ticket, ticket.items.get(), order.activities.first(),
                   order.table_links.get(), line.components.get()]
        for obj in objects:
            model = type(obj)
            self.assertIn(model, admin.site._registry)
            name = f"admin:orders_{model._meta.model_name}"
            with self.subTest(model=model):
                self.assertEqual(self.client.get(reverse(name + "_changelist")).status_code, 200)
                self.assertEqual(self.client.get(reverse(name + "_change", args=[obj.pk])).status_code, 200)
                self.assertEqual(self.client.post(reverse(name + "_change", args=[obj.pk]), {}).status_code, 403)
                self.assertEqual(self.client.get(reverse(name + "_add")).status_code, 403)
                self.assertEqual(self.client.post(reverse(name + "_delete", args=[obj.pk]), {"post": "yes"}).status_code, 403)


@override_settings(DEBUG=True, ROOT_URLCONF="config.urls")
class OrderDevViewTests(OrdersTestCase):
    def setUp(self):
        import config.urls
        reload(config.urls)
        clear_url_caches()

    def tearDown(self):
        import config.urls
        with override_settings(DEBUG=False):
            reload(config.urls)
        clear_url_caches()

    def test_anonymous_redirect_and_staff_permission_checks(self):
        response = self.client.get("/dev/ordenes/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response.url)
        user = get_user_model().objects.create_user(username="limited", is_staff=True)
        self.client.force_login(user)
        with self.assertLogs("django.request", level="WARNING"):
            self.assertEqual(self.client.get("/dev/ordenes/").status_code, 403)

    def test_complete_dev_flow_open_subaccount_add_send_and_timeline(self):
        self.client.force_login(self.user)
        response = self.client.post("/dev/ordenes/", {"action": "open", "table": self.table.pk, "billing_mode": "SPLIT"})
        self.assertEqual(response.status_code, 302)
        order = TableOrder.objects.get()
        response = self.client.post("/dev/ordenes/", {"action": "subaccount", "order": order.pk, "name": "Jorge"})
        self.assertEqual(response.status_code, 302)
        account = order.subaccounts.get()
        response = self.client.post("/dev/ordenes/", {"action": "add", "order": order.pk,
            "product": self.product.pk, "quantity": 2, "subaccount": account.pk, "unit_price": "0.01"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(order.lines.get().unit_price, 25)
        response = self.client.post("/dev/ordenes/", {"action": "send", "order": order.pk})
        self.assertEqual(response.status_code, 302)
        response = self.client.get("/dev/ordenes/", {"order": order.pk})
        for text in ("Jorge", "Cerveza", "Historial operativo", "Pedido enviado", "Comandas lógicas"):
            self.assertContains(response, text)

    def test_view_permission_alone_does_not_allow_opening(self):
        user = get_user_model().objects.create_user(username="viewer", is_staff=True)
        user.user_permissions.add(Permission.objects.get(codename="view_tableorder"))
        self.client.force_login(user)
        response = self.client.get("/dev/ordenes/")
        self.assertNotContains(response, "Abrir mesa")
        with self.assertLogs("django.request", level="WARNING"):
            response = self.client.post("/dev/ordenes/", {"action": "open", "table": self.table.pk, "billing_mode": "SINGLE"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(TableOrder.objects.count(), 0)

    def test_post_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        with self.assertLogs("django.security.csrf", level="WARNING"):
            response = client.post("/dev/ordenes/", {"action": "open", "table": self.table.pk, "billing_mode": "SINGLE"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(TableOrder.objects.count(), 0)

    def test_validation_error_is_displayed_without_writing(self):
        self.open()
        self.client.force_login(self.user)
        with self.assertLogs("django.request", level="WARNING"):
            response = self.client.post("/dev/ordenes/", {"action": "open", "table": self.table.pk, "billing_mode": "SINGLE"})
        self.assertContains(response, "La mesa ya tiene una cuenta activa.", status_code=400)
        self.assertEqual(TableOrder.objects.count(), 1)

    def test_no_route_in_production_and_view_guard(self):
        import config.urls
        self.client.force_login(self.user)
        try:
            with override_settings(DEBUG=False):
                self.assertEqual(self.client.get("/dev/ordenes/").status_code, 404)
                reload(config.urls)
                clear_url_caches()
                with self.assertRaises(Resolver404):
                    resolve("/dev/ordenes/")
        finally:
            reload(config.urls)
            clear_url_caches()

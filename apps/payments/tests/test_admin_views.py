import importlib
from decimal import Decimal as D

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, RequestFactory, override_settings
from django.urls import resolve, Resolver404, clear_url_caches

from apps.payments.models import Payment, PaymentAllocation, OrderAdjustment, AdjustmentAllocation, PaymentRefund, RefundAllocation
from apps.payments.views import PaymentsDevelopmentView
from apps.payments import services as s
from apps.orders import services as orders
from .base import PaymentsTestCase


@override_settings(DEBUG=True)
class PaymentAdminViewTests(PaymentsTestCase):
    def setUp(self):
        import config.urls
        importlib.reload(config.urls)
        clear_url_caches()

    def tearDown(self):
        import config.urls
        with override_settings(DEBUG=False):
            importlib.reload(config.urls)
        clear_url_caches()

    def test_all_financial_models_are_read_only_even_for_superuser(self):
        request = RequestFactory().get("/admin/")
        request.user = self.user
        for model in (Payment, PaymentAllocation, OrderAdjustment, AdjustmentAllocation, PaymentRefund, RefundAllocation):
            model_admin = admin.site._registry[model]
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))
            self.assertEqual(set(model_admin.get_readonly_fields(request)), {f.name for f in model._meta.fields})

    def test_dev_full_payment_ignores_frontend_total_and_can_close(self):
        order, _, _ = self.consumption(2)
        self.client.force_login(self.user)
        response = self.client.post("/dev/pagos/", {"action": "pay", "order": order.pk, "mode": "full", "amount": "1", "method": "CASH", "received_amount": "100"})
        self.assertEqual(response.status_code, 302)
        payment = Payment.objects.get()
        self.assertEqual(payment.amount, D("50"))
        self.assertEqual(payment.change_due, D("50"))
        response = self.client.get(response.url)
        self.assertContains(response, "Disponible para cobrar")
        self.assertEqual(self.client.post("/dev/pagos/", {"action": "close", "order": order.pk}).status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, "CLOSED")

    def test_dev_partial_and_transfer_confirmation(self):
        order, _, _ = self.consumption(2)
        self.client.force_login(self.user)
        response = self.client.post("/dev/pagos/", {"action": "pay", "order": order.pk, "mode": "amount", "amount": "20", "method": "CASH"})
        self.assertEqual(response.status_code, 302)
        response = self.client.post("/dev/pagos/", {"action": "pay", "order": order.pk, "mode": "full", "method": "TRANSFER", "reference": "REF"})
        self.assertEqual(response.status_code, 302)
        payment = Payment.objects.get(status="PENDING")
        self.assertEqual(payment.amount, D("30"))
        self.assertEqual(self.client.post("/dev/pagos/", {"action": "confirm", "payment": payment.pk}).status_code, 302)
        self.assertEqual(s.get_order_balance(order), D("0"))

    def test_dev_selected_json_and_card_approval(self):
        order, _, line = self.consumption(2)
        self.client.force_login(self.user)
        data = {"action": "pay", "order": order.pk, "mode": "selected", "selection": '[{"line_id": %d, "quantity": 1}]' % line.pk, "method": "CARD"}
        self.assertEqual(self.client.post("/dev/pagos/", data).status_code, 400)
        data["card_approved"] = "on"
        self.assertEqual(self.client.post("/dev/pagos/", data).status_code, 302)
        self.assertEqual(Payment.objects.get().amount, D("25"))

    def test_dev_rejection_requires_reason(self):
        order, _, _ = self.consumption(1)
        payment = s.pay_full_balance(order, "DEPOSIT", self.user, reference="R")
        self.client.force_login(self.user)
        self.assertEqual(self.client.post("/dev/pagos/", {"action": "reject", "payment": payment.pk}).status_code, 400)
        self.assertEqual(self.client.post("/dev/pagos/", {"action": "reject", "payment": payment.pk, "reason": "No recibido"}).status_code, 302)
        payment.refresh_from_db()
        self.assertEqual(payment.status, "REJECTED")

    def test_dev_requires_login_staff_and_view_permission(self):
        self.assertEqual(self.client.get("/dev/pagos/").status_code, 302)
        user = get_user_model().objects.create_user(username="no-staff")
        self.client.force_login(user)
        self.assertEqual(self.client.get("/dev/pagos/").status_code, 403)
        user.is_staff = True
        user.save()
        self.assertEqual(self.client.get("/dev/pagos/").status_code, 403)
        user.user_permissions.add(Permission.objects.get(codename="view_payment", content_type__app_label="payments"))
        self.assertEqual(self.client.get("/dev/pagos/").status_code, 200)

    def test_view_permission_does_not_allow_mutation(self):
        order, _, _ = self.consumption(1)
        user = get_user_model().objects.create_user(username="read-only-payments", is_staff=True)
        user.user_permissions.add(Permission.objects.get(codename="view_payment", content_type__app_label="payments"))
        self.client.force_login(user)
        self.assertEqual(self.client.post("/dev/pagos/", {"action": "pay", "order": order.pk, "mode": "full", "method": "CASH"}).status_code, 403)
        self.assertFalse(Payment.objects.exists())

    def test_csrf_is_required(self):
        order, _, _ = self.consumption(1)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post("/dev/pagos/", {"action": "pay", "order": order.pk, "mode": "full", "method": "CASH"}).status_code, 403)
        self.assertFalse(Payment.objects.exists())

    def test_form_rejects_cross_order_subaccount(self):
        order, _, _ = self.consumption(1)
        other = orders.open_table_order(self.destination, self.user, billing_mode="SPLIT")
        account = orders.create_subaccount(other, "Carlos", self.user)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post("/dev/pagos/", {"action": "pay", "order": order.pk, "subaccount": account.pk, "mode": "full", "method": "CASH"}).status_code, 400)
        self.assertFalse(Payment.objects.exists())

    def test_debug_false_removes_route_and_guards_view(self):
        import config.urls
        with override_settings(DEBUG=False):
            importlib.reload(config.urls)
            clear_url_caches()
            with self.assertRaises(Resolver404):
                resolve("/dev/pagos/")
            request = RequestFactory().get("/dev/pagos/")
            request.user = self.user
            from django.http import Http404
            with self.assertRaises(Http404):
                PaymentsDevelopmentView.as_view()(request)
        importlib.reload(config.urls)
        clear_url_caches()

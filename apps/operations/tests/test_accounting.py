import json
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.test import Client
from django.utils import timezone

from apps.operations.models import OperationalSession
from apps.operations.security import DEVICE_COOKIE
from apps.orders import services as orders
from apps.orders.models import TableOrder
from apps.payments import services as payments
from apps.payments.models import Payment
from apps.payments.queries import get_financial_summary
from .base import OperationsTestCase


class AccountTestCase(OperationsTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for user in (cls.waiter, cls.second_waiter):
            user.user_permissions.add(*Permission.objects.filter(content_type__app_label="payments", codename__in=["view_payment", "record_payment", "close_order"]))

    def setUp(self):
        self.order = self.open()
        self.line = orders.add_product_to_order(self.order, self.product, 6, self.user)
        orders.send_order(self.order, self.user)
        self.enter()

    def url(self, action="", order=None):
        return f"/operacion/orden/{(order or self.order).pk}/cuenta/" + (f"{action}/" if action else "")

    def post(self, action, data=None):
        return self.client.post(self.url(action), data or {}, HTTP_ACCEPT="application/json")

    def state(self, **data):
        response = self.client.get(self.url(), data, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        return response.json()["state"]

    def quote(self, **data):
        if isinstance(data.get("selection"), list):
            data["selection"] = json.dumps(data["selection"])
        response = self.post("preparar", data)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["quote"]

    def pay(self, method="tarjeta", *, quote=None, account=None, **data):
        quote = quote or self.quote(**({"subaccount": account.pk} if account else {}))
        return self.post(method, {"token": quote["token"], **({"subaccount": account.pk} if account else {}), **data})

    def split_order(self):
        self.order = self.open(self.destination, split=True)
        first = orders.create_subaccount(self.order, "Jorge", self.user)
        second = orders.create_subaccount(self.order, "Carlos", self.user)
        self.line = orders.add_product_to_order(self.order, self.product, 2, self.user, subaccount=first)
        other_line = orders.add_product_to_order(self.order, self.product, 3, self.user, subaccount=second)
        orders.send_order(self.order, self.user)
        return first, second, other_line


class AccountPresentationTests(AccountTestCase):
    def test_page_totals_and_paid_collapsed(self):
        response = self.client.get(self.url())
        self.assertContains(response, 'id="paid-section" class="paid-section" hidden>')
        self.assertContains(response, "Ver cuenta")
        self.assertNotContains(response, "terminal POS")
        summary = self.state()["summary"]
        self.assertEqual((summary["charge_total"], summary["confirmed_paid"], summary["outstanding_balance"]), ("Q150.00", "Q0.00", "Q150.00"))

    def test_sent_only_and_draft_warning(self):
        orders.add_product_to_order(self.order, self.product, 4, self.user)
        state = self.state()
        self.assertTrue(state["has_drafts"])
        self.assertEqual(len(state["lines"]), 1)
        self.assertEqual(state["summary"]["charge_total"], "Q150.00")
        self.assertEqual(self.quote()["amount"], "150.00")

    def test_cancelled_lines_excluded(self):
        orders.cancel_sent_line(self.line, self.user, reason="Prueba")
        self.assertEqual(self.state()["lines"], [])

    def test_partial_line_quantities(self):
        payments.create_selected_payment(self.order, [{"line_id": self.line.pk, "quantity": 2}], "CARD", self.user, card_approved=True)
        line = self.state()["lines"][0]
        self.assertEqual((line["paid_quantity"], line["outstanding_quantity"], line["available_quantity"]), (2, 4, 4))
        self.assertFalse(line["settled"])

    def test_fully_paid_lines_preserved(self):
        self.pay()
        state = self.state()
        self.assertEqual(len(state["lines"]), 1)
        self.assertTrue(state["lines"][0]["settled"])
        self.assertTrue(state["can_close"])
        self.assertEqual(state["history"][0]["status_label"], "Confirmado")

    def test_adjustment_reflected_in_net_and_selection(self):
        payments.apply_order_adjustment(self.order, self.user, reason="Autorizado", amount="10")
        state = self.state()
        self.assertEqual(state["summary"]["charge_total"], "Q140.00")
        self.assertTrue(state["has_adjustments"])
        self.assertEqual(self.quote(mode="selection", selection=[{"line_id": self.line.pk, "quantity": 1}])["amount"], "15.00")

    def test_refund_reflected_without_reopening_balance(self):
        payment = payments.pay_full_balance(self.order, "CARD", self.user, card_approved=True)
        payments.refund_payment(payment, self.user, reason="Devolución", amount="25")
        state = self.state()
        self.assertEqual(state["summary"]["charge_total"], "Q125.00")
        self.assertEqual(state["summary"]["confirmed_paid"], "Q125.00")
        self.assertEqual(state["summary"]["available_to_pay"], "Q0.00")
        self.assertEqual(state["history"][0]["refunded"], "Q25.00")

    def test_rejected_transfer_restores_available(self):
        self.pay("transferencia", reference="TR-01")
        payments.reject_pending_payment(Payment.objects.get(), self.user, reason="Sin ingreso")
        state = self.state()
        self.assertEqual(state["history"][0]["status_label"], "Rechazado")
        self.assertEqual(state["summary"]["available_to_pay"], "Q150.00")


class CollectionTests(AccountTestCase):
    def test_full_card_is_confirmed_and_explicit_close(self):
        response = self.pay()
        self.assertEqual(response.status_code, 200)
        payment = Payment.objects.get()
        self.assertEqual(payment.amount, 150)
        self.assertEqual(payment.status, "CONFIRMED")
        self.assertEqual(payment.recorded_by, self.waiter)
        self.order.refresh_from_db()
        self.assertNotEqual(self.order.status, "CLOSED")
        self.assertTrue(response.json()["state"]["can_close"])

    def test_selected_cash_received_change_handoff(self):
        quote = self.quote(mode="selection", selection=[{"line_id": self.line.pk, "quantity": 2}])
        response = self.pay("efectivo", quote=quote, received="100", cash_session="999", amount="0.01", user_id=self.user.pk)
        self.assertEqual(response.status_code, 200)
        payment = Payment.objects.get()
        self.assertEqual(payment.amount, 50)
        self.assertEqual(payment.change_due, 50)
        self.assertEqual(payment.cash_handoff_status, "PENDING")
        self.assertEqual(payment.cash_handoff.status, "PENDING")
        self.assertFalse(payment.cash_movements.exists())
        self.assertEqual(payment.recorded_by, self.waiter)
        self.assertEqual(payment.change_due, Decimal(response.json()["payment"]["change"].replace("Q", "")))
        self.order.refresh_from_db()
        self.assertEqual(self.order.billing_mode, "SINGLE")

    def test_cash_insufficient_does_not_write(self):
        self.assertEqual(self.pay("efectivo", received="149.99").status_code, 409)
        self.assertFalse(Payment.objects.exists())

    def test_cash_received_required(self):
        self.assertEqual(self.pay("efectivo").status_code, 409)
        self.assertFalse(Payment.objects.exists())

    def test_cash_invalid_decimal_rejected(self):
        self.assertEqual(self.pay("efectivo", received="NaN").status_code, 409)
        self.assertFalse(Payment.objects.exists())

    def test_selection_over_quantity_rejected(self):
        response = self.post("seleccion", {"selection": json.dumps([{"line_id": self.line.pk, "quantity": 7}])})
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Payment.objects.exists())

    def test_selection_not_based_only_on_order_quantity(self):
        payments.create_amount_payment(self.order, "10", "CARD", self.user, card_approved=True)
        state = self.state()
        self.assertEqual(state["lines"][0]["available_quantity"], 5)
        self.assertEqual(state["lines"][0]["partial_quantity"], 1)
        self.assertEqual(self.quote(mode="selection", selection=[{"line_id": self.line.pk, "quantity": 5}])["amount"], "125.00")

    def test_invalid_selection_forms(self):
        for selection in ('bad', '[]', '[{"line_id":true,"quantity":1}]', '[{"line_id":1,"quantity":0}]'):
            with self.subTest(selection=selection):
                self.assertEqual(self.post("seleccion", {"selection": selection}).status_code, 409)

    def test_foreign_line_selection_rejected(self):
        other = self.open(self.destination)
        line = orders.add_product_to_order(other, self.product, 1, self.user)
        orders.send_order(other, self.user)
        self.assertEqual(self.post("seleccion", {"selection": json.dumps([{"line_id":line.pk,"quantity":1}])}).status_code, 409)

    def test_transfer_requires_reference_and_reserves_balance(self):
        quote = self.quote()
        self.assertEqual(self.pay("transferencia", quote=quote).status_code, 409)
        response = self.pay("transferencia", quote=quote, reference="TR-123")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Payment.objects.get().status, "PENDING")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "PAYMENT_PENDING")
        state = response.json()["state"]
        self.assertEqual(state["summary"]["available_to_pay"], "Q0.00")
        self.assertFalse(state["can_close"])
        self.assertEqual(self.post("cerrar").status_code, 409)

    def test_deposit_pending_reference(self):
        self.assertEqual(self.pay("deposito").status_code, 409)
        response = self.pay("deposito", reference="DEP-2")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Payment.objects.get().method, "DEPOSIT")
        self.assertEqual(response.json()["state"]["summary"]["pending_verification"], "Q150.00")

    def test_reserved_units_not_selectable(self):
        payments.create_selected_payment(self.order, [{"line_id":self.line.pk,"quantity":2}], "TRANSFER", self.user, reference="TR")
        self.assertEqual(self.state()["lines"][0]["available_quantity"], 4)
        self.assertEqual(self.quote()["amount"], "100.00")

    def test_client_price_amount_status_ignored(self):
        response = self.pay(amount="1", price="1", status="PENDING", area=self.other_area.pk)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Payment.objects.get().amount, 150)
        self.assertEqual(Payment.objects.get().status, "CONFIRMED")

    def test_preview_does_not_record_payment(self):
        self.quote()
        self.quote(mode="selection", selection=[{"line_id":self.line.pk,"quantity":2}])
        self.assertFalse(Payment.objects.exists())


class MixedAndCloseTests(AccountTestCase):
    def test_mixed_cash_card_exact_completion(self):
        initial = self.quote()
        first = self.quote(mode="amount", amount="50", scope=initial["token"])
        self.assertEqual(self.pay("efectivo", quote=first, received="100").status_code, 200)
        remainder = self.quote(scope=initial["token"])
        self.assertEqual(remainder["amount"], "100.00")
        self.assertEqual(self.pay(quote=remainder).status_code, 200)
        self.assertEqual(Payment.objects.count(), 2)
        self.assertTrue(self.state()["can_close"])

    def test_mixed_cash_transfer_reserves_remainder(self):
        first = self.quote(mode="amount", amount="50")
        self.pay("efectivo", quote=first, received="50")
        self.pay("transferencia", reference="TR-MIX")
        state = self.state()
        self.assertEqual(state["summary"]["confirmed_paid"], "Q50.00")
        self.assertEqual(state["summary"]["pending_verification"], "Q100.00")
        self.assertEqual(state["summary"]["available_to_pay"], "Q0.00")
        self.assertEqual(self.post("mixto", {"amount":"100"}).status_code, 409)

    def test_mixed_selected_units_stay_scoped_after_partial_abono(self):
        initial = self.quote(mode="selection", selection=[{"line_id":self.line.pk,"quantity":2}])
        first = self.quote(mode="amount", amount="10", scope=initial["token"])
        self.pay(quote=first)
        remainder = self.quote(scope=initial["token"])
        self.assertEqual(remainder["amount"], "40.00")
        self.pay(quote=remainder)
        self.assertEqual(get_financial_summary(self.order)["available_to_pay"], 100)
        self.assertEqual(self.state()["lines"][0]["paid_quantity"], 2)

    def test_amount_cannot_exceed_available(self):
        for amount in ("151", "0", "-1", "1.001", "NaN"):
            self.assertEqual(self.post("mixto", {"amount":amount}).status_code, 409)
        self.assertFalse(Payment.objects.exists())

    def test_successful_close_releases_table(self):
        self.pay()
        response = self.post("cerrar")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["closed"])
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "CLOSED")
        self.assertFalse(self.order.table_links.filter(released_at__isnull=True).exists())
        state = self.client.get('/operacion/mesas/', HTTP_ACCEPT='application/json').json()
        table = next(table for group in state["groups"] for table in group["tables"] if table["id"] == self.table.pk)
        self.assertEqual(table["state_label"], "Libre")

    def test_cannot_close_with_draft(self):
        orders.add_product_to_order(self.order, self.product, 1, self.user)
        self.pay()
        self.assertFalse(self.state()["can_close"])
        self.assertEqual(self.post("cerrar").status_code, 409)

    def test_cannot_close_positive_balance(self):
        self.assertEqual(self.post("cerrar").status_code, 409)
        self.assertTrue(self.order.table_links.filter(released_at__isnull=True).exists())


class SplitCollectionTests(AccountTestCase):
    def setUp(self):
        super().setUp()
        self.jorge, self.carlos, self.other_line = self.split_order()

    def test_requires_selection_to_pay(self):
        self.assertEqual(self.state()["lines"], [])
        self.assertEqual(self.post("preparar").status_code, 409)

    def test_scope_only_selected_account(self):
        state = self.state(subaccount=self.jorge.pk)
        self.assertEqual(len(state["lines"]), 1)
        self.assertEqual(state["summary"]["charge_total"], "Q50.00")
        self.assertEqual(state["lines"][0]["id"], self.line.pk)

    def test_pay_one_closes_one_other_remains_open(self):
        response = self.pay(account=self.jorge)
        self.assertEqual(response.status_code, 200)
        self.jorge.refresh_from_db(); self.carlos.refresh_from_db()
        self.assertEqual(self.jorge.status, "CLOSED")
        self.assertEqual(self.carlos.status, "OPEN")
        self.assertTrue(response.json()["state"]["account_closed"])
        self.assertFalse(response.json()["state"]["can_add"])
        self.assertFalse(response.json()["state"]["can_close"])

    def test_closed_account_remains_readable_not_payable(self):
        self.pay(account=self.jorge)
        self.assertTrue(self.state(subaccount=self.jorge.pk)["lines"][0]["settled"])
        self.assertEqual(self.post("preparar", {"subaccount":self.jorge.pk}).status_code, 409)

    def test_pending_does_not_close_subaccount(self):
        self.pay("transferencia", account=self.jorge, reference="TR-J")
        self.jorge.refresh_from_db()
        self.assertEqual(self.jorge.status, "OPEN")
        self.assertFalse(self.state(subaccount=self.jorge.pk)["can_pay"])

    def test_draft_prevents_subaccount_closure(self):
        orders.add_product_to_order(self.order, self.product, 1, self.user, subaccount=self.jorge)
        self.pay(account=self.jorge)
        self.jorge.refresh_from_db()
        self.assertEqual(self.jorge.status, "OPEN")

    def test_foreign_subaccount_rejected(self):
        self.assertEqual(self.post("preparar", {"subaccount":"999999"}).status_code, 409)
        self.assertEqual(self.post("seleccion", {"subaccount":self.jorge.pk,"selection":json.dumps([{"line_id":self.other_line.pk,"quantity":1}])}).status_code, 409)

    def test_both_paid_then_close_order(self):
        self.pay(account=self.jorge); self.pay(account=self.carlos)
        self.assertTrue(self.state(subaccount=self.carlos.pk)["can_close"])
        self.assertEqual(self.post("cerrar").status_code, 200)

    def test_confirmation_cannot_cross_subaccounts(self):
        quote = self.quote(subaccount=self.jorge.pk)
        response = self.pay(quote=quote, account=self.carlos)
        self.assertEqual(response.status_code, 409)
        self.assertFalse(Payment.objects.exists())


class AccountSecurityTests(AccountTestCase):
    def test_post_and_csrf_all_actions(self):
        strict = Client(enforce_csrf_checks=True); strict.cookies.update(self.client.cookies)
        for action in ("seleccion","preparar","mixto","efectivo","tarjeta","transferencia","deposito","cerrar"):
            self.assertEqual(self.client.get(self.url(action)).status_code, 405)
            self.assertEqual(strict.post(self.url(action)).status_code, 403)

    def test_other_area_manual_url_rejected(self):
        TableOrder.objects.filter(pk=self.order.pk).update(area=self.other_area)
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.assertEqual(self.post("preparar").status_code, 409)

    def test_invalid_device_rejected(self):
        self.client.cookies[DEVICE_COOKIE] = "tampered"
        self.assertEqual(self.post("preparar").status_code, 401)

    def test_expired_session_never_records(self):
        quote = self.quote()
        OperationalSession.objects.update(last_activity_at=timezone.now() - timedelta(seconds=121))
        self.assertEqual(self.pay(quote=quote).status_code, 401)
        self.assertFalse(Payment.objects.exists())

    def test_permission_record_independent_from_view(self):
        self.waiter.user_permissions.remove(Permission.objects.get(codename="record_payment",content_type__app_label="payments"))
        self.assertEqual(self.client.get(self.url()).status_code, 200)
        self.assertEqual(self.post("preparar").status_code, 403)

    def test_permission_close_independent(self):
        self.pay()
        self.waiter.user_permissions.remove(Permission.objects.get(codename="close_order",content_type__app_label="payments"))
        self.assertEqual(self.post("cerrar").status_code, 403)

    def test_view_requires_financial_permission(self):
        self.waiter.user_permissions.remove(*Permission.objects.filter(content_type__app_label="payments"))
        self.assertEqual(self.client.get(self.url()).status_code, 403)

    def test_tampered_quote_rejected(self):
        quote = self.quote(); quote["token"] += 'tampered'
        self.assertEqual(self.pay(quote=quote).status_code, 409)
        self.assertFalse(Payment.objects.exists())

    def test_replayed_confirmation_does_not_duplicate(self):
        quote = self.quote(mode="amount", amount="25")
        self.assertEqual(self.pay(quote=quote).status_code, 200)
        response = self.pay(quote=quote)
        self.assertEqual(response.status_code, 409)
        self.assertIn("otro usuario", response.json()["message"])
        self.assertEqual(Payment.objects.count(), 1)

    def test_stale_full_quote_rejected_after_other_payment(self):
        quote = self.quote()
        payments.create_amount_payment(self.order, "25", "CARD", self.user, card_approved=True)
        response = self.pay(quote=quote)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["state"]["summary"]["available_to_pay"], "Q125.00")

    def test_quote_cannot_cross_session(self):
        quote = self.quote()
        self.client.post('/operacion/bloquear/')
        self.login(user=self.second_waiter, pin="4632")
        self.assertEqual(self.pay(quote=quote).status_code, 409)
        self.assertFalse(Payment.objects.exists())

    def test_closed_order_and_released_table_rejected(self):
        self.pay(); self.post("cerrar")
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.assertEqual(self.post("preparar").status_code, 409)

    def test_no_open_day_rejects_payment(self):
        quote = self.quote()
        type(self.day).objects.filter(pk=self.day.pk).update(status="CLOSED",closed_at=timezone.now(),closed_by=self.user)
        self.assertEqual(self.pay(quote=quote).status_code, 409)
        self.assertFalse(Payment.objects.exists())

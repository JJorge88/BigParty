from decimal import Decimal as D
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from apps.audit.models import AuditLog
from apps.catalog.models import ModifierGroup, ModifierOption
from apps.orders import services as orders
from apps.orders.models import OrderLine, SubAccount
from apps.payments import services as s
from apps.payments.models import Payment, PaymentAllocation
from .base import PaymentsTestCase


class PaymentTests(PaymentsTestCase):
    def test_only_sent_consumption_is_chargeable(self):
        order = self.open()
        line = orders.add_product_to_order(order, self.product, 2, self.user)
        self.assertEqual(s.get_order_charge_total(order), D("0.00"))
        with self.assertRaises(ValidationError):
            s.pay_full_balance(order, "CASH", self.user)
        orders.send_order(order, self.user)
        orders.cancel_sent_line(line, self.user, "Error")
        self.assertEqual(s.get_order_charge_total(order), D("0.00"))

    def test_selected_two_of_six_and_remaining_four(self):
        order, _, line = self.consumption()
        payment = s.create_selected_payment(order, [{"line_id": line.pk, "quantity": 2}], "CASH", self.user)
        self.assertEqual(payment.amount, D("50"))
        self.assertEqual(payment.allocations.count(), 2)
        self.assertEqual(sum(a.quantity for a in payment.allocations.all()), 2)
        state = s.get_line_payment_quantities(line)
        self.assertEqual(state["confirmed_quantity"], 2)
        self.assertEqual(state["outstanding_quantity"], 4)
        other = s.create_selected_payment(order, [{"line_id": line.pk, "quantity": 4}], "CARD", self.user, card_approved=True)
        self.assertEqual(other.amount, D("100"))
        line.refresh_from_db()
        self.assertEqual(line.quantity, 6)
        self.assertEqual(s.get_order_balance(order), D("0"))
        with self.assertRaises(ValidationError):
            s.create_selected_payment(order, [{"line_id": line.pk, "quantity": 1}], "CASH", self.user)

    def test_mixed_amounts_can_split_one_physical_unit(self):
        order, _, line = self.consumption(1)
        first = s.create_amount_payment(order, D("10.13"), "CASH", self.user)
        self.assertIsNone(first.allocations.get().quantity)
        self.assertEqual(s.get_line_payment_quantities(line)["partially_covered_quantity"], 1)
        self.assertEqual(s.get_line_payment_quantities(line)["confirmed_quantity"], 0)
        second = s.pay_full_balance(order, "CARD", self.user, card_approved=True)
        self.assertEqual(second.amount, D("14.87"))
        self.assertEqual(s.get_line_payment_quantities(line)["confirmed_quantity"], 1)
        self.assertEqual(s.get_order_confirmed_paid_total(order), D("25"))
        self.assertEqual(s.get_order_balance(order), D("0"))

    def test_sequential_amount_allocation_is_deterministic(self):
        order, _, first = self.consumption(2)
        second = orders.add_product_to_order(order, self.product, 1, self.user)
        orders.send_order(order, self.user)
        payment = s.create_amount_payment(order, D("55"), "CASH", self.user)
        rows = list(payment.allocations.order_by("pk").values_list("order_line_id", "unit_number", "amount"))
        self.assertEqual(rows, [(first.pk, 1, D("25")), (first.pk, 2, D("25")), (second.pk, 1, D("5"))])

    def test_cash_received_change_and_waiter_handoff(self):
        order, _, _ = self.consumption(4)
        payment = s.pay_cash(order, D("85"), self.user, received_amount=D("100"))
        self.assertEqual(payment.amount, D("85"))
        self.assertEqual(payment.change_due, D("15"))
        self.assertEqual(payment.recorded_by, self.user)
        self.assertEqual(payment.cash_handoff_status, "PENDING")
        self.assertEqual(s.get_order_balance(order), D("15"))

    def test_cashier_cash_does_not_require_handoff(self):
        order, _, _ = self.consumption(1)
        session = self.cash_session()
        self.user.role = "CAJERO"
        self.user.save()
        payment = s.pay_full_balance(order, "CASH", self.user, cash_session=session)
        self.assertEqual(payment.cash_handoff_status, "NOT_REQUIRED")
        self.assertEqual(payment.change_due, D("0"))

    def test_insufficient_cash_received_rolls_back(self):
        order, _, _ = self.consumption(1)
        with self.assertRaises(ValidationError):
            s.pay_full_balance(order, "CASH", self.user, received_amount=D("20"))
        self.assertFalse(Payment.objects.exists())

    def test_card_requires_explicit_terminal_approval(self):
        order, _, _ = self.consumption(1)
        with self.assertRaises(ValidationError):
            s.pay_full_balance(order, "CARD", self.user)
        payment = s.pay_full_balance(order, "CARD", self.user, card_approved=True)
        self.assertEqual(payment.status, "CONFIRMED")
        self.assertEqual(payment.confirmed_by, self.user)
        self.assertIsNotNone(payment.confirmed_at)
        self.assertEqual(payment.reference, "")

    def test_transfer_and_deposit_require_reference_and_reserve_balance(self):
        order, _, line = self.consumption(2)
        for method in ("TRANSFER", "DEPOSIT"):
            with self.subTest(method=method):
                with self.assertRaises(ValidationError):
                    s.create_amount_payment(order, D("25"), method, self.user, reference="  ")
                payment = s.create_amount_payment(order, D("25"), method, self.user, reference="REF-1")
                self.assertEqual(payment.status, "PENDING")
                self.assertIsNone(payment.confirmed_by)
                self.assertEqual(payment.cash_handoff_status, "NOT_REQUIRED")
        order.refresh_from_db()
        self.assertEqual(order.status, "PAYMENT_PENDING")
        self.assertEqual(s.get_order_balance(order), D("50"))
        self.assertEqual(s.get_order_confirmed_paid_total(order), D("0"))
        self.assertEqual(s.get_order_pending_payment_total(order), D("50"))
        self.assertEqual(s.get_line_payment_quantities(line)["pending_verification_quantity"], 2)
        with self.assertRaises(ValidationError):
            s.pay_full_balance(order, "CASH", self.user)

    def test_confirm_pending_records_actor_time_history_and_balance(self):
        order, _, _ = self.consumption(1)
        payment = s.pay_full_balance(order, "TRANSFER", self.user, reference="ABC")
        verified = s.confirm_pending_payment(payment, self.other_user)
        self.assertEqual(verified.confirmed_by, self.other_user)
        self.assertIsNotNone(verified.confirmed_at)
        self.assertEqual(s.get_order_balance(order), D("0"))
        self.assertEqual(s.get_order_pending_payment_total(order), D("0"))
        order.refresh_from_db()
        self.assertEqual(order.status, "PARTIALLY_PAID")
        self.assertTrue(s.can_close_order(order))
        self.assertTrue(order.activities.filter(activity_type="PAYMENT_CONFIRMED", user=self.other_user).exists())
        self.assertTrue(AuditLog.objects.filter(action="orders.payment_confirmed").exists())
        with self.assertRaises(ValidationError):
            s.confirm_pending_payment(payment, self.user)

    def test_rejection_releases_reservation_and_preserves_record(self):
        order, _, _ = self.consumption(1)
        payment = s.pay_full_balance(order, "DEPOSIT", self.user, reference="ABC")
        with self.assertRaises(ValidationError):
            s.reject_pending_payment(payment, self.user, " ")
        rejected = s.reject_pending_payment(payment, self.other_user, "No recibido")
        self.assertEqual(rejected.status, "REJECTED")
        self.assertEqual(rejected.metadata["rejected_by"], self.other_user.pk)
        order.refresh_from_db()
        self.assertEqual(order.status, "OPEN")
        self.assertEqual(s.get_order_pending_payment_total(order), D("0"))
        s.pay_full_balance(order, "CASH", self.user)
        self.assertEqual(Payment.objects.count(), 2)
        self.assertTrue(AuditLog.objects.filter(action="orders.payment_rejected").exists())
        with self.assertRaises(ValidationError):
            s.confirm_pending_payment(payment, self.user)

    def test_reject_with_other_confirmed_payment_restores_partial_status(self):
        order, _, _ = self.consumption(2)
        s.create_amount_payment(order, D("10"), "CASH", self.user)
        pending = s.pay_full_balance(order, "TRANSFER", self.user, reference="R")
        s.reject_pending_payment(pending, self.user, "No recibido")
        order.refresh_from_db()
        self.assertEqual(order.status, "PARTIALLY_PAID")
        self.assertEqual(s.get_order_balance(order), D("40"))

    def test_pending_partial_and_cash_only_cover_unreserved_balance(self):
        order, _, line = self.consumption(1)
        s.create_amount_payment(order, D("10"), "TRANSFER", self.user, reference="R")
        payment = s.pay_full_balance(order, "CASH", self.user)
        self.assertEqual(payment.amount, D("15"))
        self.assertEqual(s.get_order_balance(order), D("10"))
        self.assertEqual(s.get_financial_summary(order)["available_to_pay"], D("0"))
        self.assertEqual(s.get_line_payment_quantities(line)["pending_verification_quantity"], 1)

    def test_permission_not_role_controls_record_and_verify(self):
        order, _, _ = self.consumption(1)
        manager = get_user_model().objects.create_user(username="manager-no-perms", role="GERENTE")
        with self.assertRaises(PermissionDenied):
            s.pay_full_balance(order, "CASH", manager)
        manager.user_permissions.add(Permission.objects.get(codename="record_payment", content_type__app_label="payments"))
        manager = get_user_model().objects.get(pk=manager.pk)
        payment = s.pay_full_balance(order, "TRANSFER", manager, reference="R")
        for operation in (lambda: s.confirm_pending_payment(payment, manager), lambda: s.reject_pending_payment(payment, manager, "Error")):
            with self.assertRaises(PermissionDenied):
                operation()

    def test_snapshot_price_with_modifiers_is_used(self):
        group = ModifierGroup.objects.create(product=self.product, name="Extra", min_selections=0, max_selections=1)
        option = ModifierOption.objects.create(group=group, name="Extra", price_delta=10)
        order = self.open()
        line = orders.add_product_to_order(order, self.product, 2, self.user, modifier_option_ids=[option.pk])
        orders.send_order(order, self.user)
        self.product.base_price = 100
        self.product.save()
        option.price_delta = 50
        option.save()
        payment = s.pay_full_balance(order, "CASH", self.user)
        self.assertEqual(payment.amount, D("70"))
        self.assertEqual(line.unit_price, D("35"))

    def test_invalid_money_and_overpayment_never_create_records(self):
        order, _, _ = self.consumption(1)
        for amount in (0, -1, D("0.001"), 1.0, True, "NaN", "Infinity", "wrong", None, D("26")):
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                s.create_amount_payment(order, amount, "CASH", self.user)
        self.assertFalse(Payment.objects.exists())

    def test_invalid_selections_do_not_assign(self):
        order, _, line = self.consumption(1)
        selections = [[], [{"line_id": line.pk, "quantity": 0}], [{"line_id": line.pk, "quantity": 1.5}],
                      [{"line_id": line.pk, "quantity": 2}], [{"line_id": 999999, "quantity": 1}],
                      [{"line_id": line.pk, "quantity": 1}] * 2, ["bad"]]
        for selection in selections:
            with self.subTest(selection=selection), self.assertRaises(ValidationError):
                s.create_selected_payment(order, selection, "CASH", self.user)
        self.assertFalse(PaymentAllocation.objects.exists())

    def test_selected_does_not_implicitly_finish_partial_unit(self):
        order, _, line = self.consumption(1)
        s.create_amount_payment(order, D("10"), "CASH", self.user)
        with self.assertRaises(ValidationError):
            s.create_selected_payment(order, [{"line_id": line.pk, "quantity": 1}], "CASH", self.user)
        s.pay_full_balance(order, "CASH", self.user)
        self.assertEqual(s.get_order_balance(order), D("0"))

    def test_failure_after_payment_rolls_back_money_allocations_and_activity(self):
        order, _, _ = self.consumption(1)
        before = order.activities.count()
        with patch("apps.payments.services._refresh", side_effect=RuntimeError("late failure")):
            with self.assertRaises(RuntimeError):
                s.pay_full_balance(order, "CASH", self.user)
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(PaymentAllocation.objects.exists())
        self.assertEqual(order.activities.count(), before)

    def test_database_rejects_nonpositive_amount_and_duplicate_allocation(self):
        order, _, _ = self.consumption(1)
        payment = s.pay_full_balance(order, "CASH", self.user)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Payment.objects.filter(pk=payment.pk).update(amount=0)
        allocation = payment.allocations.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            PaymentAllocation.objects.create(payment=payment, order_line=allocation.order_line, unit_number=1, amount=25)

    def test_receipt_and_history_expose_scope_and_net_totals(self):
        order, _, line = self.consumption(1)
        first = s.create_amount_payment(order, D("10"), "CASH", self.user)
        second = s.pay_full_balance(order, "TRANSFER", self.user, reference="R")
        receipt = s.get_receipt_data(order)
        self.assertEqual(receipt["order_number"], order.order_number)
        self.assertEqual(receipt["lines"][0]["unit_price"], D("25"))
        self.assertEqual(receipt["confirmed_paid"], D("10"))
        self.assertEqual(receipt["pending_verification"], D("15"))
        self.assertEqual(list(s.get_payment_history(order).values_list("pk", flat=True)), [first.pk, second.pk])

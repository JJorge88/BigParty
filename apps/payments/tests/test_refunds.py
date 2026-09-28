from decimal import Decimal as D
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError

from apps.audit.models import AuditLog
from apps.inventory.models import InventoryMovement
from apps.orders import services as orders
from apps.payments import services as s
from apps.payments.models import PaymentRefund, RefundAllocation
from .base import PaymentsTestCase


class RefundTests(PaymentsTestCase):
    def setUp(self):
        self.session = self.cash_session()

    def test_partial_then_total_monetary_refund_keeps_net_balance_settled(self):
        order, _, _ = self.consumption(2)
        payment = s.pay_full_balance(order, "CASH", self.user, cash_session=self.session)
        first = s.refund_payment(payment, self.user, amount=D("10"), reason="Compensación")
        payment.refresh_from_db()
        self.assertEqual(payment.status, "CONFIRMED")
        self.assertEqual(s.get_order_confirmed_paid_total(order), D("40"))
        self.assertEqual(s.get_order_charge_total(order), D("40"))
        self.assertEqual(s.get_order_balance(order), D("0"))
        s.refund_payment(payment, self.user, amount=D("40"), reason="Devolución restante")
        payment.refresh_from_db()
        self.assertEqual(payment.status, "REFUNDED")
        self.assertEqual(s.get_order_confirmed_paid_total(order), D("0"))
        self.assertEqual(s.get_order_charge_total(order), D("0"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 98)
        self.assertFalse(InventoryMovement.objects.filter(movement_type="REFUND_RETURN").exists())
        with self.assertRaises(ValidationError):
            s.refund_payment(payment, self.user, amount=D("1"), reason="Otra")

    def test_refund_closed_order_and_subaccount_never_reopens_them(self):
        order, account, _ = self.consumption(1, split=True)
        payment = s.pay_full_balance(account, "CASH", self.user, cash_session=self.session)
        s.close_order(order, self.user)
        s.refund_payment(payment, self.user, amount=D("25"), reason="Devolución")
        account.refresh_from_db(); order.refresh_from_db()
        self.assertEqual(account.status, "CLOSED")
        self.assertEqual(order.status, "CLOSED")
        self.assertEqual(s.get_subaccount_balance(account), D("0"))
        self.assertEqual(orders.get_operational_table_state(self.table), "AVAILABLE")
        receipt = s.get_receipt_data(account)
        self.assertEqual(receipt["refunds"][0]["amount"], D("25"))

    def test_exact_refund_returns_only_selected_unit_inventory(self):
        order, _, line = self.consumption(3)
        payment = s.pay_full_balance(order, "CASH", self.user, cash_session=self.session)
        allocation = payment.allocations.order_by("unit_number").first()
        refund = s.refund_payment(payment, self.user, allocation_ids=[allocation.pk], return_to_inventory=True, reason="Devuelto intacto")
        self.assertEqual(refund.amount, D("25"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 98)
        movement = InventoryMovement.objects.get(movement_type="REFUND_RETURN")
        self.assertEqual(movement.quantity_delta, 1)
        self.assertEqual(movement.metadata["refund_id"], refund.pk)
        self.assertEqual(movement.metadata["unit_number"], 1)
        self.assertTrue(AuditLog.objects.filter(action="orders.refund").exists())
        with self.assertRaises(ValidationError):
            s.refund_payment(payment, self.user, allocation_ids=[allocation.pk], return_to_inventory=True, reason="Otra")
        self.assertEqual(InventoryMovement.objects.filter(movement_type="REFUND_RETURN").count(), 1)

    def test_exact_refund_without_inventory_keeps_consumption(self):
        order, _, _ = self.consumption(1)
        payment = s.pay_full_balance(order, "CASH", self.user, cash_session=self.session)
        s.refund_payment(payment, self.user, allocation_ids=[payment.allocations.get().pk], reason="Consumido")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 99)

    def test_combo_refund_returns_snapshot_components(self):
        combo, energy = self.combo()
        order, _, line = self.consumption(2, product=combo)
        payment = s.pay_full_balance(order, "CASH", self.user, cash_session=self.session)
        s.refund_payment(payment, self.user, allocation_ids=[payment.allocations.order_by("unit_number").first().pk], return_to_inventory=True, reason="Combo devuelto")
        self.product.refresh_from_db(); energy.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 99)
        self.assertEqual(energy.stock_quantity, 26)
        self.assertEqual(list(InventoryMovement.objects.filter(movement_type="REFUND_RETURN").order_by("quantity_delta").values_list("quantity_delta", flat=True)), [1, 4])

    def test_untracked_refund_does_not_create_inventory(self):
        self.product.track_inventory = False
        self.product.stock_quantity = 0
        self.product.save()
        order, _, _ = self.consumption(1)
        payment = s.pay_full_balance(order, "CASH", self.user, cash_session=self.session)
        s.refund_payment(payment, self.user, allocation_ids=[payment.allocations.get().pk], return_to_inventory=True, reason="Devuelto")
        self.assertFalse(InventoryMovement.objects.exists())

    def test_monetary_refund_cannot_guess_stock(self):
        order, _, _ = self.consumption(1)
        payment = s.pay_full_balance(order, "CASH", self.user, cash_session=self.session)
        with self.assertRaises(ValidationError):
            s.refund_payment(payment, self.user, amount=D("25"), return_to_inventory=True, reason="Devuelto")
        self.assertFalse(PaymentRefund.objects.exists())

    def test_unit_with_split_payment_cannot_return_stock_from_one_payment(self):
        order, _, _ = self.consumption(1)
        first = s.create_amount_payment(order, D("10"), "CASH", self.user, cash_session=self.session)
        s.pay_full_balance(order, "CASH", self.user, cash_session=self.session)
        with self.assertRaises(ValidationError):
            s.refund_payment(first, self.user, allocation_ids=[first.allocations.get().pk], return_to_inventory=True, reason="Devuelto")
        s.refund_payment(first, self.user, amount=D("10"), reason="Solo dinero")

    def test_refund_after_partial_money_return_cannot_return_unit_again(self):
        order, _, _ = self.consumption(1)
        payment = s.pay_full_balance(order, "CASH", self.user, cash_session=self.session)
        s.refund_payment(payment, self.user, amount=D("1"), reason="Compensación")
        with self.assertRaises(ValidationError):
            s.refund_payment(payment, self.user, allocation_ids=[payment.allocations.get().pk], return_to_inventory=True, reason="Devuelto")

    def test_discounted_unit_returns_only_paid_value_and_one_stock_unit(self):
        order, _, _ = self.consumption(1)
        s.apply_order_adjustment(order, self.user, amount=D("5"), reason="Promoción")
        payment = s.pay_full_balance(order, "CASH", self.user, cash_session=self.session)
        refund = s.refund_payment(payment, self.user, allocation_ids=[payment.allocations.get().pk], return_to_inventory=True, reason="Devuelto")
        self.assertEqual(refund.amount, D("20"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 100)
        self.assertEqual(s.get_order_charge_total(order), D("0"))

    def test_refund_requires_confirmed_payment_reason_and_permission(self):
        order, _, _ = self.consumption(1)
        pending = s.pay_full_balance(order, "TRANSFER", self.user, reference="R")
        with self.assertRaises(ValidationError):
            s.refund_payment(pending, self.user, amount=D("1"), reason="Error")
        payment = s.confirm_pending_payment(pending, self.user)
        manager = get_user_model().objects.create_user(username="refund-manager", role="GERENTE")
        with self.assertRaises(PermissionDenied):
            s.refund_payment(payment, manager, amount=D("1"), reason="Error")
        with self.assertRaises(ValidationError):
            s.refund_payment(payment, self.user, amount=D("1"), reason=" ")
        with self.assertRaises(ValidationError):
            s.refund_payment(payment, self.user, amount=D("26"), reason="Error")

    def test_wrong_and_duplicate_allocations_are_rejected(self):
        order, _, _ = self.consumption(2)
        first = s.create_amount_payment(order, D("25"), "CASH", self.user, cash_session=self.session)
        other = s.pay_full_balance(order, "CASH", self.user, cash_session=self.session)
        pk = first.allocations.get().pk
        for ids in ([pk, pk], [other.allocations.get().pk], [], [True]):
            with self.subTest(ids=ids), self.assertRaises(ValidationError):
                s.refund_payment(first, self.user, allocation_ids=ids, reason="Error")
        self.assertFalse(RefundAllocation.objects.exists())

    def test_late_refund_failure_rolls_back_stock_and_finances(self):
        order, _, _ = self.consumption(1)
        payment = s.pay_full_balance(order, "CASH", self.user, cash_session=self.session)
        with patch("apps.payments.services._log", side_effect=RuntimeError("late failure")):
            with self.assertRaises(RuntimeError):
                s.refund_payment(payment, self.user, allocation_ids=[payment.allocations.get().pk], return_to_inventory=True, reason="Devuelto")
        self.product.refresh_from_db(); payment.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 99)
        self.assertEqual(payment.status, "CONFIRMED")
        self.assertFalse(PaymentRefund.objects.exists())
        self.assertFalse(InventoryMovement.objects.filter(movement_type="REFUND_RETURN").exists())

    def test_full_stock_return_allows_disabling_inventory_again(self):
        order, _, _ = self.consumption(1)
        payment = s.pay_full_balance(order, "CASH", self.user, cash_session=self.session)
        self.product.refresh_from_db()
        self.product.track_inventory = False
        self.product.stock_quantity = 0
        with self.assertRaises(ValidationError):
            self.product.save()
        s.refund_payment(payment, self.user, allocation_ids=[payment.allocations.get().pk], return_to_inventory=True, reason="Devuelto")
        self.product.refresh_from_db()
        self.product.track_inventory = False
        self.product.stock_quantity = 0
        self.product.save()

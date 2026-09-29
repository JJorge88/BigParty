from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError

from apps.audit.models import AuditLog
from apps.orders import services as orders
from apps.orders.models import SubAccount, OrderLine
from apps.payments import services as s
from apps.payments.models import Payment, OrderAdjustment
from .base import PaymentsTestCase


class SettlementTests(PaymentsTestCase):
    def test_subaccounts_pay_independently_and_close_only_when_complete(self):
        order, first, line = self.consumption(2, split=True)
        second = orders.create_subaccount(order, "Carlos", self.user)
        other = orders.add_product_to_order(order, self.product, 1, self.user, subaccount=second)
        orders.send_order(order, self.user)
        payment = s.pay_full_balance(first, "CASH", self.user)
        first.refresh_from_db(); second.refresh_from_db()
        self.assertEqual(first.status, "CLOSED")
        self.assertIsNotNone(first.closed_at)
        self.assertEqual(second.status, "OPEN")
        self.assertEqual(payment.subaccount, first)
        self.assertEqual(s.get_subaccount_charge_total(first), D("50"))
        self.assertEqual(s.get_subaccount_confirmed_paid_total(first), D("50"))
        self.assertEqual(s.get_subaccount_balance(first), D("0"))
        self.assertEqual(s.get_subaccount_balance(second), D("25"))
        self.assertFalse(s.can_close_order(order))
        with self.assertRaises(ValidationError):
            orders.add_product_to_order(order, self.product, 1, self.user, subaccount=first)
        new = orders.create_subaccount(order, "Jorge", self.user)
        self.assertNotEqual(new.pk, first.pk)

    def test_pending_keeps_subaccount_open_until_confirmed(self):
        order, account, _ = self.consumption(1, split=True)
        payment = s.pay_full_balance(account, "DEPOSIT", self.user, reference="DEP")
        account.refresh_from_db()
        self.assertEqual(account.status, "OPEN")
        self.assertEqual(s.get_subaccount_pending_payment_total(account), D("25"))
        s.confirm_pending_payment(payment, self.other_user)
        account.refresh_from_db()
        self.assertEqual(account.status, "CLOSED")
        self.assertTrue(s.can_close_order(order))
        order.refresh_from_db()
        self.assertNotEqual(order.status, "CLOSED")

    def test_draft_prevents_automatic_subaccount_close(self):
        order, account, _ = self.consumption(1, split=True)
        draft = orders.add_product_to_order(order, self.product, 1, self.user, subaccount=account)
        s.pay_full_balance(account, "CASH", self.user)
        account.refresh_from_db()
        self.assertEqual(account.status, "OPEN")
        self.assertFalse(s.can_close_order(order))
        with self.assertRaises(ValidationError):
            s.close_order(order, self.user)
        orders.send_order(order, self.user)
        s.pay_full_balance(account, "CASH", self.user)
        account.refresh_from_db()
        self.assertEqual(account.status, "CLOSED")

    def test_cross_subaccount_selection_rejected(self):
        order, first, line = self.consumption(1, split=True)
        second = orders.create_subaccount(order, "Carlos", self.user)
        with self.assertRaises(ValidationError):
            s.create_selected_payment(second, [{"line_id": line.pk, "quantity": 1}], "CASH", self.user)
        self.assertFalse(Payment.objects.exists())

    def test_order_wide_split_payment_closes_consumed_accounts_not_empty_ones(self):
        order, first, line = self.consumption(1, split=True)
        second = orders.create_subaccount(order, "Carlos", self.user)
        empty = orders.create_subaccount(order, "Después", self.user)
        orders.add_product_to_order(order, self.product, 1, self.user, subaccount=second)
        orders.send_order(order, self.user)
        payment = s.pay_full_balance(order, "CASH", self.user)
        self.assertIsNone(payment.subaccount)
        for account in (first, second):
            account.refresh_from_db()
            self.assertEqual(account.status, "CLOSED")
            self.assertEqual(s.get_subaccount_confirmed_paid_total(account), D("25"))
            receipt = s.get_receipt_data(account)
            self.assertEqual(receipt["payments"][0]["amount"], D("25"))
            self.assertEqual(receipt["payments"][0]["payment_amount"], D("50"))
        empty.refresh_from_db()
        self.assertEqual(empty.status, "OPEN")
        s.close_order(order, self.user)
        empty.refresh_from_db()
        self.assertEqual(empty.status, "CLOSED")

    def test_single_payments_have_no_subaccount(self):
        order, _, _ = self.consumption(1)
        payment = s.pay_full_balance(order, "CASH", self.user)
        self.assertIsNone(payment.subaccount)

    def test_close_releases_all_linked_tables_and_allows_new_order(self):
        order, _, _ = self.consumption(1)
        orders.join_table_to_order(order, self.destination, self.user)
        self.assertEqual(orders.get_operational_table_state(self.table), "OCCUPIED")
        s.pay_full_balance(order, "CASH", self.user)
        self.assertTrue(s.can_close_order(order))
        closed = s.close_order(order, self.user)
        self.assertEqual(closed.status, "CLOSED")
        self.assertIsNotNone(closed.closed_at)
        self.assertFalse(closed.table_links.filter(released_at__isnull=True).exists())
        for table in (self.table, self.destination):
            self.assertEqual(orders.get_operational_table_state(table), "AVAILABLE")
        self.assertTrue(AuditLog.objects.filter(action="orders.closed").exists())
        self.assertNotEqual(orders.open_table_order(self.table, self.user).pk, order.pk)
        with self.assertRaises(ValidationError):
            s.close_order(order, self.user)

    def test_close_rejects_unpaid_pending_and_draft(self):
        order, _, _ = self.consumption(1)
        self.assertFalse(s.can_close_order(order))
        with self.assertRaises(ValidationError):
            s.close_order(order, self.user)
        payment = s.pay_full_balance(order, "TRANSFER", self.user, reference="P")
        with self.assertRaises(ValidationError):
            s.close_order(order, self.user)
        s.confirm_pending_payment(payment, self.user)
        draft = orders.add_product_to_order(order, self.product, 1, self.user)
        with self.assertRaises(ValidationError):
            s.close_order(order, self.user)
        orders.remove_draft_line(draft, self.user)
        self.assertTrue(s.can_close_order(order))

    def test_close_permission_and_closed_order_rejects_more_payments(self):
        order, _, _ = self.consumption(1)
        s.pay_full_balance(order, "CASH", self.user)
        manager = get_user_model().objects.create_user(username="close-manager", role="GERENTE")
        with self.assertRaises(PermissionDenied):
            s.close_order(order, manager)
        s.close_order(order, self.user)
        with self.assertRaises(ValidationError):
            s.create_amount_payment(order, D("1"), "CASH", self.user)

    def test_financial_inconsistency_blocks_closure(self):
        order, _, _ = self.consumption(1)
        payment = s.pay_full_balance(order, "CASH", self.user)
        Payment.objects.filter(pk=payment.pk).update(amount=26)
        self.assertFalse(s.can_close_order(order))
        with self.assertRaises(ValidationError):
            s.close_order(order, self.user)
        self.assertEqual(orders.get_operational_table_state(self.table), "PARTIALLY_PAID")

    def test_cancel_and_move_reject_financial_history(self):
        order, account, line = self.consumption(2, split=True)
        destination = orders.create_subaccount(order, "Carlos", self.user)
        s.create_amount_payment(account, D("10"), "CASH", self.user)
        for operation in (lambda: orders.cancel_sent_line(line, self.user, "Error"),
                          lambda: orders.move_line_to_subaccount(line, destination, self.user, quantity=1)):
            with self.assertRaises(ValidationError):
                operation()
        line.refresh_from_db()
        self.assertEqual(line.quantity, 2)
        self.assertEqual(line.status, "SENT")

    def test_rejected_payment_history_is_preserved_by_movement_guard(self):
        order, account, line = self.consumption(1, split=True)
        destination = orders.create_subaccount(order, "Carlos", self.user)
        payment = s.pay_full_balance(account, "TRANSFER", self.user, reference="R")
        s.reject_pending_payment(payment, self.user, "No recibido")
        with self.assertRaises(ValidationError):
            orders.move_line_to_subaccount(line, destination, self.user)
        s.pay_full_balance(account, "CASH", self.user)

    def test_merge_rejects_financial_history_but_physical_move_is_allowed(self):
        order, _, _ = self.consumption(1)
        s.create_amount_payment(order, D("10"), "CASH", self.user)
        other = self.open(table=self.destination)
        with self.assertRaises(ValidationError):
            orders.merge_orders(order, other, self.user)
        s.close_order(other, self.user)
        moved = orders.move_order_to_table(order, self.destination, self.user)
        self.assertEqual(moved.primary_table_id, self.destination.pk)
        self.assertEqual(s.get_order_balance(order), D("15"))

    def test_refresh_status_is_derived_and_never_reopens_closed_order(self):
        order, _, _ = self.consumption(1)
        self.assertEqual(s.refresh_order_payment_status(order).status, "OPEN")
        s.pay_full_balance(order, "CASH", self.user)
        self.assertEqual(s.refresh_order_payment_status(order).status, "PARTIALLY_PAID")
        s.close_order(order, self.user)
        self.assertEqual(s.refresh_order_payment_status(order).status, "CLOSED")

    def test_empty_subaccount_can_be_finalized_during_explicit_order_close(self):
        order = self.open(split=True)
        account = orders.create_subaccount(order, "Vacía", self.user)
        self.assertTrue(s.can_close_order(order))
        s.close_order(order, self.user)
        account.refresh_from_db()
        self.assertEqual(account.status, "CLOSED")

    def test_cancelling_unpaid_remainder_closes_previously_part_paid_subaccount(self):
        order, account, line = self.consumption(1, split=True)
        remainder = orders.add_product_to_order(order, self.product, 1, self.user, subaccount=account)
        orders.send_order(order, self.user)
        s.create_selected_payment(account, [{"line_id": line.pk, "quantity": 1}], "CASH", self.user)
        orders.cancel_sent_line(remainder, self.user, "Error")
        account.refresh_from_db()
        self.assertEqual(account.status, "CLOSED")
        self.assertTrue(s.can_close_order(order))

    def test_removing_draft_after_payment_closes_subaccount(self):
        order, account, _ = self.consumption(1, split=True)
        draft = orders.add_product_to_order(order, self.product, 1, self.user, subaccount=account)
        s.pay_full_balance(account, "CASH", self.user)
        orders.remove_draft_line(draft, self.user)
        account.refresh_from_db()
        self.assertEqual(account.status, "CLOSED")

    def test_moving_unpaid_remainder_closes_source_subaccount(self):
        order, account, line = self.consumption(1, split=True)
        destination = orders.create_subaccount(order, "Carlos", self.user)
        remainder = orders.add_product_to_order(order, self.product, 1, self.user, subaccount=account)
        orders.send_order(order, self.user)
        s.create_selected_payment(account, [{"line_id": line.pk, "quantity": 1}], "CASH", self.user)
        orders.move_line_to_subaccount(remainder, destination, self.user)
        account.refresh_from_db(); destination.refresh_from_db()
        self.assertEqual(account.status, "CLOSED")
        self.assertEqual(destination.status, "OPEN")
        self.assertEqual(s.get_subaccount_balance(destination), D("25"))

    def test_zero_price_consumption_can_close_without_zero_payment(self):
        self.product.base_price = 0
        self.product.save()
        order, _, _ = self.consumption(1)
        with self.assertRaises(ValidationError):
            s.pay_full_balance(order, "CASH", self.user)
        s.close_order(order, self.user)


class AdjustmentTests(PaymentsTestCase):
    def test_general_discount_reduces_charge_not_snapshot_or_inventory(self):
        order, _, line = self.consumption(2)
        adjustment = s.apply_order_adjustment(order, self.user, amount=D("10"), reason="Promoción")
        self.assertEqual(adjustment.adjustment_type, "DISCOUNT")
        self.assertEqual(s.get_order_charge_total(order), D("40"))
        self.assertFalse(Payment.objects.exists())
        line.refresh_from_db(); self.product.refresh_from_db()
        self.assertEqual(line.unit_price, D("25"))
        self.assertEqual(self.product.stock_quantity, 98)
        payment = s.pay_full_balance(order, "CASH", self.user)
        self.assertEqual(payment.amount, D("40"))
        self.assertTrue(AuditLog.objects.filter(action="orders.adjustment_applied").exists())
        self.assertEqual(s.get_receipt_data(order)["adjustments"][0]["amount"], D("10"))

    def test_courtesy_selected_unit_does_not_return_stock(self):
        order, _, line = self.consumption(3)
        adjustment = s.apply_order_adjustment(order, self.user, adjustment_type="COURTESY",
            selection=[{"line_id": line.pk, "quantity": 1}], reason="Atención al cliente")
        self.assertEqual(adjustment.amount, D("25"))
        self.assertEqual(adjustment.allocations.get().quantity, 1)
        self.assertEqual(s.get_order_balance(order), D("50"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 97)
        self.assertEqual(s.get_line_payment_quantities(line)["adjusted_quantity"], 1)
        s.create_selected_payment(order, [{"line_id": line.pk, "quantity": 2}], "CASH", self.user)
        self.assertEqual(s.get_order_balance(order), D("0"))

    def test_adjustment_requires_permission_and_reason(self):
        order, _, _ = self.consumption(1)
        manager = get_user_model().objects.create_user(username="adjust-manager", role="GERENTE")
        with self.assertRaises(PermissionDenied):
            s.apply_order_adjustment(order, manager, amount=D("5"), reason="Motivo")
        with self.assertRaises(ValidationError):
            s.apply_order_adjustment(order, self.user, amount=D("5"), reason=" ")
        self.assertFalse(OrderAdjustment.objects.exists())

    def test_adjustment_cannot_cover_reserved_or_paid_amount(self):
        order, _, _ = self.consumption(1)
        s.create_amount_payment(order, D("5"), "CASH", self.user)
        pending = s.create_amount_payment(order, D("15"), "TRANSFER", self.user, reference="R")
        with self.assertRaises(ValidationError):
            s.apply_order_adjustment(order, self.user, amount=D("6"), reason="Motivo")
        s.apply_order_adjustment(order, self.user, amount=D("5"), reason="Motivo")
        self.assertEqual(s.get_order_balance(order), D("15"))
        s.confirm_pending_payment(pending, self.user)
        self.assertEqual(s.get_order_balance(order), D("0"))

    def test_full_courtesy_closes_subaccount_and_allows_order_close(self):
        order, account, line = self.consumption(1, split=True)
        s.apply_order_adjustment(account, self.user, adjustment_type="COURTESY",
            selection=[{"line_id": line.pk, "quantity": 1}], reason="Cortesía")
        account.refresh_from_db()
        self.assertEqual(account.status, "CLOSED")
        self.assertEqual(s.get_subaccount_charge_total(account), D("0"))
        s.close_order(order, self.user)
        self.assertFalse(Payment.objects.exists())

    def test_adjusted_line_cannot_be_cancelled_or_moved(self):
        order, account, line = self.consumption(2, split=True)
        target = orders.create_subaccount(order, "Carlos", self.user)
        s.apply_order_adjustment(account, self.user, amount=D("1"), reason="Promoción")
        with self.assertRaises(ValidationError):
            orders.cancel_sent_line(line, self.user, "Error")
        with self.assertRaises(ValidationError):
            orders.move_line_to_subaccount(line, target, self.user, quantity=1)

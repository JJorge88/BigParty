from datetime import date, timedelta
from decimal import Decimal as D
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.cash import services as s
from apps.cash.models import BusinessDay, BusinessDayReopen, CashHandoff, CashMovement
from apps.orders import services as orders
from apps.orders.models import TableOrder
from apps.payments import services as payments
from apps.payments.models import Payment
from .base import CashTestCase


class BusinessDayTests(CashTestCase):
    def test_one_open_day_and_permission_required(self):
        with self.assertRaises(ValidationError):
            s.open_business_day(self.user, self.day.business_date + timedelta(days=1))
        with self.assertRaises(IntegrityError), transaction.atomic():
            BusinessDay.objects.create(business_date=self.day.business_date + timedelta(days=1), opened_by=self.user)
        manager = get_user_model().objects.create_user(username="manager-no-day", role="GERENTE")
        with self.assertRaises(PermissionDenied):
            s.open_business_day(manager)

    def test_day_survives_midnight_and_orders_use_explicit_relation(self):
        next_day = timezone.now() + timedelta(days=1)
        with patch("django.utils.timezone.now", return_value=next_day):
            order = self.open()
            session = self.session()
        self.assertEqual(order.business_day, self.day)
        self.assertEqual(session.business_day, self.day)
        self.assertEqual(BusinessDay.objects.count(), 1)

    def test_new_order_requires_open_day(self):
        s.close_business_day(self.day, self.user)
        with self.assertRaises(ValidationError):
            self.open()
        self.assertFalse(TableOrder.objects.exists())

    def test_closed_day_blocks_order_payment_refund_and_cash_mutations(self):
        session = self.session()
        order, _ = self.consumption(1)
        payment = self.payment(order, session=session)
        payments.close_order(order, self.user)
        self.close_session(session)
        s.close_business_day(self.day, self.user)
        operations = [lambda: payments.refund_payment(payment, self.user, amount=D("1"), reason="Devolución"),
                      lambda: orders.update_order_note(order, "Nueva", self.user),
                      lambda: payments.refresh_order_payment_status(order)]
        for operation in operations:
            with self.assertRaises(ValidationError):
                operation()
        self.assertFalse(payment.refunds.exists())

    def test_blockers_are_structured_and_include_all_pending_types(self):
        session = self.session()
        order, _ = self.consumption(4)
        self.payment(order)
        pending = self.payment(order, method="TRANSFER")
        blockers = s.get_business_day_close_blockers(self.day)
        types = {b["type"] for b in blockers}
        self.assertTrue({"ACTIVE_ORDER", "OUTSTANDING_BALANCE", "PENDING_PAYMENT", "OPEN_CASH_SESSION", "PENDING_HANDOFF"}.issubset(types))
        self.assertTrue(all(set(b) == {"type", "description", "object_id"} for b in blockers))
        self.assertIn(pending.pk, [b["object_id"] for b in blockers if b["type"] == "PENDING_PAYMENT"])
        with self.assertRaises(ValidationError):
            s.close_business_day(self.day, self.user)

    def test_handoff_pending_blocks_day_even_when_order_and_session_closed(self):
        session = self.session()
        order, _ = self.consumption(1)
        self.payment(order)
        payments.close_order(order, self.user)
        self.close_session(session)
        blockers = s.get_business_day_close_blockers(self.day)
        self.assertEqual({b["type"] for b in blockers}, {"PENDING_HANDOFF"})
        self.assertFalse(s.can_close_business_day(self.day))

    def test_complete_day_close_and_next_day(self):
        session = self.session()
        order, _ = self.consumption(1)
        payment = self.payment(order)
        s.confirm_cash_handoff(payment, session, self.user)
        payments.close_order(order, self.user)
        self.close_session(session)
        self.assertEqual(s.get_business_day_close_blockers(self.day), [])
        self.assertTrue(s.can_close_business_day(self.day))
        closed = s.close_business_day(self.day, self.other_user)
        self.assertEqual(closed.status, "CLOSED")
        self.assertEqual(closed.closed_by, self.other_user)
        self.assertIsNotNone(closed.closed_at)
        self.assertTrue(AuditLog.objects.filter(action="cash.day_closed").exists())
        self.assertFalse(s.can_close_business_day(closed))
        following = s.open_business_day(self.user, self.day.business_date + timedelta(days=1))
        new_order = self.open()
        self.assertEqual(new_order.business_day, following)

    def test_close_day_requires_permission(self):
        manager = get_user_model().objects.create_user(username="no-close-day", role="GERENTE")
        with self.assertRaises(PermissionDenied):
            s.close_business_day(self.day, manager)

    def test_reopen_reason_permission_and_append_only_history(self):
        first_close = s.close_business_day(self.day, self.user)
        manager = get_user_model().objects.create_user(username="no-reopen", role="GERENTE")
        with self.assertRaises(PermissionDenied):
            s.reopen_business_day(first_close, manager, "Corrección")
        with self.assertRaises(ValidationError):
            s.reopen_business_day(first_close, self.user, " ")
        reopened = s.reopen_business_day(first_close, self.other_user, "Corrección uno")
        self.assertEqual(reopened.status, "OPEN")
        self.assertEqual(reopened.reopened_by, self.other_user)
        self.assertIsNone(reopened.closed_at)
        first_event = reopened.reopens.get()
        self.assertEqual(first_event.previous_closed_at, first_close.closed_at)
        self.assertEqual(first_event.previous_closed_by, self.user)
        s.close_business_day(reopened, self.user)
        s.reopen_business_day(reopened, self.user, "Corrección dos")
        self.assertEqual(reopened.reopens.count(), 2)
        self.assertTrue(AuditLog.objects.filter(action="cash.day_reopened").exists())

    def test_reopen_rejects_if_another_day_is_open(self):
        s.close_business_day(self.day, self.user)
        following = s.open_business_day(self.user, self.day.business_date + timedelta(days=1))
        with self.assertRaises(ValidationError):
            s.reopen_business_day(self.day, self.user, "Corrección")
        self.assertEqual(BusinessDay.objects.filter(status="OPEN").get(), following)

    def test_closed_commercial_date_cannot_be_opened_as_duplicate(self):
        s.close_business_day(self.day, self.user)
        with self.assertRaises(ValidationError):
            s.open_business_day(self.user, self.day.business_date)

    def test_financial_corruption_and_unreconciled_cash_block_close(self):
        session = self.session()
        order, _ = self.consumption(1)
        payment = self.payment(order, session=session)
        payments.close_order(order, self.user)
        self.close_session(session)
        Payment.objects.filter(pk=payment.pk).update(amount=26)
        types = {b["type"] for b in s.get_business_day_close_blockers(self.day)}
        self.assertIn("FINANCIAL_INCONSISTENCY", types)
        self.assertIn("CASH_INCONSISTENCY", types)
        with self.assertRaises(ValidationError):
            s.close_business_day(self.day, self.user)

    def test_legacy_order_not_inferred_and_must_be_explicitly_assigned(self):
        order, _ = self.consumption(1)
        TableOrder.objects.filter(pk=order.pk).update(business_day=None)
        order.refresh_from_db()
        self.assertIsNone(order.business_day)
        self.assertIn("UNASSIGNED_LEGACY_ORDER", {b["type"] for b in s.get_business_day_close_blockers(self.day)})
        with self.assertRaises(ValidationError):
            orders.update_order_note(order, "Cambio", self.user)
        with self.assertRaises(ValidationError):
            s.assign_legacy_order_to_day(order, self.day, self.user, " ")
        assigned = s.assign_legacy_order_to_day(order, self.day, self.user, "Regularización supervisada")
        self.assertEqual(assigned.business_day, self.day)
        with self.assertRaises(ValidationError):
            s.assign_legacy_order_to_day(order, self.day, self.user, "Otra")

    def test_reopened_day_allows_refund_with_new_session_without_changing_closed_session(self):
        session = self.session()
        order, _ = self.consumption(1)
        payment = self.payment(order, session=session)
        payments.close_order(order, self.user)
        self.close_session(session)
        s.close_business_day(self.day, self.user)
        s.reopen_business_day(self.day, self.user, "Reembolso autorizado")
        next_session = s.open_cash_session(session.register, self.user, D("100"), self.user)
        refund = payments.refund_payment(payment, self.user, amount=D("25"), reason="Devuelto")
        s.record_cash_refund(refund, next_session, self.user)
        self.assertEqual(s.get_expected_cash(session), D("125"))
        self.assertEqual(s.get_expected_cash(next_session), D("75"))
        session.refresh_from_db()
        self.assertEqual(session.status, "CLOSED")

    def test_summary_separates_gross_adjustments_refunds_and_methods(self):
        session = self.session("500")
        order, _ = self.consumption(8)  # Q200.
        payments.apply_order_adjustment(order, self.user, amount=D("20"), reason="Promoción")
        direct = self.payment(order, "50", session=session)
        waiter = self.payment(order, "20")
        s.confirm_cash_handoff(waiter, session, self.user)
        self.payment(order, "10")
        self.payment(order, "50", method="CARD")
        transfer = self.payment(order, "30", method="TRANSFER")
        payments.confirm_pending_payment(transfer, self.user)
        self.payment(order, "20", method="DEPOSIT")
        refund = payments.refund_payment(direct, self.user, amount=D("10"), reason="Compensación")
        s.record_cash_refund(refund, session, self.user)
        s.create_cash_withdrawal(session, D("40"), "Bóveda", self.user, self.user)
        self.close_session(session, "515", "Faltante Q5")
        summary = s.get_business_day_summary(self.day)
        self.assertEqual(summary["gross_sales"], D("200"))
        self.assertEqual(summary["adjustments"], D("20"))
        self.assertEqual(summary["refunds"], D("10"))
        self.assertEqual(summary["net_sales"], D("170"))
        self.assertEqual(summary["payments_by_method"]["CASH"], {"confirmed_gross": D("80"), "confirmed_net": D("70"), "refunds": D("10"), "pending": D("0")})
        self.assertEqual(summary["payments_by_method"]["CARD"]["confirmed_net"], D("50"))
        self.assertEqual(summary["payments_by_method"]["TRANSFER"]["confirmed_net"], D("30"))
        self.assertEqual(summary["pending_verification"], D("20"))
        self.assertEqual(summary["withdrawals"], D("40"))
        self.assertEqual(summary["cash_differences"], D("-5"))
        self.assertEqual(summary["sessions"], {"open": 0, "closed": 1})
        self.assertEqual(summary["handoffs"], {"pending": 1, "delivered": 1})
        self.assertEqual(summary["orders"], {"active": 1, "closed": 0})

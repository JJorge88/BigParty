from decimal import Decimal as D
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.management import call_command, CommandError
from django.db import IntegrityError, transaction

from apps.audit.models import AuditLog
from apps.cash import services as s
from apps.cash.models import CashRegister, CashSession, CashHandoff, CashMovement
from apps.payments import services as payments
from apps.payments.models import Payment
from apps.venues.models import Area
from .base import CashTestCase


class RegisterAndSessionTests(CashTestCase):
    def test_register_requires_area_and_unique_code(self):
        register = self.register()
        self.assertEqual(register.area, self.area)
        with self.assertRaises(ValidationError):
            self.register()
        with self.assertRaises(ValidationError):
            CashRegister.objects.create(name="Inválida", code="NOAREA")

    def test_seed_creates_exactly_three_and_is_idempotent(self):
        Area.objects.create(name="Discoteca", slug="discoteca")
        output = StringIO()
        call_command("seed_cash_defaults", stdout=output)
        call_command("seed_cash_defaults", stdout=output)
        self.assertEqual(CashRegister.objects.count(), 3)
        self.assertEqual(set(CashRegister.objects.values_list("code", "area__slug")), {("SPORT", "sport-bar"), ("DISCO", "discoteca"), ("PREMIUM", "premium")})
        register = CashRegister.objects.get(code="SPORT")
        register.name = "Nombre personalizado"
        register.save()
        call_command("seed_cash_defaults", stdout=output)
        register.refresh_from_db()
        self.assertEqual(register.name, "Nombre personalizado")

    def test_seed_missing_area_rolls_back_without_creating_areas(self):
        with self.assertRaises(CommandError):
            call_command("seed_cash_defaults", stdout=StringIO())
        self.assertFalse(CashRegister.objects.exists())
        self.assertEqual(Area.objects.count(), 2)

    def test_open_assigns_day_cashier_float_and_actor(self):
        session = s.open_cash_session(self.register(), self.other_user, D("500"), self.user)
        self.assertEqual(session.business_day, self.day)
        self.assertEqual(session.cashier, self.other_user)
        self.assertEqual(session.opened_by, self.user)
        self.assertEqual(session.opening_float, D("500"))
        self.assertEqual(s.get_expected_cash(session), D("500"))
        self.assertFalse(session.movements.exists())
        self.assertTrue(AuditLog.objects.filter(action="cash.session_opened").exists())

    def test_same_station_rejects_second_open_but_other_station_allowed(self):
        first = self.session()
        with self.assertRaises(ValidationError):
            s.open_cash_session(first.register, self.other_user, D("0"), self.user)
        second = self.session(register=self.register("DISCO"))
        self.assertNotEqual(first.pk, second.pk)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CashSession.objects.create(register=first.register, cashier=self.user, opened_by=self.user, business_day=self.day, opening_float=0)

    def test_open_needs_active_register_area_cashier(self):
        register = self.register()
        register.is_active = False
        register.save()
        with self.assertRaises(ValidationError):
            s.open_cash_session(register, self.user, D("0"), self.user)
        register.is_active = True
        register.save()
        self.user.is_active = False
        self.user.save()
        with self.assertRaises(ValidationError):
            s.open_cash_session(register, self.user, D("0"), self.other_user)
        self.user.is_active = True
        self.user.save()
        s.close_business_day(self.day, self.user)
        session = s.open_cash_session(register, self.user, D("0"), self.user)
        self.assertEqual(session.status, "OPEN")

    def test_open_permission_and_invalid_amounts(self):
        user = get_user_model().objects.create_user(username="no-perm", role="CAJERO")
        register = self.register()
        with self.assertRaises(PermissionDenied):
            s.open_cash_session(register, user, 0, user)
        for value in (-1, 0.1, "NaN", "1.001", True):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                s.open_cash_session(register, self.user, value, self.user)
        self.assertFalse(CashSession.objects.exists())

    def test_register_with_open_session_cannot_deactivate_or_change_identity(self):
        session = self.session()
        register = session.register
        register.is_active = False
        with self.assertRaises(ValidationError):
            register.save()
        register.refresh_from_db()
        register.area = self.other_area
        with self.assertRaises(ValidationError):
            register.save()
        self.close_session(session)
        register.refresh_from_db()
        register.is_active = False
        register.save()

    def test_same_station_can_open_next_shift_after_close(self):
        first = self.session("500")
        self.close_session(first)
        second = s.open_cash_session(first.register, self.other_user, D("100"), self.user)
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(first.register.sessions.count(), 2)
        self.assertEqual(s.get_expected_cash(first), D("500"))
        self.assertEqual(s.get_expected_cash(second), D("100"))


class PhysicalCashTests(CashTestCase):
    def test_direct_payment_creates_exactly_one_movement_atomically(self):
        session = self.session()
        order, _ = self.consumption()
        payment = self.payment(order, session=session)
        self.assertEqual(payment.cash_handoff_status, "NOT_REQUIRED")
        self.assertFalse(CashHandoff.objects.exists())
        movement = session.movements.get()
        self.assertEqual(movement.movement_type, "DIRECT_CASH_PAYMENT")
        self.assertEqual(movement.payment, payment)
        self.assertEqual(s.get_expected_cash(session), D("125"))
        retry = s.record_direct_cash_payment(payment, session, self.user)
        self.assertEqual(retry.pk, movement.pk)
        self.assertEqual(session.movements.count(), 1)

    def test_cashier_without_session_rejected(self):
        order, _ = self.consumption()
        self.user.role = "CAJERO"
        self.user.save()
        with self.assertRaises(ValidationError):
            self.payment(order)
        self.assertFalse(Payment.objects.exists())

    def test_waiter_cash_stays_outside_expected_until_received(self):
        session = self.session()
        order, _ = self.consumption()
        payment = self.payment(order)
        handoff = payment.cash_handoff
        self.assertEqual(handoff.status, "PENDING")
        self.assertIsNone(handoff.cash_session)
        self.assertEqual(handoff.waiter, self.user)
        self.assertEqual(s.get_expected_cash(session), D("100"))
        self.assertEqual(list(s.get_pending_cash_handoffs(day=self.day, waiter=self.user)), [handoff])
        delivered = s.confirm_cash_handoff(handoff, session, self.other_user)
        payment.refresh_from_db()
        self.assertEqual(payment.cash_handoff_status, "DELIVERED")
        self.assertEqual(delivered.status, "DELIVERED")
        self.assertEqual(delivered.received_by, self.other_user)
        self.assertEqual(delivered.cash_session, session)
        self.assertEqual(s.get_expected_cash(session), D("125"))
        self.assertEqual(payments.get_order_confirmed_paid_total(order), D("25"))
        self.assertEqual(Payment.objects.count(), 1)
        self.assertTrue(AuditLog.objects.filter(action="cash.handoff_received").exists())
        with self.assertRaises(ValidationError):
            s.confirm_cash_handoff(payment, session, self.user)

    def test_handoff_rejects_closed_missing_inactive_or_frozen_session(self):
        session = self.session()
        order, _ = self.consumption()
        payment = self.payment(order)
        with self.assertRaises(ValidationError):
            s.confirm_cash_handoff(payment, CashSession(pk=999999), self.user)
        CashRegister.objects.filter(pk=session.register_id).update(is_active=False)
        with self.assertRaises(ValidationError):
            s.confirm_cash_handoff(payment, session, self.user)
        CashRegister.objects.filter(pk=session.register_id).update(is_active=True)
        s.submit_blind_cash_count(session, D("100"), self.user)
        with self.assertRaises(ValidationError):
            s.confirm_cash_handoff(payment, session, self.user)
        s.close_cash_session(session, self.user)
        with self.assertRaises(ValidationError):
            s.confirm_cash_handoff(payment, session, self.user)
        payment.refresh_from_db()
        self.assertEqual(payment.cash_handoff_status, "PENDING")

    def test_wrong_method_and_permission_cannot_receive_handoff(self):
        session = self.session()
        order, _ = self.consumption()
        payment = self.payment(order, method="CARD")
        with self.assertRaises(ValidationError):
            s.confirm_cash_handoff(payment, session, self.user)
        user = get_user_model().objects.create_user(username="no-receive", role="CAJERO")
        with self.assertRaises(PermissionDenied):
            s.confirm_cash_handoff(payment, session, user)

    def test_cards_transfers_deposits_never_enter_cash(self):
        session = self.session()
        order, _ = self.consumption()
        for method in ("CARD", "TRANSFER", "DEPOSIT"):
            self.payment(order, method=method)
        self.assertEqual(s.get_expected_cash(session), D("100"))
        self.assertFalse(session.movements.exists())
        with self.assertRaises(ValidationError):
            self.payment(order, method="CARD", session=session)

    def test_direct_payment_failure_rolls_back_financial_payment(self):
        session = self.session()
        order, _ = self.consumption()
        self.close_session(session)
        with self.assertRaises(ValidationError):
            self.payment(order, session=session)
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(CashMovement.objects.exists())

    def test_handoff_late_failure_rolls_back_both_statuses_and_movement(self):
        session = self.session()
        order, _ = self.consumption()
        payment = self.payment(order)
        with patch("apps.cash.services._audit", side_effect=RuntimeError("failure")):
            with self.assertRaises(RuntimeError):
                s.confirm_cash_handoff(payment, session, self.user)
        payment.refresh_from_db()
        self.assertEqual(payment.cash_handoff_status, "PENDING")
        self.assertEqual(payment.cash_handoff.status, "PENDING")
        self.assertFalse(CashMovement.objects.exists())

    def test_withdrawal_records_requester_approver_reason_and_reduces_cash(self):
        session = self.session()
        movement = s.create_cash_withdrawal(session, D("40"), "Depósito en bóveda", self.user, self.other_user)
        self.assertEqual(movement.created_by, self.user)
        self.assertEqual(movement.approved_by, self.other_user)
        self.assertEqual(s.get_expected_cash(session), D("60"))
        self.assertFalse(Payment.objects.exists())
        self.assertTrue(AuditLog.objects.filter(action="cash.withdrawal").exists())

    def test_withdrawal_needs_reason_amount_permission_and_available_funds(self):
        session = self.session()
        approver = get_user_model().objects.create_user(username="manager-no-approval", role="GERENTE")
        with self.assertRaises(PermissionDenied):
            s.create_cash_withdrawal(session, 1, "Motivo", self.user, approver)
        for amount, reason in [(0, "Motivo"), (-1, "Motivo"), (101, "Motivo"), (1, " ")]:
            with self.subTest(amount=amount, reason=reason), self.assertRaises(ValidationError):
                s.create_cash_withdrawal(session, amount, reason, self.user, self.other_user)
        self.assertFalse(CashMovement.objects.exists())

    def test_physical_refund_is_explicit_and_does_not_duplicate_financial_refund(self):
        session = self.session()
        order, _ = self.consumption()
        payment = self.payment(order, session=session)
        refund = payments.refund_payment(payment, self.user, amount=D("10"), reason="Devolución")
        self.assertEqual(s.get_expected_cash(session), D("125"))
        movement = s.record_cash_refund(refund, session, self.user)
        self.assertEqual(s.get_expected_cash(session), D("115"))
        self.assertEqual(movement.refund, refund)
        self.assertEqual(s.record_cash_refund(refund, session, self.user).pk, movement.pk)
        self.assertEqual(payment.refunds.count(), 1)
        self.assertEqual(payment.amount, D("25"))
        other = self.session(register=self.register("OTHER"))
        with self.assertRaises(ValidationError):
            s.record_cash_refund(refund, other, self.user)

    def test_refund_rejects_non_cash_and_insufficient_physical_funds(self):
        session = self.session("0")
        order, _ = self.consumption()
        card = self.payment(order, method="CARD")
        refund = payments.refund_payment(card, self.user, amount=D("10"), reason="Devolución")
        with self.assertRaises(ValidationError):
            s.record_cash_refund(refund, session, self.user)
        cash = self.payment(order, session=session)
        refund = payments.refund_payment(cash, self.user, amount=D("25"), reason="Devolución")
        s.create_cash_withdrawal(session, 25, "Retiro", self.user, self.user)
        with self.assertRaises(ValidationError):
            s.record_cash_refund(refund, session, self.user)

    def test_pending_waiter_cash_must_be_received_before_financial_refund(self):
        session = self.session()
        order, _ = self.consumption()
        payment = self.payment(order)
        with self.assertRaises(ValidationError):
            payments.refund_payment(payment, self.user, amount=D("25"), reason="Devolución")
        s.confirm_cash_handoff(payment, session, self.user)
        refund = payments.refund_payment(payment, self.user, amount=D("25"), reason="Devolución")
        s.record_cash_refund(refund, session, self.user)
        self.assertEqual(s.get_expected_cash(session), D("100"))

    def test_expected_cash_combines_only_physical_movements(self):
        session = self.session("500")
        order, _ = self.consumption(20)
        direct = self.payment(order, "200", session=session)
        waiter = self.payment(order, "100")
        s.confirm_cash_handoff(waiter, session, self.user)
        self.payment(order, "50")  # Aún en manos del mesero.
        self.payment(order, "50", method="CARD")
        s.create_cash_withdrawal(session, D("75"), "Bóveda", self.user, self.user)
        refund = payments.refund_payment(direct, self.user, amount=D("25"), reason="Devolución")
        s.record_cash_refund(refund, session, self.user)
        self.assertEqual(s.get_expected_cash(session), D("700"))
        summary = s.get_cash_session_summary(session)
        self.assertEqual(summary["direct_cash_receipts"], D("200"))
        self.assertEqual(summary["waiter_handoffs"], D("100"))
        self.assertEqual(summary["withdrawals"], D("75"))
        self.assertEqual(summary["cash_refunds"], D("25"))
        self.assertIsNone(summary["difference"])


class BlindClosingTests(CashTestCase):
    def test_count_returns_only_submitted_data_then_reveals_result(self):
        session = self.session("500")
        with self.assertRaises(ValidationError):
            s.get_blind_close_result(session, self.user)
        result = s.submit_blind_cash_count(session, D("480"), self.user)
        self.assertNotIn("expected_cash", result)
        self.assertNotIn("difference", result)
        self.assertEqual(result["counted_cash"], D("480"))
        result = s.get_blind_close_result(session, self.user)
        self.assertEqual(result, {"counted_cash": D("480"), "expected_cash": D("500"), "difference": D("-20")})
        with self.assertRaises(ValidationError):
            s.submit_blind_cash_count(session, D("500"), self.user)

    def test_exact_close_does_not_require_reason(self):
        session = self.session()
        closed = self.close_session(session)
        self.assertEqual(closed.status, "CLOSED")
        self.assertEqual(closed.difference, D("0"))
        self.assertEqual(closed.closed_by, self.user)
        self.assertIsNotNone(closed.closed_at)
        self.assertTrue(AuditLog.objects.filter(action="cash.blind_count_submitted").exists())
        self.assertTrue(AuditLog.objects.filter(action="cash.session_closed").exists())

    def test_shortage_and_overage_require_reason(self):
        for index, counted in enumerate((D("80"), D("120"))):
            session = self.session(register=self.register(f"CASE{index}"))
            s.submit_blind_cash_count(session, counted, self.user)
            with self.assertRaises(ValidationError):
                s.close_cash_session(session, self.user)
            closed = s.close_cash_session(session, self.user, "Diferencia investigada")
            self.assertEqual(closed.difference, counted - D("100"))

    def test_cannot_close_without_count_or_count_negative(self):
        session = self.session()
        with self.assertRaises(ValidationError):
            s.close_cash_session(session, self.user)
        with self.assertRaises(ValidationError):
            s.submit_blind_cash_count(session, -1, self.user)
        session.refresh_from_db()
        self.assertIsNone(session.counted_cash)

    def test_count_freezes_movements_and_closed_records_are_immutable(self):
        session = self.session()
        order, _ = self.consumption()
        payment = self.payment(order)
        s.submit_blind_cash_count(session, D("100"), self.user)
        operations = [lambda: self.payment(order, session=session),
                      lambda: s.confirm_cash_handoff(payment, session, self.user),
                      lambda: s.create_cash_withdrawal(session, 1, "Retiro", self.user, self.user)]
        for operation in operations:
            with self.assertRaises(ValidationError):
                operation()
        s.close_cash_session(session, self.user)
        with self.assertRaises(ValidationError):
            s.close_cash_session(session, self.user)
        with self.assertRaises(ValidationError):
            s.submit_blind_cash_count(session, D("99"), self.user)

    def test_pending_waiter_money_does_not_block_individual_session_close(self):
        session = self.session()
        order, _ = self.consumption()
        self.payment(order)
        self.close_session(session)
        self.assertTrue(s.get_pending_cash_handoffs().exists())

    def test_delivered_money_missing_movement_blocks_count_and_close(self):
        session = self.session()
        order, _ = self.consumption()
        payment = self.payment(order)
        handoff = s.confirm_cash_handoff(payment, session, self.user)
        handoff.movement.delete()  # Simula corrupción externa, no una operación soportada.
        with self.assertRaises(ValidationError):
            s.submit_blind_cash_count(session, D("125"), self.user)
        self.assertIn("CASH_INCONSISTENCY", {b["type"] for b in s.get_business_day_close_blockers(self.day)})

    def test_tampering_after_count_is_detected_before_close(self):
        session = self.session()
        s.create_cash_withdrawal(session, 10, "Retiro", self.user, self.user)
        s.submit_blind_cash_count(session, D("90"), self.user)
        session.movements.update(amount=20)
        with self.assertRaises(ValidationError):
            s.close_cash_session(session, self.user)
        session.refresh_from_db()
        self.assertEqual(session.status, "OPEN")

    def test_count_and_result_require_explicit_close_permission(self):
        session = self.session()
        cashier = get_user_model().objects.create_user(username="no-count-perm", role="CAJERO")
        with self.assertRaises(PermissionDenied):
            s.submit_blind_cash_count(session, D("100"), cashier)
        s.submit_blind_cash_count(session, D("100"), self.user)
        with self.assertRaises(PermissionDenied):
            s.get_blind_close_result(session, cashier)
        with self.assertRaises(PermissionDenied):
            s.close_cash_session(session, cashier)

    def test_cash_refund_permission_is_separate_from_financial_refund(self):
        session = self.session()
        order, _ = self.consumption()
        payment = self.payment(order, session=session)
        refund = payments.refund_payment(payment, self.user, amount=D("10"), reason="Devolución")
        user = get_user_model().objects.create_user(username="no-physical-refund", role="GERENTE")
        user.user_permissions.add(Permission.objects.get(codename="refund_payment", content_type__app_label="payments"))
        with self.assertRaises(PermissionDenied):
            s.record_cash_refund(refund, session, user)
        self.assertFalse(CashMovement.objects.filter(refund=refund).exists())

    def test_other_cashier_cannot_directly_use_another_cashiers_session(self):
        session = self.session()
        order, _ = self.consumption()
        user = get_user_model().objects.create_user(username="other-cashier", role="CAJERO")
        user.user_permissions.add(Permission.objects.get(codename="record_payment", content_type__app_label="payments"))
        with self.assertRaises(ValidationError):
            payments.create_amount_payment(order, D("25"), "CASH", user, cash_session=session)
        self.assertFalse(Payment.objects.exists())

    def test_inactive_area_cannot_open_a_session(self):
        register = self.register()
        self.area.is_active = False
        self.area.save()
        with self.assertRaises(ValidationError):
            s.open_cash_session(register, self.user, 0, self.user)

    def test_database_blocks_duplicate_incoming_movement(self):
        session = self.session()
        order, _ = self.consumption()
        payment = self.payment(order, session=session)
        with self.assertRaises(IntegrityError), transaction.atomic():
            CashMovement.objects.create(cash_session=session, movement_type="DIRECT_CASH_PAYMENT", payment=payment, amount=25, created_by=self.user)

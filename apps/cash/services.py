from datetime import date
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.orders.models import TableOrder
from apps.payments.models import Payment, PaymentRefund
from .guards import lock_operation_gate, lock_open_day, lock_order_day
from .models import BusinessDay, BusinessDayReopen, CashRegister, CashSession, CashHandoff, CashMovement
from .queries import (ZERO, get_expected_cash, get_pending_cash_handoffs, get_cash_session_summary,
                      get_session_integrity_errors, get_business_day_close_blockers, can_close_business_day, get_business_day_summary)


def _require(user, permission):
    if user is None or not user.is_active or not user.has_perm("cash." + permission):
        raise PermissionDenied("No tienes permiso para esta operación de caja/jornada.")


def _money(value, *, zero=False):
    if isinstance(value, (float, bool)):
        raise ValidationError("Usa un importe decimal exacto.")
    try:
        value = Decimal(value)
        if not value.is_finite() or value < ZERO or (value == ZERO and not zero) or value > Decimal("999999999999.99") or value != value.quantize(Decimal("0.01")):
            raise ValueError
        return value.quantize(Decimal("0.01"))
    except (ValueError, TypeError, InvalidOperation):
        raise ValidationError("Importe inválido; usa como máximo dos decimales y un valor no negativo.")


def _reason(value):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError("Indica el motivo de la operación.")
    return value.strip()


def _audit(entity, user, action, **data):
    AuditLog.objects.create(user=user, action="cash." + action, entity=entity._meta.label_lower, entity_id=str(entity.pk), data=data)


def _save(obj):
    obj.full_clean()
    obj.save()
    return obj


def _session(session, *, receiving=False):
    day_id = CashSession.objects.filter(pk=getattr(session, "pk", None)).values_list("business_day_id", flat=True).first()
    if day_id is None:
        raise ValidationError("La sesión de caja no existe.")
    lock_open_day(day_id)
    current = CashSession.objects.select_for_update().get(pk=session.pk)
    if current.status != "OPEN":
        raise ValidationError("La sesión de caja está cerrada.")
    if receiving:
        if current.counted_at:
            raise ValidationError("El conteo ya fue presentado; la caja está congelada hasta finalizar su cierre.")
        if not current.register.is_active or not current.register.area.is_active:
            raise ValidationError("La caja y su área deben estar activas.")
    return current


@transaction.atomic
def open_business_day(user, business_date=None):
    _require(user, "open_business_day")
    lock_operation_gate()
    business_date = business_date or timezone.localdate()
    if type(business_date) is not date:
        raise ValidationError("La fecha comercial debe ser una fecha válida.")
    if BusinessDay.objects.filter(status="OPEN").exists():
        raise ValidationError("Ya existe una jornada abierta.")
    if BusinessDay.objects.filter(business_date=business_date).exists():
        raise ValidationError("Esa fecha comercial ya existe; utiliza la reapertura autorizada.")
    day = _save(BusinessDay(business_date=business_date, opened_by=user))
    _audit(day, user, "day_opened", business_date=business_date.isoformat())
    return day


@transaction.atomic
def open_cash_session(register, cashier, opening_float, user):
    _require(user, "open_cash_session")
    day = lock_open_day()
    register = CashRegister.objects.select_for_update().get(pk=register.pk)
    cashier.refresh_from_db()
    if not register.is_active or not register.area.is_active or not cashier.is_active:
        raise ValidationError("Caja, área y cajero deben estar activos.")
    if register.sessions.filter(status="OPEN").exists():
        raise ValidationError("Esta estación ya tiene una sesión abierta.")
    session = _save(CashSession(business_day=day, register=register, cashier=cashier, opened_by=user, opening_float=_money(opening_float, zero=True)))
    _audit(session, user, "session_opened", cashier_id=cashier.pk, opening_float=str(session.opening_float), day_id=day.pk)
    return session


@transaction.atomic
def create_pending_handoff(payment):
    lock_order_day(payment.order_id)
    current = Payment.objects.select_for_update().get(pk=payment.pk)
    if current.method != "CASH" or current.status != "CONFIRMED" or current.cash_handoff_status != "PENDING":
        raise ValidationError("El pago no corresponde a efectivo pendiente de mesero.")
    handoff, created = CashHandoff.objects.get_or_create(payment=current, defaults={"waiter": current.recorded_by, "amount": current.amount})
    if handoff.amount != current.amount or handoff.waiter_id != current.recorded_by_id or handoff.status != "PENDING":
        raise ValidationError("La entrega y el pago no coinciden.")
    if created:
        _audit(handoff, current.recorded_by, "handoff_pending", payment_id=current.pk, order_id=current.order_id)
    return handoff


@transaction.atomic
def record_direct_cash_payment(payment, cash_session, user):
    # Se llama en la misma transacción que crea Payment. Reintentar el mismo pago no duplica el ingreso.
    if not user.is_active or not user.has_perm("payments.record_payment"):
        raise PermissionDenied("No tienes permiso para registrar pagos.")
    day = lock_order_day(payment.order_id)
    current = Payment.objects.select_for_update().get(pk=payment.pk)
    existing = current.cash_movements.filter(movement_type__in=["DIRECT_CASH_PAYMENT", "WAITER_HANDOFF"]).first()
    if existing:
        if existing.movement_type == "DIRECT_CASH_PAYMENT" and existing.cash_session_id == cash_session.pk:
            return existing
        raise ValidationError("El pago ya fue recibido en otra operación de caja.")
    session = _session(cash_session, receiving=True)
    if session.business_day_id != day.pk or (session.cashier_id != user.pk and not user.is_superuser):
        raise ValidationError("Selecciona una sesión de tu cajero en la jornada de la cuenta.")
    if current.method != "CASH" or current.status != "CONFIRMED" or current.cash_handoff_status != "NOT_REQUIRED" or CashHandoff.objects.filter(payment=current).exists():
        raise ValidationError("El pago no es un cobro directo en efectivo.")
    movement = _save(CashMovement(cash_session=session, movement_type="DIRECT_CASH_PAYMENT", amount=current.amount, payment=current, created_by=user))
    _audit(movement, user, "direct_cash_payment", payment_id=current.pk, session_id=session.pk, amount=str(current.amount))
    return movement


@transaction.atomic
def confirm_cash_handoff(payment, cash_session, user):
    _require(user, "receive_waiter_cash")
    if isinstance(payment, CashHandoff):
        payment = payment.payment
    day = lock_order_day(payment.order_id)
    current = Payment.objects.select_for_update().get(pk=payment.pk)
    if current.method != "CASH" or current.status != "CONFIRMED" or current.cash_handoff_status != "PENDING":
        raise ValidationError("El pago no está pendiente de entrega de efectivo.")
    session = _session(cash_session, receiving=True)
    if session.business_day_id != day.pk:
        raise ValidationError("La entrega debe pertenecer a la misma jornada de la caja.")
    handoff = create_pending_handoff(current)
    if current.cash_movements.filter(movement_type__in=["DIRECT_CASH_PAYMENT", "WAITER_HANDOFF"]).exists():
        raise ValidationError("Este pago ya tiene recepción física.")
    handoff.cash_session, handoff.status = session, "DELIVERED"
    handoff.received_by, handoff.received_at = user, timezone.now()
    handoff.metadata = {"order_id": current.order_id, "table_id": current.order.primary_table_id}
    _save(handoff)
    current.cash_handoff_status = "DELIVERED"
    current.save(update_fields=["cash_handoff_status"])
    movement = _save(CashMovement(cash_session=session, movement_type="WAITER_HANDOFF", amount=handoff.amount,
                                  payment=current, handoff=handoff, created_by=user))
    _audit(handoff, user, "handoff_received", payment_id=current.pk, waiter_id=handoff.waiter_id,
           session_id=session.pk, amount=str(handoff.amount), movement_id=movement.pk, **handoff.metadata)
    return handoff


@transaction.atomic
def create_cash_withdrawal(cash_session, amount, reason, requested_by, approved_by):
    # approved_by es el actor autenticado que ejecuta/aprueba; requested_by solo identifica al solicitante.
    _require(approved_by, "approve_cash_withdrawal")
    requested_by.refresh_from_db()
    if not requested_by.is_active:
        raise ValidationError("El solicitante debe estar activo.")
    amount, reason = _money(amount), _reason(reason)
    session = _session(cash_session, receiving=True)
    if amount > get_expected_cash(session):
        raise ValidationError("No se puede registrar el retiro solicitado: fondos insuficientes.")
    movement = _save(CashMovement(cash_session=session, movement_type="WITHDRAWAL", amount=amount,
        reason=reason, created_by=requested_by, approved_by=approved_by))
    _audit(movement, approved_by, "withdrawal", requested_by=requested_by.pk, session_id=session.pk, amount=str(amount), reason=reason)
    return movement


@transaction.atomic
def record_cash_refund(refund, cash_session, user):
    _require(user, "record_cash_refund")
    refund = PaymentRefund.objects.select_related("payment").get(pk=refund.pk)
    day = lock_order_day(refund.payment.order_id)
    existing = CashMovement.objects.filter(refund=refund).first()
    if existing:
        if existing.cash_session_id == cash_session.pk:
            return existing
        raise ValidationError("El reembolso ya tiene una salida física registrada.")
    session = _session(cash_session, receiving=True)
    if refund.payment.method != "CASH" or session.business_day_id != day.pk:
        raise ValidationError("Solo se registra la salida de un reembolso de efectivo de la misma jornada.")
    if refund.amount > get_expected_cash(session):
        raise ValidationError("No se puede registrar la salida: fondos insuficientes.")
    movement = _save(CashMovement(cash_session=session, movement_type="CASH_REFUND", amount=refund.amount,
        reason=refund.reason, created_by=user, refund=refund, payment=refund.payment))
    _audit(movement, user, "cash_refund", refund_id=refund.pk, session_id=session.pk, amount=str(refund.amount))
    return movement


@transaction.atomic
def submit_blind_cash_count(session, counted_cash, user):
    _require(user, "close_cash_session")
    current = _session(session)
    if current.counted_at:
        raise ValidationError("El conteo ya fue presentado y no se puede sustituir.")
    errors = get_session_integrity_errors(current)
    if errors:
        raise ValidationError(errors)
    current.counted_cash = _money(counted_cash, zero=True)
    current.counted_by, current.counted_at = user, timezone.now()
    current.expected_cash_at_close = get_expected_cash(current)
    current.difference = current.counted_cash - current.expected_cash_at_close
    _save(current)
    _audit(current, user, "blind_count_submitted", counted_cash=str(current.counted_cash))
    return {"session_id": current.pk, "counted_cash": current.counted_cash, "submitted_at": current.counted_at}


def get_blind_close_result(session, user):
    _require(user, "close_cash_session")
    current = CashSession.objects.get(pk=session.pk)
    if not current.counted_at:
        raise ValidationError("Registra primero el conteo ciego.")
    return {"counted_cash": current.counted_cash, "expected_cash": current.expected_cash_at_close, "difference": current.difference}


@transaction.atomic
def close_cash_session(session, user, reason=""):
    _require(user, "close_cash_session")
    current = _session(session)
    if not current.counted_at:
        raise ValidationError("Debes presentar el conteo ciego antes de cerrar.")
    errors = get_session_integrity_errors(current)
    if errors:
        raise ValidationError(errors)
    expected = get_expected_cash(current)
    difference = current.counted_cash - expected
    if difference:
        reason = _reason(reason)
    elif not isinstance(reason, str):
        raise ValidationError("El motivo debe ser texto.")
    current.expected_cash_at_close, current.difference = expected, difference
    current.closing_reason, current.closed_by, current.closed_at, current.status = reason.strip(), user, timezone.now(), "CLOSED"
    _save(current)
    _audit(current, user, "session_closed", expected=str(expected), counted=str(current.counted_cash), difference=str(difference), reason=reason)
    return current


@transaction.atomic
def close_business_day(day, user):
    _require(user, "close_business_day")
    current = lock_open_day(day.pk)
    blockers = get_business_day_close_blockers(current)
    if blockers:
        raise ValidationError([blocker["description"] for blocker in blockers])
    current.status, current.closed_at, current.closed_by = "CLOSED", timezone.now(), user
    _save(current)
    _audit(current, user, "day_closed", business_date=current.business_date.isoformat())
    return current


@transaction.atomic
def reopen_business_day(day, user, reason):
    _require(user, "reopen_business_day")
    reason = _reason(reason)
    lock_operation_gate()
    current = BusinessDay.objects.select_for_update().get(pk=day.pk)
    if current.status != "CLOSED" or BusinessDay.objects.filter(status="OPEN").exists():
        raise ValidationError("La jornada debe estar cerrada y no debe existir otra abierta.")
    event = _save(BusinessDayReopen(business_day=current, reopened_by=user, reason=reason,
        previous_closed_at=current.closed_at, previous_closed_by=current.closed_by))
    current.status, current.closed_at, current.closed_by = "OPEN", None, None
    current.reopened_at, current.reopened_by, current.reopen_reason = event.reopened_at, user, reason
    _save(current)
    _audit(current, user, "day_reopened", reason=reason, reopen_id=event.pk)
    return current


@transaction.atomic
def assign_legacy_order_to_day(order, day, user, reason):
    """Regularización explícita; nunca infiere una jornada por fecha histórica."""
    _require(user, "open_business_day")
    reason = _reason(reason)
    current_day = lock_open_day(day.pk)
    current = TableOrder.objects.select_for_update().get(pk=order.pk)
    if current.business_day_id is not None:
        raise ValidationError("La cuenta ya tiene jornada; no puede reasignarse.")
    current.business_day = current_day
    current.save(update_fields=["business_day", "updated_at"])
    for payment in current.payments.filter(method="CASH", status="CONFIRMED", cash_handoff_status="PENDING"):
        create_pending_handoff(payment)
    _audit(current, user, "legacy_order_assigned", day_id=current_day.pk, reason=reason)
    return current

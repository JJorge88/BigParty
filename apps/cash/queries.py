"""Consultas internas; las vistas controlan qué información financiera pueden revelar."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Sum, Q

from apps.orders.models import ACTIVE_STATUSES, TableOrder
from apps.payments.models import Payment
from apps.payments.queries import get_financial_summary
from .models import BusinessDay, CashSession, CashMovement, CashHandoff

ZERO = Decimal("0.00")
INCOMING = ("DIRECT_CASH_PAYMENT", "WAITER_HANDOFF")


def get_expected_cash(session):
    session = CashSession.objects.get(pk=session.pk)
    totals = {row["movement_type"]: row["total"] for row in session.movements.values("movement_type").annotate(total=Sum("amount"))}
    return (session.opening_float + totals.get("DIRECT_CASH_PAYMENT", ZERO) + totals.get("WAITER_HANDOFF", ZERO)
            - totals.get("WITHDRAWAL", ZERO) - totals.get("CASH_REFUND", ZERO))


def get_pending_cash_handoffs(*, day=None, waiter=None):
    rows = CashHandoff.objects.filter(status="PENDING").select_related("waiter", "payment__order__primary_table")
    if day is not None:
        rows = rows.filter(payment__order__business_day=day)
    if waiter is not None:
        rows = rows.filter(waiter=waiter)
    return rows.order_by("created_at", "pk")


def get_cash_session_summary(session):
    session = CashSession.objects.select_related("register", "cashier").get(pk=session.pk)
    totals = {row["movement_type"]: row["total"] for row in session.movements.values("movement_type").annotate(total=Sum("amount"))}
    return {"id": session.pk, "register": session.register.name, "cashier": session.cashier.get_username(),
            "opening_float": session.opening_float, "direct_cash_receipts": totals.get("DIRECT_CASH_PAYMENT", ZERO),
            "waiter_handoffs": totals.get("WAITER_HANDOFF", ZERO), "withdrawals": totals.get("WITHDRAWAL", ZERO),
            "cash_refunds": totals.get("CASH_REFUND", ZERO), "expected_cash": get_expected_cash(session),
            "counted_cash": session.counted_cash if session.status == "CLOSED" else None,
            "difference": session.difference if session.status == "CLOSED" else None,
            "opened_at": session.opened_at, "closed_at": session.closed_at, "status": session.status}


def get_session_integrity_errors(session):
    errors = []
    for movement in session.movements.select_related("payment__order", "handoff", "refund"):
        if movement.payment_id and (movement.payment.method != "CASH" or movement.payment.order.business_day_id != session.business_day_id):
            errors.append(f"Movimiento #{movement.pk}: pago o jornada incompatible")
        if movement.movement_type in INCOMING:
            if movement.amount != movement.payment.amount or movement.payment.status not in ("CONFIRMED", "REFUNDED"):
                errors.append(f"Movimiento #{movement.pk}: monto/estado del pago inconsistente")
        if movement.movement_type == "DIRECT_CASH_PAYMENT" and movement.payment.cash_handoff_status != "NOT_REQUIRED":
            errors.append(f"Movimiento #{movement.pk}: entrega incompatible con cobro directo")
        if movement.movement_type == "WAITER_HANDOFF":
            handoff = movement.handoff
            if (handoff.status != "DELIVERED" or handoff.cash_session_id != session.pk or handoff.payment_id != movement.payment_id
                or handoff.amount != movement.amount or movement.payment.cash_handoff_status != "DELIVERED"):
                errors.append(f"Movimiento #{movement.pk}: entrega inconsistente")
        if movement.movement_type == "CASH_REFUND" and (movement.refund.amount != movement.amount or movement.refund.payment_id != movement.payment_id):
            errors.append(f"Movimiento #{movement.pk}: reembolso inconsistente")
    for handoff in session.handoffs.all():
        if handoff.status != "DELIVERED" or not session.movements.filter(handoff=handoff, movement_type="WAITER_HANDOFF").exists():
            errors.append(f"Entrega #{handoff.pk}: falta el movimiento de recepción")
    expected = get_expected_cash(session)
    if expected < ZERO:
        errors.append("Efectivo esperado negativo")
    if session.counted_at and (session.expected_cash_at_close != expected or session.difference != session.counted_cash - expected):
        errors.append("El conteo no coincide con el libro de movimientos congelado")
    return errors


def get_business_day_close_blockers(day):
    from apps.payments.services import _assert_ledger
    day = BusinessDay.objects.get(pk=day.pk)
    blockers = []
    def add(kind, description, pk):
        blockers.append({"type": kind, "description": description, "object_id": pk})
    legacy = TableOrder.objects.filter(business_day__isnull=True).filter(
        Q(status__in=ACTIVE_STATUSES) | Q(payments__status="PENDING") | Q(payments__cash_handoff_status="PENDING")
    ).distinct()
    for order in legacy:
        add("UNASSIGNED_LEGACY_ORDER", f"{order}: requiere asignación explícita a una jornada antes de liquidar sus pendientes", order.pk)
    for order in day.orders.select_related("primary_table"):
        if order.status in ACTIVE_STATUSES:
            add("ACTIVE_ORDER", f"{order} · {order.primary_table} continúa activa", order.pk)
        summary = get_financial_summary(order)
        if summary["outstanding_balance"] != ZERO:
            add("OUTSTANDING_BALANCE", f"{order} tiene saldo Q{summary['outstanding_balance']}", order.pk)
        try:
            _assert_ledger(order)
        except ValidationError as exc:
            add("FINANCIAL_INCONSISTENCY", f"{order}: {' '.join(exc.messages)}", order.pk)
        if order.status not in ACTIVE_STATUSES and order.table_links.filter(released_at__isnull=True).exists():
            add("FINANCIAL_INCONSISTENCY", f"{order}: conserva vínculos activos tras finalizar", order.pk)
    for payment in Payment.objects.filter(order__business_day=day, status="PENDING"):
        add("PENDING_PAYMENT", f"Pago #{payment.pk} de {payment.order}: pendiente de verificar", payment.pk)
    for session in day.cash_sessions.all():
        if session.status == "OPEN":
            add("OPEN_CASH_SESSION", f"{session.register.name} continúa abierta (sesión #{session.pk})", session.pk)
        for error in get_session_integrity_errors(session):
            add("CASH_INCONSISTENCY", error, session.pk)
    for handoff in get_pending_cash_handoffs(day=day):
        add("PENDING_HANDOFF", f"{handoff.waiter}: entrega del pago #{handoff.payment_id} pendiente", handoff.pk)
    for payment in Payment.objects.filter(order__business_day=day, method="CASH"):
        handoff = CashHandoff.objects.filter(payment=payment).first()
        incoming = payment.cash_movements.filter(movement_type__in=INCOMING).first()
        if payment.cash_handoff_status == "NOT_REQUIRED":
            consistent = incoming is not None and incoming.movement_type == "DIRECT_CASH_PAYMENT" and handoff is None
        else:
            consistent = handoff is not None and handoff.amount == payment.amount and handoff.waiter_id == payment.recorded_by_id and handoff.status == payment.cash_handoff_status
            if payment.cash_handoff_status == "DELIVERED":
                consistent = consistent and incoming is not None and incoming.handoff_id == handoff.pk
            else:
                consistent = consistent and incoming is None and payment.status == "CONFIRMED"
        if incoming and incoming.cash_session.business_day_id != day.pk:
            consistent = False
        if not consistent:
            add("CASH_INCONSISTENCY", f"Pago #{payment.pk}: su recepción física no está conciliada", payment.pk)
    return blockers


def can_close_business_day(day):
    return BusinessDay.objects.filter(pk=day.pk, status="OPEN").exists() and not get_business_day_close_blockers(day)


def get_business_day_summary(day):
    day = BusinessDay.objects.get(pk=day.pk)
    totals = {key: ZERO for key in ("gross_sales", "adjustments", "refunds", "net_sales")}
    for order in day.orders.all():
        summary = get_financial_summary(order)
        for key, source in (("gross_sales", "gross_total"), ("adjustments", "adjustments"), ("refunds", "refunds"), ("net_sales", "charge_total")):
            totals[key] += summary[source]
    methods = {}
    for method in Payment.Method.values:
        payments = Payment.objects.filter(order__business_day=day, method=method)
        confirmed = payments.filter(status__in=["CONFIRMED", "REFUNDED"]).aggregate(total=Sum("amount"))["total"] or ZERO
        refunds = sum((p.refunds.aggregate(total=Sum("amount"))["total"] or ZERO for p in payments), ZERO)
        methods[method] = {"confirmed_gross": confirmed, "refunds": refunds, "confirmed_net": confirmed - refunds,
                           "pending": payments.filter(status="PENDING").aggregate(total=Sum("amount"))["total"] or ZERO}
    sessions = day.cash_sessions.all()
    handoffs = CashHandoff.objects.filter(payment__order__business_day=day)
    return {"business_date": day.business_date, "status": day.status, **totals, "payments_by_method": methods,
            "sessions": {"open": sessions.filter(status="OPEN").count(), "closed": sessions.filter(status="CLOSED").count()},
            "cash_differences": sessions.filter(status="CLOSED").aggregate(total=Sum("difference"))["total"] or ZERO,
            "withdrawals": CashMovement.objects.filter(cash_session__business_day=day, movement_type="WITHDRAWAL").aggregate(total=Sum("amount"))["total"] or ZERO,
            "cash_refunds": CashMovement.objects.filter(cash_session__business_day=day, movement_type="CASH_REFUND").aggregate(total=Sum("amount"))["total"] or ZERO,
            "handoffs": {"pending": handoffs.filter(status="PENDING").count(), "delivered": handoffs.filter(status="DELIVERED").count()},
            "orders": {"active": day.orders.filter(status__in=ACTIVE_STATUSES).count(), "closed": day.orders.filter(status="CLOSED").count()},
            "pending_verification": Payment.objects.filter(order__business_day=day, status="PENDING").aggregate(total=Sum("amount"))["total"] or ZERO}

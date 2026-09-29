"""Consultas internas; las vistas controlan qué información financiera pueden revelar."""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Sum, Q, Prefetch

from apps.orders.models import ACTIVE_STATUSES, TableOrder
from apps.payments.models import Payment
from apps.payments.queries import get_financial_summary, prefetch_financials, summarize_payment_methods
from .models import BusinessDay, CashSession, CashMovement, CashHandoff

ZERO = Decimal("0.00")
INCOMING = ("DIRECT_CASH_PAYMENT", "WAITER_HANDOFF")


def _movement_totals(session):
    if hasattr(session, '_ledger_movements'):
        totals = {}
        for movement in session._ledger_movements:
            totals[movement.movement_type] = totals.get(movement.movement_type, ZERO) + movement.amount
        return totals
    return {row['movement_type']:row['total'] for row in session.movements.values('movement_type').annotate(total=Sum('amount'))}


def get_expected_cash(session):
    if not hasattr(session, '_ledger_movements'):
        session = CashSession.objects.get(pk=session.pk)
    totals = _movement_totals(session)
    return (session.opening_float + totals.get("DIRECT_CASH_PAYMENT", ZERO) + totals.get("WAITER_HANDOFF", ZERO)
            - totals.get("WITHDRAWAL", ZERO) - totals.get("CASH_REFUND", ZERO))


def cash_sessions_for_day(day):
    return list(day.cash_sessions.select_related('register__area', 'cashier', 'closed_by').prefetch_related(
        Prefetch('movements', queryset=CashMovement.objects.select_related('payment__order', 'handoff', 'refund').order_by('created_at','pk'), to_attr='_ledger_movements'),
        Prefetch('handoffs', queryset=CashHandoff.objects.all(), to_attr='_ledger_handoffs')))


def get_business_day_snapshot(day):
    """Lectura por lotes, transitoria; no usar el snapshot para autorizar escrituras."""
    orders = prefetch_financials(day.orders.select_related('primary_table', 'area').prefetch_related('table_links'))
    return {'day_id':day.pk, 'orders':orders, 'payments':[p for order in orders for p in order._financial_payments],
            'sessions':cash_sessions_for_day(day)}


def get_pending_cash_handoffs(*, day=None, waiter=None):
    rows = CashHandoff.objects.filter(status="PENDING").select_related("waiter", "payment__order__primary_table")
    if day is not None:
        rows = rows.filter(payment__order__business_day=day)
    if waiter is not None:
        rows = rows.filter(waiter=waiter)
    return rows.order_by("created_at", "pk")


def get_cash_session_summary(session):
    if not hasattr(session, "_ledger_movements"):
        session = CashSession.objects.select_related("register", "cashier").get(pk=session.pk)
    totals = _movement_totals(session)
    return {"id": session.pk, "register": session.register.name, "cashier": session.cashier.get_username(),
            "opening_float": session.opening_float, "direct_cash_receipts": totals.get("DIRECT_CASH_PAYMENT", ZERO),
            "waiter_handoffs": totals.get("WAITER_HANDOFF", ZERO), "withdrawals": totals.get("WITHDRAWAL", ZERO),
            "cash_refunds": totals.get("CASH_REFUND", ZERO), "expected_cash": get_expected_cash(session),
            "counted_cash": session.counted_cash if session.status == "CLOSED" else None,
            "difference": session.difference if session.status == "CLOSED" else None,
            "opened_at": session.opened_at, "closed_at": session.closed_at, "status": session.status}


def get_session_integrity_errors(session):
    errors = []
    movements = (session._ledger_movements if hasattr(session, '_ledger_movements') else
                 list(session.movements.select_related('payment__order', 'handoff', 'refund')))
    for movement in movements:
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
    handoffs = session._ledger_handoffs if hasattr(session, '_ledger_handoffs') else session.handoffs.all()
    received_ids = {m.handoff_id for m in movements if m.movement_type == 'WAITER_HANDOFF'}
    for handoff in handoffs:
        if handoff.status != "DELIVERED" or handoff.pk not in received_ids:
            errors.append(f"Entrega #{handoff.pk}: falta el movimiento de recepción")
    expected = get_expected_cash(session)
    if expected < ZERO:
        errors.append("Efectivo esperado negativo")
    if session.counted_at and (session.expected_cash_at_close != expected or session.difference != session.counted_cash - expected):
        errors.append("El conteo no coincide con el libro de movimientos congelado")
    return errors


def get_business_day_close_blockers(day, *, snapshot=None):
    from apps.payments.services import _assert_ledger
    day = BusinessDay.objects.get(pk=day.pk)
    snapshot = snapshot or get_business_day_snapshot(day)
    if snapshot['day_id'] != day.pk:
        raise ValidationError('El resumen no corresponde a esta jornada.')
    blockers = []
    def add(kind, description, pk):
        blockers.append({"type": kind, "description": description, "object_id": pk})
    legacy = TableOrder.objects.filter(business_day__isnull=True).filter(
        Q(status__in=ACTIVE_STATUSES) | Q(payments__status="PENDING") | Q(payments__cash_handoff_status="PENDING")
    ).distinct()
    for order in legacy.select_related("primary_table"):
        add("UNASSIGNED_LEGACY_ORDER", f"{order}: requiere asignación explícita a una jornada antes de liquidar sus pendientes", order.pk)
    for order in snapshot["orders"]:
        if order.status in ACTIVE_STATUSES:
            add("ACTIVE_ORDER", f"{order.display_name} continúa activa", order.pk)
        summary = get_financial_summary(order)
        if summary["outstanding_balance"] != ZERO:
            add("OUTSTANDING_BALANCE", f"{order} tiene saldo Q{summary['outstanding_balance']}", order.pk)
        try:
            _assert_ledger(order)
        except ValidationError as exc:
            add("FINANCIAL_INCONSISTENCY", f"{order}: {' '.join(exc.messages)}", order.pk)
        if order.status not in ACTIVE_STATUSES and any(link.released_at is None for link in order.table_links.all()):
            add("FINANCIAL_INCONSISTENCY", f"{order}: conserva vínculos activos tras finalizar", order.pk)
    for payment in snapshot["payments"]:
        if payment.status != "PENDING":
            continue
        add("PENDING_PAYMENT", f"Pago #{payment.pk} de {payment.order}: pendiente de verificar", payment.pk)
    for session in snapshot["sessions"]:
        if session.status == "OPEN":
            add("OPEN_CASH_SESSION", f"{session.register.name} continúa abierta (sesión #{session.pk})", session.pk)
        for error in get_session_integrity_errors(session):
            add("CASH_INCONSISTENCY", error, session.pk)
    handoffs = list(CashHandoff.objects.filter(payment__order__business_day=day).select_related('waiter'))
    handoff_by_payment = {h.payment_id:h for h in handoffs}
    incoming_by_payment = {m.payment_id:m for m in CashMovement.objects.filter(payment__order__business_day=day,
        movement_type__in=INCOMING).select_related('cash_session')}
    for handoff in handoffs:
        if handoff.status == 'PENDING':
            add("PENDING_HANDOFF", f"{handoff.waiter}: entrega del pago #{handoff.payment_id} pendiente", handoff.pk)
    for payment in snapshot['payments']:
        if payment.method != 'CASH':
            continue
        handoff = handoff_by_payment.get(payment.pk)
        incoming = incoming_by_payment.get(payment.pk)
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


def get_business_day_summary(day, *, snapshot=None):
    day = BusinessDay.objects.get(pk=day.pk)
    snapshot = snapshot or get_business_day_snapshot(day)
    if snapshot['day_id'] != day.pk:
        raise ValidationError('El resumen no corresponde a esta jornada.')
    totals = {key: ZERO for key in ("gross_sales", "adjustments", "refunds", "net_sales")}
    for order in snapshot['orders']:
        summary = get_financial_summary(order)
        for key, source in (("gross_sales", "gross_total"), ("adjustments", "adjustments"), ("refunds", "refunds"), ("net_sales", "charge_total")):
            totals[key] += summary[source]
    methods = summarize_payment_methods(snapshot['payments'])
    sessions = snapshot['sessions']
    handoffs = CashHandoff.objects.filter(payment__order__business_day=day)
    movements = [movement for session in sessions for movement in session._ledger_movements]
    return {"business_date":day.business_date, "status":day.status, **totals, 'payments_by_method':methods,
        'sessions':{status.lower():sum(s.status == status for s in sessions) for status in ('OPEN','CLOSED')},
        'cash_differences':sum((s.difference for s in sessions if s.status == 'CLOSED'),ZERO),
        'withdrawals':sum((m.amount for m in movements if m.movement_type == 'WITHDRAWAL'),ZERO),
        'cash_refunds':sum((m.amount for m in movements if m.movement_type == 'CASH_REFUND'),ZERO),
        'handoffs':{'pending':handoffs.filter(status='PENDING').count(), 'delivered':handoffs.filter(status='DELIVERED').count()},
        'orders':{'active':sum(o.status in ACTIVE_STATUSES for o in snapshot['orders']), 'closed':sum(o.status == 'CLOSED' for o in snapshot['orders'])},
        'pending_verification':sum((p.amount for p in snapshot['payments'] if p.status == 'PENDING'),ZERO)}

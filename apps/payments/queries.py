"""Importes netos y cobertura por unidad, sin modificar las cantidades de consumo."""
from decimal import Decimal

from django.db.models import Q, Prefetch

from apps.orders.models import SubAccount, OrderLine
from .models import Payment, PaymentAllocation, OrderAdjustment, AdjustmentAllocation, PaymentRefund, RefundAllocation

ZERO = Decimal("0.00")


def prefetch_financials(orders):
    """Snapshot de lectura por lotes; reutiliza unit_ledger y sus validaciones originales.

    Nunca reutilizar estos objetos para una escritura: servicios releen bajo bloqueo.
    El número de consultas no crece con órdenes, pagos ni líneas.
    """
    allocations = PaymentAllocation.objects.select_related('order_line').prefetch_related('refund_allocations')
    refunds = PaymentRefund.objects.prefetch_related(
        Prefetch('allocations', queryset=RefundAllocation.objects.select_related('payment_allocation')))
    payments = Payment.objects.select_related('subaccount', 'order__primary_table', 'recorded_by').prefetch_related(
        Prefetch('allocations', queryset=allocations), Prefetch('refunds', queryset=refunds))
    adjustments = OrderAdjustment.objects.select_related('subaccount').prefetch_related(
        Prefetch('allocations', queryset=AdjustmentAllocation.objects.select_related('order_line')))
    return list(orders.prefetch_related(
        Prefetch('lines', queryset=OrderLine.objects.order_by('pk'), to_attr='_financial_lines'),
        Prefetch('payments', queryset=payments, to_attr='_financial_payments'),
        Prefetch('adjustments', queryset=adjustments, to_attr='_financial_adjustments')))


def financial_headers(order, model):
    attr = '_financial_payments' if model is Payment else '_financial_adjustments'
    if hasattr(order, attr):
        return getattr(order, attr)
    return model.objects.filter(order=order).prefetch_related('allocations__order_line')


def financial_refunds(order):
    if hasattr(order, '_financial_payments'):
        return [refund for payment in order._financial_payments for refund in payment.refunds.all()]
    return PaymentRefund.objects.filter(payment__order=order).prefetch_related('allocations__payment_allocation')


def financial_allocations(order):
    if hasattr(order, '_financial_payments'):
        return [row for payment in order._financial_payments for row in payment.allocations.all()]
    return PaymentAllocation.objects.filter(payment__order=order).prefetch_related('refund_allocations')


def unit_ledger(order, *, include_drafts=False):
    units = {}
    statuses = ["SENT", "DRAFT"] if include_drafts else ["SENT"]
    lines = ([line for line in order._financial_lines if line.status in statuses] if hasattr(order, '_financial_lines')
             else order.lines.filter(status__in=statuses).order_by('pk'))
    for line in lines:
        for number in range(1, line.quantity + 1):
            units[(line.pk, number)] = dict(line=line, unit_number=number, price=line.unit_price,
                confirmed=ZERO, pending=ZERO, adjustment=ZERO, refunded=ZERO)
    if hasattr(order, '_financial_payments'):
        sources = [
            ([row for p in order._financial_payments if p.status in ('CONFIRMED', 'REFUNDED') for row in p.allocations.all()], 'confirmed'),
            ([row for p in order._financial_payments if p.status == 'PENDING' for row in p.allocations.all()], 'pending'),
            ([row for a in order._financial_adjustments for row in a.allocations.all()], 'adjustment'),
        ]
        refunds = [row for refund in financial_refunds(order) for row in refund.allocations.all()]
    else:
        sources = [
            (PaymentAllocation.objects.filter(payment__order=order, payment__status__in=["CONFIRMED", "REFUNDED"]), "confirmed"),
            (PaymentAllocation.objects.filter(payment__order=order, payment__status="PENDING"), "pending"),
            (AdjustmentAllocation.objects.filter(adjustment__order=order), "adjustment"),
        ]
        refunds = RefundAllocation.objects.filter(refund__payment__order=order).select_related("payment_allocation")
    for rows, field in sources:
        for row in rows:
            key = (row.order_line_id, row.unit_number)
            if key in units:
                units[key][field] += row.amount
    for row in refunds:
        key = (row.payment_allocation.order_line_id, row.payment_allocation.unit_number)
        if key in units:
            units[key]["refunded"] += row.amount
    for unit in units.values():
        unit["charge"] = unit["price"] - unit["adjustment"] - unit["refunded"]
        unit["paid"] = unit["confirmed"] - unit["refunded"]
        unit["balance"] = unit["charge"] - unit["paid"]
        unit["available"] = unit["balance"] - unit["pending"]
    return units


def _scope(target):
    return (target.order, target.pk) if isinstance(target, SubAccount) else (target, None)


def get_financial_summary(target, *, include_drafts=False):
    order, account_id = _scope(target)
    units = [u for u in unit_ledger(order, include_drafts=include_drafts).values() if account_id is None or u["line"].subaccount_id == account_id]
    total = lambda key: sum((u[key] for u in units), ZERO)
    return {"gross_total": total("price"), "adjustments": total("adjustment"),
            "refunds": total("refunded"), "charge_total": total("charge"),
            "confirmed_paid": total("paid"), "pending_verification": total("pending"),
            "outstanding_balance": total("balance"), "available_to_pay": total("available")}


def get_order_charge_total(order):
    return get_financial_summary(order)["charge_total"]


def get_order_confirmed_paid_total(order):
    return get_financial_summary(order)["confirmed_paid"]


def get_order_pending_payment_total(order):
    return get_financial_summary(order)["pending_verification"]


def get_order_balance(order):
    return get_financial_summary(order)["outstanding_balance"]


get_subaccount_charge_total = get_order_charge_total
get_subaccount_confirmed_paid_total = get_order_confirmed_paid_total
get_subaccount_pending_payment_total = get_order_pending_payment_total
get_subaccount_balance = get_order_balance


def get_line_payment_quantities(line, *, include_drafts=False):
    units = [u for u in unit_ledger(line.order, include_drafts=include_drafts).values() if u["line"].pk == line.pk]
    return {
        "total_quantity": line.quantity,
        "confirmed_quantity": sum(u["balance"] == ZERO and u["confirmed"] > ZERO for u in units),
        "pending_verification_quantity": sum(u["pending"] > ZERO for u in units),
        "outstanding_quantity": sum(u["balance"] > ZERO for u in units),
        "partially_covered_quantity": sum(ZERO < u["confirmed"] + u["adjustment"] < u["price"] for u in units),
        "adjusted_quantity": sum(u["adjustment"] == u["price"] for u in units),
        "confirmed_paid": sum((u["paid"] for u in units), ZERO),
        "pending_verification": sum((u["pending"] for u in units), ZERO),
        "units": [{k: v for k, v in u.items() if k != "line"} for u in units],
    }


def get_payment_history(order):
    return Payment.objects.filter(order=order).select_related("recorded_by", "confirmed_by", "subaccount").prefetch_related("refunds").order_by("created_at", "pk")


def get_receipt_data(target):
    order, account_id = _scope(target)
    lines = order.lines.filter(status="SENT")
    if account_id is not None:
        lines = lines.filter(subaccount_id=account_id)
    line_ids = list(lines.values_list("pk", flat=True))
    payments = get_payment_history(order).filter(allocations__order_line_id__in=line_ids).distinct()
    adjustments = order.adjustments.filter(allocations__order_line_id__in=line_ids).distinct()
    def scope_amount(rows):
        return sum((row.amount for row in rows if row.order_line_id in line_ids), ZERO)
    summary = get_financial_summary(target)
    return {
        "order_number": order.order_number, "table": order.display_name,
        "tables": list(order.table_links.filter(Q(released_at__isnull=True) | Q(released_at=order.closed_at)).values_list("table__name", flat=True)),
        "subaccount": target.name if account_id else None,
        "date": order.closed_at or order.opened_at, "status": order.status,
        "lines": [{"line_id": line.pk, "description": line.product_name_snapshot, "quantity": line.quantity,
                   "unit_price": line.unit_price, "subtotal": line.subtotal,
                   "modifiers": list(line.modifiers.values_list("option_name_snapshot", flat=True)),
                   "coverage": get_line_payment_quantities(line)} for line in lines],
        "adjustments": [{"id": a.pk, "type": a.adjustment_type, "amount": scope_amount(a.allocations.all()), "reason": a.reason} for a in adjustments],
        "payments": [{"id": p.pk, "method": p.method, "status": p.status,
                      "amount": scope_amount(p.allocations.all()), "payment_amount": p.amount,
                      "date": p.created_at, "reference": p.reference} for p in payments],
        "refunds": [{"id": row.refund_id, "payment_id": row.refund.payment_id, "amount": row.amount,
                     "line_id": row.payment_allocation.order_line_id, "unit_number": row.payment_allocation.unit_number,
                     "reason": row.refund.reason, "date": row.refund.created_at}
                    for row in RefundAllocation.objects.filter(payment_allocation__order_line_id__in=line_ids).select_related("refund", "payment_allocation")],
        **{key: value for key, value in summary.items() if key not in ("adjustments", "refunds")},
        "adjustment_total": summary["adjustments"], "refund_total": summary["refunds"],
    }


def summarize_payment_methods(payments):
    """Colección con refunds prefetched: separar confirmado, reembolsado y pendiente."""
    methods = {method:dict(confirmed_gross=ZERO, refunds=ZERO, confirmed_net=ZERO, pending=ZERO) for method in Payment.Method.values}
    for payment in payments:
        row = methods[payment.method]
        if payment.status in ('CONFIRMED','REFUNDED'):
            row['confirmed_gross'] += payment.amount
            row['refunds'] += sum((refund.amount for refund in payment.refunds.all()),ZERO)
        elif payment.status == 'PENDING':
            row['pending'] += payment.amount
    for row in methods.values():
        row['confirmed_net'] = row['confirmed_gross'] - row['refunds']
    return methods

"""Presentación financiera y confirmaciones ligadas al estado real de la cuenta."""
import hashlib
import json

from django.core import signing
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.payments import services as payments
from apps.payments.models import RefundAllocation
from apps.payments.queries import get_financial_summary, get_line_payment_quantities, get_payment_history, unit_ledger, ZERO
from .ordering import positive_id
from .queries import money_label

QUOTE_SALT = "operations.payment-quote.v1"
STALE_MESSAGE = "Este consumo ya fue pagado por otro usuario o la cuenta cambió. Revisa el saldo actualizado antes de continuar."


def can_view_account(user):
    return any(user.has_perm("payments." + name) for name in ("view_payment", "record_payment", "close_order"))


def account_target(order, value, *, writable=False):
    if order.billing_mode == "SINGLE":
        if value:
            raise ValidationError("Esta mesa utiliza una sola cuenta.")
        return None
    if not value:
        if writable:
            raise ValidationError("Selecciona la cuenta que se pagará.")
        return None
    account = order.subaccounts.filter(pk=positive_id(value, "La cuenta")).first()
    if account is None:
        raise ValidationError("La cuenta seleccionada no está disponible.")
    if writable and account.status != "OPEN":
        raise ValidationError("Esta cuenta ya está pagada. No se puede volver a cobrar.")
    return account


def amounts(summary):
    return {key: money_label(value) for key, value in summary.items()}


def account_state(order, user, account=None, *, include_drafts=False):
    target = account or order
    selected = order.billing_mode == "SINGLE" or account is not None
    summary = get_financial_summary(target, include_drafts=include_drafts) if selected else {key: ZERO for key in get_financial_summary(order)}
    lines = order.lines.filter(status__in=["SENT", "DRAFT"] if include_drafts else ["SENT"]).prefetch_related("modifiers").order_by("pk")
    if account:
        lines = lines.filter(subaccount=account)
    elif not selected:
        lines = lines.none()
    rows = []
    line_ids = []
    for line in lines:
        line_ids.append(line.pk)
        coverage = get_line_payment_quantities(line, include_drafts=include_drafts)
        units = coverage["units"]
        eligible = [unit for unit in units if unit["available"] > ZERO and unit["confirmed"] == ZERO and unit["credit"] == ZERO and unit["pending"] == ZERO]
        settled = all(unit["balance"] == ZERO and unit["pending"] == ZERO for unit in units)
        rows.append({"id": line.pk, "name": line.product_name_snapshot, "quantity": line.quantity,
            "unit_price": money_label(line.unit_price), "subtotal": money_label(line.subtotal),
            "modifiers": [item.option_name_snapshot for item in line.modifiers.all()], "notes": line.notes,
            "paid_quantity": coverage["confirmed_quantity"], "pending_quantity": coverage["pending_verification_quantity"],
            "outstanding_quantity": coverage["outstanding_quantity"], "adjusted_quantity": coverage["adjusted_quantity"],
            "partial_quantity": sum(unit["confirmed"] + unit["credit"] > ZERO and unit["available"] > ZERO for unit in units),
            "available_quantity": len(eligible), "settled": settled})
    history = []
    for payment in get_payment_history(order).filter(allocations__order_line_id__in=line_ids).distinct().prefetch_related("allocations"):
        applied = sum((a.amount for a in payment.allocations.all() if a.order_line_id in line_ids), ZERO)
        refunded = sum((row.amount for row in RefundAllocation.objects.filter(refund__payment=payment,
            payment_allocation__order_line_id__in=line_ids)), ZERO)
        history.append({"method": payment.get_method_display(), "status": payment.status,
            "status_label": "Pendiente de verificación" if payment.status == "PENDING" else payment.get_status_display(),
            "amount": money_label(applied), "refunded": money_label(refunded) if refunded else None,
            "reference": payment.reference})
    drafts = order.lines.filter(status="DRAFT")
    if account:
        drafts = drafts.filter(subaccount=account)
    accounts = []
    for sub in order.subaccounts.order_by("pk"):
        financial = get_financial_summary(sub)
        accounts.append({"id": sub.pk, "name": sub.name, "closed": sub.status == "CLOSED",
            "balance": money_label(financial["outstanding_balance"]),
            "pending": financial["pending_verification"] > ZERO})
    from apps.reservations.credits import credit_summary
    credit = credit_summary(order)
    return {"reservation_credit": {"codes": credit["codes"], **amounts({k: v for k, v in credit.items() if k != "codes"})} if credit["amount"] else None,
        "table_name": order.display_name, "area": order.area.name, "billing_mode": order.billing_mode,
        "selected_account": account.pk if account else None,
        "selected_name": account.name if account else "Una sola cuenta" if selected else "Selecciona una cuenta",
        "account_closed": bool(account and account.status == "CLOSED"), "accounts": accounts,
        "summary": amounts(summary), "lines": rows, "history": history, "has_drafts": drafts.exists(),
        "has_pending": summary["pending_verification"] > ZERO, "has_adjustments": summary["adjustments"] > ZERO,
        "has_refunds": summary["refunds"] > ZERO,
        "can_pay": selected and not (account and account.status == "CLOSED") and summary["available_to_pay"] > ZERO and user.has_perm("payments.record_payment"),
        "can_close": user.has_perm("payments.close_order") and payments.can_close_order(order),
        "can_add": user.has_perm("orders.add_order_line") and not (account and account.status == "CLOSED"),
        "order_url": reverse("operations:order", args=[order.pk]) + (f"?subaccount={account.pk}" if account else "")}


def financial_revision(order):
    ledger = unit_ledger(order, include_drafts=order.order_type == "QUICK_SALE")
    data = [[*key, str(unit["price"]), str(unit["confirmed"]), str(unit["pending"]),
             str(unit["adjustment"]), str(unit["refunded"]), str(unit["credit"]), unit["line"].subaccount_id] for key, unit in ledger.items()]
    # Los identificadores detectan también un pago seguido de rechazo que restituye el saldo.
    data += list(order.payments.order_by("pk").values_list("pk", "status"))
    data += list(order.subaccounts.order_by("pk").values_list("pk", "status"))
    return hashlib.sha256(json.dumps(data).encode()).hexdigest()


def signed_plan(context, order, account, plan):
    return signing.dumps({**plan, "order": order.pk, "account": account.pk if account else None,
        "session": context["session"].pk, "kind": context.get("kind", "waiter"), "revision": financial_revision(order)}, salt=QUOTE_SALT, compress=True)


def read_plan(value, context, order, account, *, current=True):
    try:
        plan = signing.loads(value, salt=QUOTE_SALT, max_age=600)
    except (signing.BadSignature, TypeError, ValueError):
        raise ValidationError("La confirmación venció. Revisa el monto y prepara el pago nuevamente.")
    if (plan.get("order") != order.pk or plan.get("account") != (account.pk if account else None)
        or plan.get("session") != context["session"].pk or plan.get("kind", "waiter") != context.get("kind", "waiter")):
        raise ValidationError("Esta confirmación no pertenece a tu cuenta o sesión actual.")
    if current and plan["revision"] != financial_revision(order):
        raise ValidationError(STALE_MESSAGE)
    return plan


def prepare_payment(context, order, account, data):
    mode = data.get("mode", "full")
    try:
        selection = json.loads(data.get("selection", "[]"))
    except (ValueError, TypeError):
        raise ValidationError("La selección de productos no es válida.")
    keys = None
    if data.get("scope"):
        scope = read_plan(data["scope"], context, order, account, current=False)
        keys = scope["scope_keys"]
        if mode == "selection":
            raise ValidationError("Vuelve a la cuenta para cambiar los productos seleccionados.")
    quote = payments.get_payment_quote(account or order, mode=mode, selection=selection,
        amount=data.get("amount"), unit_keys=keys, include_drafts=order.order_type == "QUICK_SALE")
    plan = {"mode": mode, "selection": selection if mode == "selection" else None,
        "amount": str(quote["amount"]), "scope_keys": keys or quote["unit_keys"], "restricted": keys is not None}
    token = signed_plan(context, order, account, plan)
    value = quote["amount"]
    quick = sorted({value, (value // 100 + 1) * 100, (value // 100 + 2) * 100, (value // 100 + 3) * 100})
    return {"token": token, "amount": str(value), "amount_label": money_label(value),
        "line_amounts": {str(key): money_label(amount) for key, amount in quote["line_amounts"].items()},
        "quick_cash": [{"value": str(amount), "label": money_label(amount)} for amount in quick]}

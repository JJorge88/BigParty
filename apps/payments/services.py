"""Toda escritura financiera bloquea primero la orden; importes y cobertura se calculan aquí."""
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Product
from apps.inventory.models import InventoryMovement
from apps.inventory.services import _record_movement
from apps.orders.models import ACTIVE_STATUSES, TableOrder, SubAccount
from apps.orders.services import _log
from .models import Payment, PaymentAllocation, OrderAdjustment, AdjustmentAllocation, PaymentRefund, RefundAllocation
from .queries import (ZERO, unit_ledger, get_financial_summary, get_order_charge_total,
    get_order_confirmed_paid_total, get_order_pending_payment_total, get_order_balance,
    get_subaccount_charge_total, get_subaccount_confirmed_paid_total, get_subaccount_pending_payment_total,
    get_subaccount_balance, get_line_payment_quantities, get_receipt_data, get_payment_history)


def _require(user, permission):
    if user is None or not user.is_active or not user.has_perm("payments." + permission):
        raise PermissionDenied("No tienes permiso para esta operación financiera.")


def _money(value):
    if isinstance(value, (float, bool)):
        raise ValidationError("Usa un importe decimal exacto, sin float.")
    try:
        amount = Decimal(value)
        if not amount.is_finite() or amount <= ZERO or amount > Decimal("999999999999.99") or amount != amount.quantize(Decimal("0.01")):
            raise ValueError
        return amount.quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError("El importe debe ser positivo y tener como máximo dos decimales.")


def _reason(reason):
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError("Indica el motivo de la operación.")
    return reason.strip()


def _locked_target(target):
    account_id = target.pk if isinstance(target, SubAccount) else None
    order_id = target.order_id if account_id else target.pk
    order = TableOrder.objects.select_for_update().get(pk=order_id)
    if order.status not in ACTIVE_STATUSES:
        raise ValidationError("La cuenta no está activa.")
    account = None
    if account_id:
        account = SubAccount.objects.get(pk=account_id)
        if account.order_id != order.pk or order.billing_mode != "SPLIT" or account.status != "OPEN":
            raise ValidationError("La subcuenta debe estar abierta y pertenecer a esta cuenta separada.")
    return order, account


def _available_units(order, account=None):
    return [u for u in unit_ledger(order).values() if (account is None or u["line"].subaccount_id == account.pk) and u["available"] > ZERO]


def _select(units, selection):
    if not isinstance(selection, (list, tuple)) or not selection:
        raise ValidationError("Selecciona líneas y cantidades enteras.")
    result, seen = [], set()
    for item in selection:
        if not isinstance(item, dict):
            raise ValidationError("La selección debe contener línea y cantidad.")
        pk, quantity = item.get("line_id"), item.get("quantity")
        if type(pk) is not int or pk in seen or type(quantity) is not int or quantity <= 0:
            raise ValidationError("No repitas líneas y usa cantidades enteras positivas.")
        seen.add(pk)
        eligible = [u for u in units if u["line"].pk == pk and u["confirmed"] == ZERO and u["pending"] == ZERO]
        if len(eligible) < quantity:
            raise ValidationError("No hay suficientes unidades sin pago en esa línea. Para completar una unidad pagada parcialmente usa pago por monto o saldo total.")
        result.extend((u, u["available"], 1) for u in eligible[:quantity])
    return result


def _distribute(units, amount):
    remaining, result = amount, []
    for unit in units:
        applied = min(unit["available"], remaining)
        if applied:
            result.append((unit, applied, None))
            remaining -= applied
        if remaining == ZERO:
            break
    if remaining:
        raise ValidationError("El importe supera el saldo disponible; los pagos pendientes también reservan saldo.")
    return result


def _assert_ledger(order):
    """Comprobación de cierre y frontera de escritura, incluida integridad entre cabeceras y detalles."""
    units = unit_ledger(order)
    for model, relation in ((Payment, "payment"), (OrderAdjustment, "adjustment")):
        for header in model.objects.filter(order=order).prefetch_related("allocations__order_line"):
            rows = list(header.allocations.all())
            if not rows or sum((r.amount for r in rows), ZERO) != header.amount:
                raise ValidationError("Inconsistencia entre el monto y sus asignaciones.")
            if header.subaccount_id and (header.subaccount.order_id != order.pk or order.billing_mode != "SPLIT"):
                raise ValidationError("Subcuenta financiera inconsistente.")
            for row in rows:
                if (row.order_line.order_id != order.pk or row.unit_number > row.order_line.quantity or
                    row.order_line.status != "SENT" or
                    (header.subaccount_id and row.order_line.subaccount_id != header.subaccount_id)):
                    raise ValidationError("Asignación fuera del consumo autorizado.")
    for refund in PaymentRefund.objects.filter(payment__order=order).prefetch_related("allocations__payment_allocation"):
        rows = list(refund.allocations.all())
        if not rows or sum((r.amount for r in rows), ZERO) != refund.amount or any(r.payment_allocation.payment_id != refund.payment_id for r in rows):
            raise ValidationError("Asignación de reembolso inconsistente.")
    for allocation in PaymentAllocation.objects.filter(payment__order=order).prefetch_related("refund_allocations"):
        if allocation.refund_allocations.exists() and allocation.payment.status not in ("CONFIRMED", "REFUNDED"):
            raise ValidationError("Un pago sin confirmar no puede tener reembolsos.")
        if sum((r.amount for r in allocation.refund_allocations.all()), ZERO) > allocation.amount:
            raise ValidationError("El reembolso supera el pago asignado.")
    for unit in units.values():
        if unit["available"] < ZERO or unit["refunded"] > unit["confirmed"]:
            raise ValidationError("El consumo tiene cobertura financiera inconsistente.")


def _refresh(order, user=None, *, close_empty=False):
    _assert_ledger(order)
    if order.status not in ACTIVE_STATUSES:
        return order
    accounts = order.subaccounts.filter(status="OPEN") if user is not None else []
    for account in accounts:
        summary = get_financial_summary(account)
        relevant = close_empty or account.lines.exists()
        if relevant and not account.lines.filter(status="DRAFT").exists() and summary["outstanding_balance"] == ZERO and summary["pending_verification"] == ZERO:
            account.status, account.closed_at = "CLOSED", timezone.now()
            account.save(update_fields=["status", "closed_at"])
            if user:
                _log(order, user, "CLOSED", f"Subcuenta cerrada: {account.name}", subaccount_id=account.pk)
    summary = get_financial_summary(order)
    # Una cuenta totalmente pagada permanece activa hasta el cierre explícito.
    status = "PAYMENT_PENDING" if summary["pending_verification"] else (
        "PARTIALLY_PAID" if order.payments.filter(status__in=["CONFIRMED", "REFUNDED"]).exists() else "OPEN")
    order.status = status
    order.save(update_fields=["status", "updated_at"])
    return order


@transaction.atomic
def refresh_order_payment_status(order, user=None):
    current = TableOrder.objects.select_for_update().get(pk=order.pk)
    return _refresh(current, user)


def _create(order, account, allocations, method, user, *, reference="", notes="", received_amount=None, card_approved=False):
    if method not in Payment.Method.values:
        raise ValidationError("Método de pago inválido.")
    if not isinstance(reference, str) or not isinstance(notes, str):
        raise ValidationError("La referencia y las notas deben ser texto.")
    reference = reference.strip()
    pending = method in ("TRANSFER", "DEPOSIT")
    if pending and not reference:
        raise ValidationError("La transferencia o depósito necesita una referencia.")
    if method == "CARD" and card_approved is not True:
        raise ValidationError("Confirma que la terminal bancaria aprobó el cobro.")
    amount = _money(sum((a for _, a, _ in allocations), ZERO))
    metadata = {}
    if received_amount is not None:
        if method != "CASH":
            raise ValidationError("El importe recibido solo aplica al efectivo.")
        received = _money(received_amount)
        if received < amount:
            raise ValidationError("El efectivo recibido no alcanza para este pago.")
        metadata["received_amount"] = str(received)
    if method == "CARD":
        metadata["terminal_approved"] = True
    payment = Payment(order=order, subaccount=account, method=method,
        status="PENDING" if pending else "CONFIRMED", amount=amount, recorded_by=user,
        confirmed_by=None if pending else user, confirmed_at=None if pending else timezone.now(),
        reference=reference, notes=notes.strip(), metadata=metadata,
        cash_handoff_status="PENDING" if method == "CASH" and user.role == "MESERO" else "NOT_REQUIRED")
    payment.full_clean()
    payment.save()
    for unit, applied, quantity in allocations:
        PaymentAllocation.objects.create(payment=payment, order_line=unit["line"], unit_number=unit["unit_number"], quantity=quantity, amount=applied)
    _log(order, user, "PAYMENT_RECORDED", f"Pago {payment.get_method_display()}: Q{amount}", payment_id=payment.pk, amount=str(amount), status=payment.status)
    _refresh(order, user)
    return payment


@transaction.atomic
def create_selected_payment(target, selection, method, user, **options):
    _require(user, "record_payment")
    order, account = _locked_target(target)
    return _create(order, account, _select(_available_units(order, account), selection), method, user, **options)


@transaction.atomic
def create_amount_payment(target, amount, method, user, **options):
    _require(user, "record_payment")
    amount = _money(amount)
    order, account = _locked_target(target)
    return _create(order, account, _distribute(_available_units(order, account), amount), method, user, **options)


@transaction.atomic
def pay_full_balance(target, method, user, **options):
    _require(user, "record_payment")
    order, account = _locked_target(target)
    units = _available_units(order, account)
    amount = _money(sum((u["available"] for u in units), ZERO))
    return _create(order, account, _distribute(units, amount), method, user, **options)


def pay_cash(target, amount_due, user, *, received_amount=None):
    return create_amount_payment(target, amount_due, "CASH", user, received_amount=received_amount)


def _locked_payment(payment, *, active=True):
    order = TableOrder.objects.select_for_update().get(pk=Payment.objects.values_list("order_id", flat=True).get(pk=payment.pk))
    current = Payment.objects.select_for_update().get(pk=payment.pk)
    if active and order.status not in ACTIVE_STATUSES:
        raise ValidationError("La cuenta no está activa.")
    return current, order


@transaction.atomic
def confirm_pending_payment(payment, user):
    _require(user, "verify_transfer_payment")
    current, order = _locked_payment(payment)
    if current.status != "PENDING" or current.method not in ("TRANSFER", "DEPOSIT"):
        raise ValidationError("Este pago no está pendiente de verificación.")
    current.status, current.confirmed_by, current.confirmed_at = "CONFIRMED", user, timezone.now()
    current.save(update_fields=["status", "confirmed_by", "confirmed_at"])
    _log(order, user, "PAYMENT_CONFIRMED", f"Pago #{current.pk} verificado", payment_id=current.pk)
    _refresh(order, user)
    return current


@transaction.atomic
def reject_pending_payment(payment, user, reason):
    _require(user, "reject_transfer_payment")
    reason = _reason(reason)
    current, order = _locked_payment(payment)
    if current.status != "PENDING" or current.method not in ("TRANSFER", "DEPOSIT"):
        raise ValidationError("Este pago no está pendiente de verificación.")
    current.status = "REJECTED"
    current.metadata = {**current.metadata, "rejection_reason": reason, "rejected_by": user.pk, "rejected_at": timezone.now().isoformat()}
    current.save(update_fields=["status", "metadata"])
    _log(order, user, "PAYMENT_REJECTED", f"Pago #{current.pk} rechazado: {reason}", payment_id=current.pk, reason=reason)
    _refresh(order, user)
    return current


@transaction.atomic
def apply_order_adjustment(target, user, *, adjustment_type="DISCOUNT", amount=None, selection=None, reason):
    _require(user, "apply_order_adjustment")
    reason = _reason(reason)
    order, account = _locked_target(target)
    if adjustment_type not in OrderAdjustment.Kind.values or (selection is None) == (amount is None):
        raise ValidationError("Indica un tipo válido y un monto o una selección, exclusivamente.")
    units = _available_units(order, account)
    allocations = _select(units, selection) if selection is not None else _distribute(units, _money(amount))
    adjustment = OrderAdjustment(order=order, subaccount=account, adjustment_type=adjustment_type,
        amount=_money(sum((a for _, a, _ in allocations), ZERO)), reason=reason, authorized_by=user)
    adjustment.full_clean()
    adjustment.save()
    for unit, applied, quantity in allocations:
        AdjustmentAllocation.objects.create(adjustment=adjustment, order_line=unit["line"], unit_number=unit["unit_number"], amount=applied, quantity=quantity)
    _log(order, user, "ADJUSTMENT_APPLIED", f"{adjustment.get_adjustment_type_display()}: Q{adjustment.amount}", adjustment_id=adjustment.pk, reason=reason)
    _refresh(order, user)
    return adjustment


def can_close_order(order):
    current = TableOrder.objects.get(pk=order.pk)
    if current.status not in ACTIVE_STATUSES or current.lines.filter(status="DRAFT").exists():
        return False
    try:
        _assert_ledger(current)
    except ValidationError:
        return False
    summary = get_financial_summary(current)
    # close_order también finaliza subcuentas vacías/de importe cero en su transacción.
    return summary["outstanding_balance"] == ZERO and summary["pending_verification"] == ZERO


@transaction.atomic
def close_order(order, user):
    _require(user, "close_order")
    current, _ = _locked_target(order)
    _refresh(current, user, close_empty=True)
    if not can_close_order(current):
        raise ValidationError("No se puede cerrar: hay borradores, saldo, pagos pendientes o inconsistencias.")
    current.status, current.closed_at = "CLOSED", timezone.now()
    current.save(update_fields=["status", "closed_at", "updated_at"])
    current.table_links.filter(released_at__isnull=True).update(released_at=current.closed_at)
    _log(current, user, "CLOSED", "Cuenta liquidada y mesas liberadas")
    return current


@transaction.atomic
def refund_payment(payment, user, *, reason, amount=None, allocation_ids=None, return_to_inventory=False):
    _require(user, "refund_payment")
    reason = _reason(reason)
    if type(return_to_inventory) is not bool or (amount is None) == (allocation_ids is None):
        raise ValidationError("Indica un monto o asignaciones exactas, exclusivamente.")
    current, order = _locked_payment(payment, active=False)
    if current.status != "CONFIRMED":
        raise ValidationError("Solo se reembolsa un pago confirmado con monto disponible.")
    allocations = list(current.allocations.order_by("order_line_id", "unit_number").prefetch_related("refund_allocations", "order_line__components"))
    entries = []
    if allocation_ids is not None:
        if not isinstance(allocation_ids, (list, tuple)) or not allocation_ids or any(type(pk) is not int for pk in allocation_ids) or len(set(allocation_ids)) != len(allocation_ids):
            raise ValidationError("Selecciona asignaciones exactas sin repetir.")
        selected = [a for a in allocations if a.pk in allocation_ids]
        if len(selected) != len(allocation_ids):
            raise ValidationError("La asignación no pertenece al pago.")
        ledger = unit_ledger(order)
        for allocation in selected:
            unit = ledger[(allocation.order_line_id, allocation.unit_number)]
            # Una devolución física exige una unidad pagada íntegramente por este pago.
            if allocation.refund_allocations.exists() or allocation.amount != unit["price"] - unit["adjustment"] or unit["pending"] or unit["refunded"]:
                raise ValidationError("La unidad tiene pagos divididos o reembolsos previos; utiliza un reembolso monetario sin inventario.")
            entries.append((allocation, allocation.amount, 1))
        amount = sum((a for _, a, _ in entries), ZERO)
    else:
        if return_to_inventory:
            raise ValidationError("Un reembolso por monto no identifica unidades físicas; no puede devolver inventario.")
        amount = _money(amount)
        remaining = amount
        for allocation in allocations:
            available = allocation.amount - sum((r.amount for r in allocation.refund_allocations.all()), ZERO)
            applied = min(available, remaining)
            if applied:
                entries.append((allocation, applied, None))
                remaining -= applied
            if not remaining:
                break
        if remaining:
            raise ValidationError("El reembolso supera el monto neto disponible del pago.")
    refund = PaymentRefund.objects.create(payment=current, amount=_money(amount), reason=reason,
        created_by=user, return_to_inventory=return_to_inventory)
    for allocation, applied, quantity in entries:
        RefundAllocation.objects.create(refund=refund, payment_allocation=allocation, amount=applied, quantity=quantity)
    if return_to_inventory:
        product_ids = {c.product_id for a, _, _ in entries for c in a.order_line.components.all() if c.stock_deducted}
        products = {p.pk: p for p in Product.objects.filter(pk__in=product_ids).order_by("pk").select_for_update()}
        for allocation, _, _ in entries:
            for component in allocation.order_line.components.all():
                if component.stock_deducted:
                    _record_movement(products[component.product_id], component.quantity_per_unit, user, reason,
                        InventoryMovement.MovementType.REFUND_RETURN,
                        metadata={"order_id": order.pk, "line_id": allocation.order_line_id, "payment_id": current.pk,
                                  "refund_id": refund.pk, "unit_number": allocation.unit_number})
    refunded = sum((r.amount for r in current.refunds.all()), ZERO)
    if refunded == current.amount:
        current.status = "REFUNDED"
        current.save(update_fields=["status"])
    _log(order, user, "REFUND", f"Reembolso Q{refund.amount}: {reason}", payment_id=current.pk,
         refund_id=refund.pk, amount=str(refund.amount), return_to_inventory=return_to_inventory)
    _refresh(order, user)
    return refund

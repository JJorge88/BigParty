"""Toda escritura financiera bloquea primero la orden; importes y cobertura se calculan aquí."""
from apps.sync.services import sync_atomic, track, save_tracked
from decimal import Decimal, InvalidOperation

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.catalog.models import Product
from apps.cash.guards import lock_order_day
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
    lock_order_day(order_id)
    order = TableOrder.objects.select_for_update().get(pk=order_id)
    if order.status not in ACTIVE_STATUSES:
        raise ValidationError("La cuenta no está activa.")
    account = None
    if account_id:
        account = SubAccount.objects.get(pk=account_id)
        if account.order_id != order.pk or order.billing_mode != "SPLIT" or account.status != "OPEN":
            raise ValidationError("La subcuenta debe estar abierta y pertenecer a esta cuenta separada.")
    return order, account


def _available_units(order, account=None, *, unit_keys=None, include_drafts=False):
    ledger = {key: unit for key, unit in unit_ledger(order, include_drafts=include_drafts).items()
              if account is None or unit["line"].subaccount_id == account.pk}
    if unit_keys is not None:
        if (not isinstance(unit_keys, (list, tuple)) or not unit_keys or
            any(not isinstance(key, (list, tuple)) or len(key) != 2 or
                any(type(value) is not int for value in key) for key in unit_keys)):
            raise ValidationError("La selección de consumo no es válida.")
        keys = [tuple(key) for key in unit_keys]
        if len(keys) != len(set(keys)) or any(key not in ledger for key in keys):
            raise ValidationError("El consumo seleccionado cambió. Vuelve a revisar la cuenta.")
        ledger = {key: ledger[key] for key in keys}
    return [unit for unit in ledger.values() if unit["available"] > ZERO]


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
        eligible = [u for u in units if u["line"].pk == pk and u["confirmed"] == ZERO and u["credit"] == ZERO and u["pending"] == ZERO]
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


def get_payment_quote(target, *, mode="full", selection=None, amount=None, unit_keys=None, include_drafts=False):
    """Vista previa que comparte exactamente las reglas de asignación del pago.

    unit_keys permite completar por monto las mismas unidades de una selección mixta,
    incluidas unidades que ya recibieron un abono. No reserva ni registra dinero.
    """
    account = target if isinstance(target, SubAccount) else None
    order = account.order if account else target
    units = _available_units(order, account, unit_keys=unit_keys, include_drafts=include_drafts)
    if mode == "selection":
        allocations = _select(units, selection)
    elif mode in ("full", "amount"):
        value = _money(amount if mode == "amount" else sum((u["available"] for u in units), ZERO))
        allocations = _distribute(units, value)
    else:
        raise ValidationError("Elige cómo deseas pagar la cuenta.")
    line_amounts = {}
    for unit, value, _ in allocations:
        line_amounts[unit["line"].pk] = line_amounts.get(unit["line"].pk, ZERO) + value
    return {"amount": sum((value for _, value, _ in allocations), ZERO), "line_amounts": line_amounts,
            "unit_keys": [(unit["line"].pk, unit["unit_number"]) for unit, _, _ in allocations]}


def _assert_ledger(order):
    """Comprobación de cierre y frontera de escritura, incluida integridad entre cabeceras y detalles."""
    from .queries import financial_headers, financial_refunds, financial_allocations
    from apps.reservations.credits import assert_credit_integrity
    assert_credit_integrity(order)
    units = unit_ledger(order)
    for model, relation in ((Payment, "payment"), (OrderAdjustment, "adjustment")):
        for header in financial_headers(order, model):
            rows = list(header.allocations.all())
            if not rows or sum((r.amount for r in rows), ZERO) != header.amount:
                raise ValidationError("Inconsistencia entre el monto y sus asignaciones.")
            if header.subaccount_id and (header.subaccount.order_id != order.pk or order.billing_mode != "SPLIT"):
                raise ValidationError("Subcuenta financiera inconsistente.")
            for row in rows:
                if (row.order_line.order_id != order.pk or row.unit_number > row.order_line.quantity or
                    (row.order_line.status != "SENT" and not (order.order_type == "QUICK_SALE" and order.status == "CANCELLED" and isinstance(header, Payment) and header.status in ("REJECTED", "REFUNDED"))) or
                    (header.subaccount_id and row.order_line.subaccount_id != header.subaccount_id)):
                    raise ValidationError("Asignación fuera del consumo autorizado.")
    for refund in financial_refunds(order):
        rows = list(refund.allocations.all())
        if not rows or sum((r.amount for r in rows), ZERO) != refund.amount or any(r.payment_allocation.payment_id != refund.payment_id for r in rows):
            raise ValidationError("Asignación de reembolso inconsistente.")
    for allocation in financial_allocations(order):
        if bool(list(allocation.refund_allocations.all())) and allocation.payment.status not in ("CONFIRMED", "REFUNDED"):
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
            save_tracked(account, update_fields=["status", "closed_at"])
            if user:
                _log(order, user, "CLOSED", f"Subcuenta cerrada: {account.name}", subaccount_id=account.pk)
    summary = get_financial_summary(order)
    # Una cuenta totalmente pagada permanece activa hasta el cierre explícito.
    status = "PAYMENT_PENDING" if summary["pending_verification"] else (
        "PARTIALLY_PAID" if summary["confirmed_paid"] or order.payments.filter(status__in=["CONFIRMED", "REFUNDED"]).exists() else "OPEN")
    order.status = status
    save_tracked(order, update_fields=["status", "updated_at"])
    return order


@sync_atomic('local')
@transaction.atomic
def refresh_order_payment_status(order, user=None):
    lock_order_day(order.pk)
    current = TableOrder.objects.select_for_update().get(pk=order.pk)
    return _refresh(current, user)


def _create(order, account, allocations, method, user, *, reference="", notes="", received_amount=None, card_approved=False, cash_session=None):
    if method not in Payment.Method.values:
        raise ValidationError("Método de pago inválido.")
    from apps.core.configuration import require_method
    require_method(method)
    if not isinstance(reference, str) or not isinstance(notes, str):
        raise ValidationError("La referencia y las notas deben ser texto.")
    reference = reference.strip()
    if cash_session is not None and method != "CASH":
        raise ValidationError("La sesión de caja solo corresponde a cobros en efectivo.")
    if method == "CASH" and cash_session is None and user.role != "MESERO":
        raise ValidationError("El cobro directo en efectivo requiere una sesión de caja explícita.")
    if order.order_type == "QUICK_SALE" and method == "CASH":
        if cash_session is None or cash_session.pk != order.cash_session_id:
            raise ValidationError("La venta rápida requiere su sesión de caja de origen; no admite entregas de mesero.")
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
    if order.order_type == "QUICK_SALE":
        from apps.orders.services import reserve_quick_sale_stock
        reserve_quick_sale_stock(order, user)
    payment = Payment(order=order, subaccount=account, method=method,
        status="PENDING" if pending else "CONFIRMED", amount=amount, recorded_by=user,
        confirmed_by=None if pending else user, confirmed_at=None if pending else timezone.now(),
        reference=reference, notes=notes.strip(), metadata=metadata,
        cash_handoff_status="PENDING" if method == "CASH" and cash_session is None else "NOT_REQUIRED")
    payment.full_clean()
    save_tracked(payment)
    for unit, applied, quantity in allocations:
        track(PaymentAllocation.objects.create(payment=payment, order_line=unit["line"], unit_number=unit["unit_number"], quantity=quantity, amount=applied))
    if method == "CASH":
        from apps.cash.services import record_direct_cash_payment, create_pending_handoff
        if cash_session is not None:
            record_direct_cash_payment(payment, cash_session, user)
        else:
            create_pending_handoff(payment)
    _log(order, user, "PAYMENT_RECORDED", f"Pago {payment.get_method_display()}: Q{amount}", payment_id=payment.pk, amount=str(amount), status=payment.status)
    _refresh(order, user)
    return payment


@sync_atomic('local')
@transaction.atomic
def create_selected_payment(target, selection, method, user, **options):
    _require(user, "record_payment")
    order, account = _locked_target(target)
    return _create(order, account, _select(_available_units(order, account), selection), method, user, **options)


@sync_atomic('local')
@transaction.atomic
def create_amount_payment(target, amount, method, user, *, unit_keys=None, **options):
    _require(user, "record_payment")
    amount = _money(amount)
    order, account = _locked_target(target)
    return _create(order, account, _distribute(_available_units(order, account, unit_keys=unit_keys), amount), method, user, **options)


@sync_atomic('local')
@transaction.atomic
def pay_full_balance(target, method, user, **options):
    _require(user, "record_payment")
    order, account = _locked_target(target)
    units = _available_units(order, account)
    amount = _money(sum((u["available"] for u in units), ZERO))
    return _create(order, account, _distribute(units, amount), method, user, **options)


def pay_cash(target, amount_due, user, *, received_amount=None, cash_session=None):
    return create_amount_payment(target, amount_due, "CASH", user, received_amount=received_amount, cash_session=cash_session)


def _locked_payment(payment, *, active=True):
    order_id = Payment.objects.values_list("order_id", flat=True).get(pk=payment.pk)
    lock_order_day(order_id)
    order = TableOrder.objects.select_for_update().get(pk=order_id)
    current = Payment.objects.select_for_update().get(pk=payment.pk)
    if active and order.status not in ACTIVE_STATUSES:
        raise ValidationError("La cuenta no está activa.")
    return current, order


@sync_atomic('local')
@transaction.atomic
def confirm_pending_payment(payment, user):
    _require(user, "verify_transfer_payment")
    current, order = _locked_payment(payment)
    if current.status != "PENDING" or current.method not in ("TRANSFER", "DEPOSIT"):
        raise ValidationError("Este pago no está pendiente de verificación.")
    if order.order_type == "QUICK_SALE":
        from apps.orders.services import reserve_quick_sale_stock
        reserve_quick_sale_stock(order, user)
    current.status, current.confirmed_by, current.confirmed_at = "CONFIRMED", user, timezone.now()
    save_tracked(current, update_fields=["status", "confirmed_by", "confirmed_at"])
    _log(order, user, "PAYMENT_CONFIRMED", f"Pago #{current.pk} verificado", payment_id=current.pk)
    _refresh(order, user)
    return current


@sync_atomic('local')
@transaction.atomic
def reject_pending_payment(payment, user, reason):
    _require(user, "reject_transfer_payment")
    reason = _reason(reason)
    current, order = _locked_payment(payment)
    if current.status != "PENDING" or current.method not in ("TRANSFER", "DEPOSIT"):
        raise ValidationError("Este pago no está pendiente de verificación.")
    current.status = "REJECTED"
    current.metadata = {**current.metadata, "rejection_reason": reason, "rejected_by": user.pk, "rejected_at": timezone.now().isoformat()}
    save_tracked(current, update_fields=["status", "metadata"])
    if order.order_type == "QUICK_SALE":
        from apps.orders.services import release_quick_sale_stock
        release_quick_sale_stock(order, user, "Pago rechazado: " + reason)
    _log(order, user, "PAYMENT_REJECTED", f"Pago #{current.pk} rechazado: {reason}", payment_id=current.pk, reason=reason)
    _refresh(order, user)
    return current


@sync_atomic('local')
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
    save_tracked(adjustment)
    for unit, applied, quantity in allocations:
        track(AdjustmentAllocation.objects.create(adjustment=adjustment, order_line=unit["line"], unit_number=unit["unit_number"], amount=applied, quantity=quantity))
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


@sync_atomic('local')
@transaction.atomic
def close_order(order, user):
    _require(user, "close_order")
    current, _ = _locked_target(order)
    _refresh(current, user, close_empty=True)
    if not can_close_order(current):
        raise ValidationError("No se puede cerrar: hay borradores, saldo, pagos pendientes o inconsistencias.")
    if current.order_type == "QUICK_SALE" and not current.fulfilled_at:
        from apps.orders.services import _ticket, reserve_quick_sale_stock
        reserve_quick_sale_stock(current, user)
        lines = list(current.lines.filter(status="SENT").prefetch_related("components", "modifiers"))
        if not lines:
            raise ValidationError("Agrega productos antes de completar la venta.")
        _ticket(current, lines, "NEW", user)
        current.fulfilled_at = timezone.now()
        save_tracked(current, update_fields=["fulfilled_at"])
    current.status, current.closed_at = "CLOSED", timezone.now()
    save_tracked(current, update_fields=["status", "closed_at", "updated_at"])
    current.table_links.filter(released_at__isnull=True).update(released_at=current.closed_at)
    _log(current, user, "CLOSED", "Cuenta liquidada y mesas liberadas")
    return current


@sync_atomic('local')
@transaction.atomic
def refund_payment(payment, user, *, reason, amount=None, allocation_ids=None, return_to_inventory=False):
    _require(user, "refund_payment")
    reason = _reason(reason)
    if type(return_to_inventory) is not bool or (amount is None) == (allocation_ids is None):
        raise ValidationError("Indica un monto o asignaciones exactas, exclusivamente.")
    current, order = _locked_payment(payment, active=False)
    if current.status != "CONFIRMED":
        raise ValidationError("Solo se reembolsa un pago confirmado con monto disponible.")
    if current.method == "CASH" and current.cash_handoff_status == "PENDING":
        raise ValidationError("Confirma primero la entrega del efectivo del mesero; no se puede reembolsar dinero aún pendiente de recepción.")
    if order.order_type == "QUICK_SALE" and not order.fulfilled_at:
        # No hubo entrega física: devolver la reserva completa antes de resolver dinero.
        # Así un refund con inventario nunca devuelve por segunda vez la misma reserva.
        from apps.orders.services import release_quick_sale_stock
        release_quick_sale_stock(order, user, "Reembolso de venta sin entregar: " + reason)
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
    refund = track(PaymentRefund.objects.create(payment=current, amount=_money(amount), reason=reason,
        created_by=user, return_to_inventory=return_to_inventory))
    for allocation, applied, quantity in entries:
        track(RefundAllocation.objects.create(refund=refund, payment_allocation=allocation, amount=applied, quantity=quantity))
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
        save_tracked(current, update_fields=["status"])
    _log(order, user, "REFUND", f"Reembolso Q{refund.amount}: {reason}", payment_id=current.pk,
         refund_id=refund.pk, amount=str(refund.amount), return_to_inventory=return_to_inventory)
    _refresh(order, user)
    return refund

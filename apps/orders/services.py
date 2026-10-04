"""Operaciones soportadas: permiso, bloqueo, validación, escritura e historial."""
from apps.sync.services import sync_atomic, track, save_tracked
from collections import Counter
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.cash.guards import lock_open_day, lock_order_day
from apps.catalog.models import Product, ModifierGroup, ModifierOption
from apps.catalog.services import catalog_products, get_product_price, is_product_available
from apps.inventory.models import InventoryMovement
from apps.inventory.services import _record_movement
from apps.tables.models import VenueTable

from .models import (ACTIVE_STATUSES, TableOrder, OrderTableLink, SubAccount, OrderLine,
                     OrderLineModifier, OrderLineComponent, PreparationTicket, PreparationTicketItem, OrderActivity)
from .queries import (get_active_order_for_table, get_operational_table_state, get_order_draft_lines,
                      get_order_sent_lines, get_order_total, get_order_committed_total, get_order_pending_total,
                      get_order_grand_total, get_subaccount_total, get_subaccount_committed_total,
                      get_subaccount_pending_total, get_subaccount_grand_total, get_order_timeline,
                      get_order_tickets, get_line_combo_components)


def _require(user, permission):
    if user is None or not user.is_active or not user.has_perm(f"orders.{permission}"):
        raise PermissionDenied("No tienes permiso para realizar esta operación.")


def _quantity(value):
    if type(value) is not int or value <= 0:
        raise ValidationError("La cantidad debe ser un entero mayor que cero.")


def _text(value, label="La nota"):
    if not isinstance(value, str):
        raise ValidationError(f"{label} debe ser texto.")
    return value.strip()


def _save(obj):
    obj.full_clean()
    save_tracked(obj)
    return obj


def _active(order):
    if order.status not in ACTIVE_STATUSES:
        raise ValidationError("La cuenta ya no está activa.")


def _locked_order(order):
    lock_order_day(order.pk)
    current = TableOrder.objects.select_for_update().get(pk=order.pk)
    _active(current)
    return current


def _locked_line(line, statuses):
    current = OrderLine.objects.get(pk=line.pk)
    order = _locked_order(current.order)
    current.refresh_from_db()
    if current.order_id != order.pk:
        raise ValidationError("La línea cambió de cuenta; vuelve a consultar la orden.")
    if current.status not in statuses:
        raise ValidationError("El estado de la línea no permite esta operación.")
    _subaccount(order, current.subaccount)
    return current, order


def _subaccount(order, subaccount):
    if subaccount is None:
        return None
    if order.billing_mode != TableOrder.BillingMode.SPLIT:
        raise ValidationError("Una cuenta única no admite subcuentas.")
    current = SubAccount.objects.get(pk=subaccount.pk)
    if current.order_id != order.pk or current.status != SubAccount.Status.OPEN:
        raise ValidationError("La subcuenta debe estar abierta y pertenecer a esta cuenta.")
    return current


def _log(order, user, kind, description, **metadata):
    activity = OrderActivity.objects.create(
        order=order, origin_order=order, user=user, activity_type=kind,
        description=description, metadata=metadata,
    )
    AuditLog.objects.create(
        user=user, action=f"orders.{kind.lower()}", entity="orders.tableorder", entity_id=str(order.pk),
        data={"activity_id": activity.pk, **metadata},
    )


def _valid_table(table, area_id=None):
    if not table.is_active or table.operational_status != "ACTIVE" or not table.area.is_active:
        raise ValidationError("La mesa y su área deben estar activas y en servicio.")
    if area_id is not None and table.area_id != area_id:
        raise ValidationError("La mesa debe pertenecer a la misma área.")


def _link(order, table):
    link, _ = OrderTableLink.objects.get_or_create(order=order, table=table)
    if link.released_at is not None:
        link.released_at = None
        save_tracked(link, update_fields=["released_at"])
    return link


@sync_atomic('local')
@transaction.atomic
def open_table_order(table, user, *, responsible_waiter=None, billing_mode="SINGLE", general_note=""):
    _require(user, "open_table_order")
    day = lock_open_day()
    from apps.reservations.queries import ensure_not_reserved
    ensure_not_reserved(table)
    return _create_table_order(table, user, day=day, responsible=responsible_waiter or user,
                               billing_mode=billing_mode, general_note=general_note)


def _create_table_order(table, user, *, day, responsible, billing_mode="SINGLE", general_note=""):
    """Primitiva interna; llamadores autorizan y bloquean la jornada antes de entrar."""
    current = VenueTable.objects.select_for_update().get(pk=table.pk)
    _valid_table(current)
    if current.order_links.filter(released_at__isnull=True).exists():
        raise ValidationError("La mesa ya tiene una cuenta activa.")
    responsible.refresh_from_db()
    if not responsible.is_active:
        raise ValidationError("El responsable debe ser un usuario activo.")
    order = _save(TableOrder(business_day=day, primary_table=current, area_id=current.area_id, opened_by=user,
                             responsible_waiter=responsible, billing_mode=billing_mode, general_note=_text(general_note)))
    _link(order, current)
    _log(order, user, "OPENED", f"Mesa abierta: {current.name}", table_id=current.pk, responsible_waiter_id=responsible.pk)
    return order


@sync_atomic('local')
@transaction.atomic
def create_subaccount(order, name, user):
    _require(user, "manage_subaccounts")
    current = _locked_order(order)
    if current.billing_mode != "SPLIT":
        raise ValidationError("La cuenta debe usar cuentas separadas.")
    account = _save(SubAccount(order=current, name=_text(name, "El nombre")))
    _log(current, user, "SUBACCOUNT_CREATED", f"Subcuenta creada: {account.name}", subaccount_id=account.pk)
    return account


@sync_atomic('local')
@transaction.atomic
def change_billing_mode(order, billing_mode, user):
    _require(user, "manage_subaccounts")
    current = _locked_order(order)
    if current.reservation_credits.exists() and billing_mode != "SINGLE":
        raise ValidationError("Una cuenta con anticipo de reserva conserva la modalidad de cuenta única.")
    if current.lines.exists() or current.subaccounts.exists():
        raise ValidationError("Solo se puede cambiar la modalidad de una cuenta sin líneas ni subcuentas.")
    if current.billing_mode != billing_mode:
        current.billing_mode = billing_mode
        _save(current)
        _log(current, user, "BILLING_MODE_CHANGED", "Modalidad de cuenta cambiada", billing_mode=billing_mode)
    return current


def _selected_modifiers(product, option_ids):
    ids = list(option_ids or [])
    if any(type(pk) is not int for pk in ids) or len(ids) != len(set(ids)):
        raise ValidationError("Las opciones deben ser identificadores únicos.")
    options = list(ModifierOption.objects.filter(pk__in=ids, is_active=True, group__product=product, group__is_active=True).order_by("pk"))
    if len(options) != len(ids):
        raise ValidationError("Hay modificadores inválidos, inactivos o de otro producto.")
    counts = Counter(option.group_id for option in options)
    for group in ModifierGroup.objects.filter(product=product, is_active=True):
        count = counts[group.pk]
        if not group.min_selections <= count <= group.max_selections:
            raise ValidationError(f"Revisa las opciones de «{group.name}»: mínimo {group.min_selections}, máximo {group.max_selections}.")
    return options


def _component_specs(product):
    # Snapshot ingredient consumption with the order, so later recipe edits do not
    # change cancellations/refunds. The prepared product keeps its own ticket route.
    def recipe_specs(item, multiplier=1):
        result = [(item.pk, multiplier, item.name, item.preparation_route)]
        if item.uses_recipe:
            result += [(row.ingredient_id, row.quantity * multiplier, row.ingredient.name, 'NONE')
                       for row in item.recipe_ingredients.select_related('ingredient')]
        return result
    specs = []
    if product.is_combo:
        for row in product.combo_components.all(): specs.extend(recipe_specs(row.component, row.quantity))
    else: specs = recipe_specs(product)
    merged = {}
    for pk, quantity, name, route in specs:
        if pk in merged:
            old = merged[pk]
            if old[3] != route: raise ValidationError('Un ingrediente no puede venderse también como preparación en el mismo combo.')
            quantity += old[1]
        merged[pk] = (pk, quantity, name, route)
    return list(merged.values())


def get_order_product_quote(product, area, quantity=1, *, modifier_option_ids=None):
    """Precio validado compartido por la vista previa y la escritura del borrador."""
    _quantity(quantity)
    if not is_product_available(product):
        raise ValidationError("Producto agotado o no disponible.")
    options = _selected_modifiers(product, modifier_option_ids)
    base_price = get_product_price(product, area)
    unit_price = base_price + sum((option.price_delta for option in options), Decimal("0.00"))
    return {"base_price": base_price, "unit_price": unit_price,
            "total": unit_price * quantity, "options": options}


@sync_atomic('local')
@transaction.atomic
def add_product_to_order(order, product, quantity, user, *, subaccount=None, modifier_option_ids=None, notes="", draft_origin=""):
    _require(user, "add_order_line")
    _quantity(quantity)
    current = _locked_order(order)
    account = _subaccount(current, subaccount)
    product = catalog_products().get(pk=product.pk)
    if not is_product_available(product):
        raise ValidationError("El producto no está disponible para venta.")
    quote = get_order_product_quote(product, current.area, quantity, modifier_option_ids=modifier_option_ids)
    options, base_price, price = quote["options"], quote["base_price"], quote["unit_price"]
    notes = _text(notes)
    specs = sorted(_component_specs(product))
    modifier_specs = [(option.pk, option.name, option.price_delta) for option in options]
    candidates = current.lines.filter(status="DRAFT", draft_origin=draft_origin, product=product, subaccount=account, notes=notes,
                                     unit_price=price, base_unit_price=base_price,
                                     product_name_snapshot=product.name, is_combo_snapshot=product.is_combo).prefetch_related("modifiers", "components")
    line = None
    for candidate in candidates:
        old_options = sorted((item.modifier_option_id, item.option_name_snapshot, item.price_delta_snapshot) for item in candidate.modifiers.all())
        old_components = sorted((item.product_id, item.quantity_per_unit, item.name_snapshot, item.route_snapshot) for item in candidate.components.all())
        if old_options == modifier_specs and old_components == specs:
            line = candidate
            line.quantity += quantity
            _save(line)
            break
    if line is None:
        line = _save(OrderLine(order=current, subaccount=account, product=product, product_name_snapshot=product.name,
                               is_combo_snapshot=product.is_combo, quantity=quantity, base_unit_price=base_price,
                               unit_price=price, notes=notes, created_by=user, draft_origin=draft_origin))
        for option in options:
            track(OrderLineModifier.objects.create(order_line=line, modifier_option=option,
                option_name_snapshot=option.name, price_delta_snapshot=option.price_delta))
        for product_id, units, name, route in specs:
            track(OrderLineComponent.objects.create(order_line=line, product_id=product_id,
                quantity_per_unit=units, name_snapshot=name, route_snapshot=route))
    _log(current, user, "PRODUCT_ADDED", f"Agregó {quantity} × {line.product_name_snapshot}", line_id=line.pk, quantity=quantity)
    return line


@sync_atomic('local')
@transaction.atomic
def increase_draft_line(line, user, quantity=1):
    _require(user, "add_order_line")
    _quantity(quantity)
    current, order = _locked_line(line, ["DRAFT"])
    current.quantity += quantity
    _save(current)
    _log(order, user, "DRAFT_UPDATED", "Cantidad pendiente aumentada", line_id=current.pk, quantity=current.quantity)
    return current


@sync_atomic('local')
@transaction.atomic
def decrease_draft_line(line, user, quantity=1):
    _require(user, "add_order_line")
    _quantity(quantity)
    current, order = _locked_line(line, ["DRAFT"])
    if quantity > current.quantity:
        raise ValidationError("No puedes quitar más unidades de las existentes.")
    if quantity == current.quantity:
        return remove_draft_line(current, user)
    current.quantity -= quantity
    _save(current)
    _log(order, user, "DRAFT_UPDATED", "Cantidad pendiente reducida", line_id=current.pk, quantity=current.quantity)
    return current


@sync_atomic('local')
@transaction.atomic
def remove_draft_line(line, user):
    _require(user, "add_order_line")
    current, order = _locked_line(line, ["DRAFT"])
    current.status = "CANCELLED"
    _save(current)
    _log(order, user, "LINE_CANCELLED", "Producto pendiente retirado, sin consumo de inventario", line_id=current.pk)
    _refresh_financial_state(order, user)
    return current


@sync_atomic('local')
@transaction.atomic
def update_draft_line_note(line, notes, user):
    _require(user, "add_order_line")
    current, order = _locked_line(line, ["DRAFT"])
    current.notes = _text(notes)
    _save(current)
    _log(order, user, "NOTE_UPDATED", "Nota de producto pendiente actualizada", line_id=current.pk, note=current.notes)
    return current


@sync_atomic('local')
@transaction.atomic
def update_order_note(order, note, user):
    _require(user, "add_order_line")
    current = _locked_order(order)
    old = current.general_note
    current.general_note = _text(note)
    if old != current.general_note:
        _save(current)
        _log(current, user, "NOTE_UPDATED", "Nota general actualizada", before=old, after=current.general_note)
    return current


def _ticket(order, lines, kind, user, reason=""):
    if order.order_type == "QUICK_SALE" and order.fulfilled_at is None and kind != "NEW":
        return None
    items = []
    for line in lines:
        options = ", ".join(item.option_name_snapshot for item in line.modifiers.all())
        for component in line.components.all():
            if component.route_snapshot == "NONE" or (component.route_snapshot == "AREA_BAR" and (line.fulfillment_mode == "TAKE_AT_BAR" or order.order_type == "QUICK_SALE")):
                continue
            description = line.product_name_snapshot
            if line.is_combo_snapshot:
                description += f" · {component.name_snapshot}"
            if options:
                description += f" ({options})"
            items.append((line, component, description))
    if not items:
        return None
    # La fila de la cuenta está bloqueada durante toda la operación.
    sequence = (order.tickets.aggregate(last=Max("sequence_number"))["last"] or 0) + 1
    ticket = PreparationTicket.objects.create(order=order, sequence_number=sequence, ticket_type=kind,
        created_by=user, table_name_snapshot=order.primary_table.name if order.primary_table_id else "",
        order_number_snapshot=order.order_number, customer_alias_snapshot=order.customer_alias,
        cash_register_snapshot=order.cash_session.register.name if order.cash_session_id else "")
    for line, component, description in items:
        PreparationTicketItem.objects.create(ticket=ticket, order_line=line, route=component.route_snapshot,
            area=order.area, quantity=line.quantity * component.quantity_per_unit,
            description_snapshot=description, notes_snapshot=(f"{line.notes}\nAnulación: {reason}".strip() if reason else line.notes))
    from .signals import preparation_ticket_created
    preparation_ticket_created.send(sender=PreparationTicket, ticket=ticket)
    return ticket


def _locked_products(lines):
    ids = {line.product_id for line in lines}
    ids.update(item.product_id for line in lines for item in line.components.all())
    return {product.pk: product for product in Product.objects.filter(pk__in=ids).order_by("pk").select_for_update()}


@sync_atomic('local')
@transaction.atomic
def send_order(order, user, *, subaccount=None, draft_origin="", fulfillment_mode="NORMAL_TABLE_SEND", defer_ticket=False):
    _require(user, "send_order")
    current = _locked_order(order)
    if fulfillment_mode not in OrderLine.FulfillmentMode.values:
        raise ValidationError("Selecciona un modo de entrega válido.")
    if fulfillment_mode == "TAKE_AT_BAR" and not (user.has_perm("orders.add_products_from_cash_register") or user.has_perm("orders.create_quick_sale")):
        raise PermissionDenied("No tienes permiso para entregar productos desde barra.")
    if defer_ticket and current.order_type != "QUICK_SALE":
        raise ValidationError("Solo una venta rápida puede esperar el pago antes de emitir cocina.")
    if current.order_type == "QUICK_SALE" and (not defer_ticket or fulfillment_mode != "TAKE_AT_BAR"):
        raise ValidationError("La venta rápida se confirma desde su flujo de cobro.")
    drafts = current.lines.filter(status="DRAFT", draft_origin=draft_origin)
    if subaccount is not None:
        account = _subaccount(current, subaccount)
        drafts = drafts.filter(subaccount=account)
    lines = list(drafts.prefetch_related("components", "modifiers"))
    if not lines:
        return None
    products = _locked_products(lines)
    required = Counter()
    for line in lines:
        _subaccount(current, line.subaccount)
        main = products[line.product_id]
        if not main.is_active or not main.visible_in_pos or not main.category.is_active:
            raise ValidationError(f"«{line.product_name_snapshot}» ya no está disponible.")
        if not line.components.all():
            raise ValidationError("La línea no tiene composición de consumo.")
        for item in line.components.all():
            product = products[item.product_id]
            if not product.is_active or not product.category.is_active or product.is_combo:
                raise ValidationError(f"El componente «{item.name_snapshot}» no está disponible.")
            if product.track_inventory:
                required[product.pk] += item.quantity_per_unit * line.quantity
    for pk, quantity in required.items():
        if products[pk].stock_quantity < quantity:
            raise ValidationError(f"Stock insuficiente de «{products[pk].name}»: se requieren {quantity}, hay {products[pk].stock_quantity}. No se envió ningún producto.")
    kind = "ADDITION" if current.activities.filter(activity_type="ORDER_SENT").exists() else "NEW"
    for line in lines:
        for item in line.components.all():
            if products[item.product_id].track_inventory:
                _record_movement(products[item.product_id], -line.quantity * item.quantity_per_unit, user,
                    "Consumo enviado a preparación", InventoryMovement.MovementType.SALE,
                    metadata={"order_id": current.pk, "line_id": line.pk, "table": current.primary_table_id})
                item.stock_deducted = True
                save_tracked(item, update_fields=["stock_deducted"])
        line.status = "SENT"
        line.fulfillment_mode = fulfillment_mode
        _save(line)
    from apps.reservations.credits import apply_available_credit
    apply_available_credit(current, user)
    _refresh_financial_state(current, user)
    ticket = None if defer_ticket else _ticket(current, lines, kind, user)
    _log(current, user, "ORDER_SENT", f"Pedido enviado: {len(lines)} líneas", line_ids=[line.pk for line in lines], ticket_id=ticket.pk if ticket else None, fulfillment_mode=fulfillment_mode, draft_origin=draft_origin, preparation_deferred=defer_ticket)
    return ticket


@sync_atomic('local')
@transaction.atomic
def cancel_sent_line(line, user, reason):
    _require(user, "cancel_sent_order_line")
    reason = _text(reason, "El motivo")
    if not reason:
        raise ValidationError("Indica el motivo de anulación.")
    current, order = _locked_line(line, ["SENT"])
    _require_no_financial_history(current)
    products = _locked_products([current])
    for item in current.components.all():
        if item.stock_deducted:
            _record_movement(products[item.product_id], current.quantity * item.quantity_per_unit, user,
                reason, InventoryMovement.MovementType.CANCELLATION_RETURN,
                metadata={"order_id": order.pk, "line_id": current.pk, "table": order.primary_table_id,
                          "source_line_id": current.source_line_id})
    ticket = _ticket(order, [current], "CANCELLATION", user, reason)
    current.status = "CANCELLED"
    _save(current)
    _log(order, user, "LINE_CANCELLED", f"Producto enviado anulado: {reason}", line_id=current.pk, reason=reason, ticket_id=ticket.pk if ticket else None)
    _refresh_financial_state(order, user)
    return current


@sync_atomic('local')
@transaction.atomic
def update_sent_line_note(line, notes, user):
    _require(user, "add_order_line")
    current, order = _locked_line(line, ["SENT"])
    before = current.notes
    current.notes = _text(notes)
    if current.notes != before:
        _save(current)
        ticket = _ticket(order, [current], "UPDATE", user)
        _log(order, user, "NOTE_UPDATED", "Nota adicional de producto enviado", line_id=current.pk,
             before=before, after=current.notes, ticket_id=ticket.pk if ticket else None)
    return current


def _refresh_financial_state(order, user):
    if order.payments.exists() or order.adjustments.exists() or order.reservation_credits.exists():
        from apps.payments.services import refresh_order_payment_status
        refresh_order_payment_status(order, user)


def _require_no_financial_history(line):
    if line.paymentallocation_set.exists() or line.adjustmentallocation_set.exists() or line.reservation_credit_allocations.exists():
        raise ValidationError("La línea tiene historial financiero: no se puede trasladar ni anular; utiliza el flujo de reembolso cuando corresponda.")


def _clone_line(line, quantity, destination, user):
    clone = _save(OrderLine(order=line.order, subaccount=destination, product=line.product,
        product_name_snapshot=line.product_name_snapshot, is_combo_snapshot=line.is_combo_snapshot,
        quantity=quantity, unit_price=line.unit_price, base_unit_price=line.base_unit_price, notes=line.notes,
        status=line.status, created_by=user, source_line=line.source_line or line,
        draft_origin=line.draft_origin, fulfillment_mode=line.fulfillment_mode))
    for item in line.modifiers.all():
        track(OrderLineModifier.objects.create(order_line=clone, modifier_option_id=item.modifier_option_id,
            option_name_snapshot=item.option_name_snapshot, price_delta_snapshot=item.price_delta_snapshot))
    for item in line.components.all():
        track(OrderLineComponent.objects.create(order_line=clone, product_id=item.product_id,
            quantity_per_unit=item.quantity_per_unit, name_snapshot=item.name_snapshot,
            route_snapshot=item.route_snapshot, stock_deducted=item.stock_deducted))
    return clone


@sync_atomic('local')
@transaction.atomic
def move_line_to_subaccount(line, destination, user, *, quantity=None):
    _require(user, "manage_subaccounts")
    current, order = _locked_line(line, ["DRAFT", "SENT"])
    if order.billing_mode != "SPLIT" or destination is None:
        raise ValidationError("Selecciona una subcuenta de destino en una cuenta separada.")
    _require_no_financial_history(current)
    target = _subaccount(order, destination)
    quantity = current.quantity if quantity is None else quantity
    _quantity(quantity)
    if quantity > current.quantity:
        raise ValidationError("La cantidad supera la de la línea.")
    if current.subaccount_id == target.pk:
        return current
    origin = current.subaccount_id
    if quantity == current.quantity:
        current.subaccount = target
        _save(current)
        result = current
    else:
        result = _clone_line(current, quantity, target, user)
        current.quantity -= quantity
        _save(current)
    _log(order, user, "LINE_MOVED", f"{quantity} unidades trasladadas a {target.name}",
         line_id=current.pk, destination_line_id=result.pk, from_subaccount=origin, to_subaccount=target.pk, quantity=quantity)
    _refresh_financial_state(order, user)
    return result


@sync_atomic('local')
@transaction.atomic
def move_order_to_table(order, destination_table, user):
    _require(user, "move_order_table")
    current = _locked_order(order)
    if current.order_type != "TABLE":
        raise ValidationError("Una venta rápida no se puede trasladar a una mesa.")
    tables = {table.pk: table for table in VenueTable.objects.filter(
        pk__in=[current.primary_table_id, destination_table.pk]).order_by("pk").select_for_update()}
    destination = tables[destination_table.pk]
    _valid_table(destination, current.area_id)
    if destination.pk == current.primary_table_id:
        return current
    if current.table_links.filter(released_at__isnull=True).count() != 1:
        raise ValidationError("El traslado de un grupo de mesas unidas queda pendiente de una regla física; no se deshace la unión.")
    from apps.reservations.queries import ensure_not_reserved
    ensure_not_reserved(destination)
    if destination.order_links.filter(released_at__isnull=True).exists():
        raise ValidationError("La mesa de destino está ocupada.")
    old = current.primary_table_id
    current.table_links.filter(table_id=old).update(released_at=timezone.now())
    _link(current, destination)
    current.primary_table = destination
    _save(current)
    _log(current, user, "TABLE_MOVED", f"Cuenta trasladada a {destination.name}", from_table=old, to_table=destination.pk)
    return current


@sync_atomic('local')
@transaction.atomic
def join_table_to_order(order, table, user):
    _require(user, "merge_orders")
    current = _locked_order(order)
    if current.order_type != "TABLE":
        raise ValidationError("Una venta rápida no admite mesas.")
    table = VenueTable.objects.select_for_update().get(pk=table.pk)
    _valid_table(table, current.area_id)
    from apps.reservations.queries import ensure_not_reserved
    ensure_not_reserved(table)
    if table.order_links.filter(released_at__isnull=True).exists():
        raise ValidationError("La mesa está ocupada; utiliza la unión de cuentas existentes.")
    _link(current, table)
    _log(current, user, "TABLES_MERGED", f"Mesa vinculada: {table.name}", table_id=table.pk)
    return current


@sync_atomic('local')
@transaction.atomic
def merge_orders(primary_order, secondary_order, user):
    _require(user, "merge_orders")
    if primary_order.pk == secondary_order.pk:
        raise ValidationError("Selecciona dos cuentas distintas.")
    day = lock_order_day(primary_order.pk)
    if lock_order_day(secondary_order.pk).pk != day.pk:
        raise ValidationError("Solo se pueden unir cuentas de la misma jornada.")
    orders = {order.pk: order for order in TableOrder.objects.filter(pk__in=[primary_order.pk, secondary_order.pk]).order_by("pk").select_for_update()}
    primary, secondary = orders[primary_order.pk], orders[secondary_order.pk]
    _active(primary)
    _active(secondary)
    if primary.order_type != "TABLE" or secondary.order_type != "TABLE":
        raise ValidationError("Solo se pueden unir cuentas de mesas.")
    if any(o.payments.exists() or o.adjustments.exists() or o.reservation_credits.exists() for o in (primary, secondary)):
        raise ValidationError("No se pueden unir cuentas con historial financiero. Une las cuentas antes de cobrar o ajustar.")
    if primary.area_id != secondary.area_id:
        raise ValidationError("Solo se pueden unir cuentas de la misma área.")
    if primary.subaccounts.filter(status="CLOSED").exists() or secondary.subaccounts.filter(status="CLOSED").exists():
        raise ValidationError("No se pueden unir cuentas con subcuentas cerradas.")
    links = list(secondary.table_links.filter(released_at__isnull=True))
    list(VenueTable.objects.filter(pk__in=[link.table_id for link in links]).order_by("pk").select_for_update())
    if secondary.billing_mode == "SPLIT":
        primary.billing_mode = "SPLIT"
    if secondary.general_note:
        primary.general_note = (primary.general_note + f"\n[Cuenta #{secondary.order_number}] {secondary.general_note}").strip()
    _save(primary)
    # La FK compuesta de subcuenta/línea es diferida para hacer el traslado atómico.
    secondary.subaccounts.update(order=primary)
    secondary.lines.update(order=primary)
    secondary.activities.update(order=primary)
    for link in links:
        link.released_at = timezone.now()
        save_tracked(link, update_fields=["released_at"])
        _link(primary, link.table)
    secondary.status = "MERGED"
    secondary.merged_into = primary
    secondary.closed_at = timezone.now()
    _save(secondary)
    _log(primary, user, "TABLES_MERGED", f"Cuenta #{secondary.order_number} unida a #{primary.order_number}", secondary_order_id=secondary.pk, table_ids=[link.table_id for link in links])
    return primary


@sync_atomic('local')
@transaction.atomic
def release_quick_sale_stock(order, user, reason):
    """Liberación interna autorizada por rechazo o cancelación; conserva el historial financiero."""
    current = _locked_order(order)
    if current.order_type != 'QUICK_SALE' or current.fulfilled_at:
        raise ValidationError('Solo se puede liberar una venta rápida aún no entregada.')
    reason = _text(reason, 'El motivo')
    if not reason:
        raise ValidationError('Indica el motivo para liberar la reserva.')
    lines = list(current.lines.filter(status='SENT').prefetch_related('components'))
    products = _locked_products(lines)
    for line in lines:
        for item in line.components.all():
            if item.stock_deducted:
                _record_movement(products[item.product_id], line.quantity * item.quantity_per_unit, user, reason,
                    InventoryMovement.MovementType.CANCELLATION_RETURN, metadata={'order_id':current.pk,'line_id':line.pk,'reservation_release':True})
                item.stock_deducted = False
                save_tracked(item, update_fields=['stock_deducted'])
    current.reservation_released_at = timezone.now()
    save_tracked(current, update_fields=['reservation_released_at','updated_at'])
    _log(current, user, 'NOTE_UPDATED', 'Reserva liberada: ' + reason, reservation_released=True)
    return current


@sync_atomic('local')
@transaction.atomic
def reserve_quick_sale_stock(order, user):
    current = _locked_order(order)
    if current.order_type != 'QUICK_SALE' or not current.reservation_released_at:
        return current
    if current.payments.filter(refunds__isnull=False).exists():
        raise ValidationError('Esta venta sin entregar tiene reembolsos. Resuelve los pagos restantes y anúlala; inicia otra venta para continuar.')
    lines = list(current.lines.filter(status='SENT').prefetch_related('components'))
    products = _locked_products(lines)
    needed = Counter()
    for line in lines:
        main = products[line.product_id]
        if not main.is_active or not main.visible_in_pos or not main.category.is_active:
            raise ValidationError(f'«{main.name}» ya no está disponible.')
        for item in line.components.all():
            product = products[item.product_id]
            if not product.is_active:
                raise ValidationError(f'«{product.name}» ya no está disponible.')
            if product.track_inventory and not item.stock_deducted:
                needed[product.pk] += line.quantity * item.quantity_per_unit
    for pk, quantity in needed.items():
        if products[pk].stock_quantity < quantity:
            raise ValidationError(f'Stock insuficiente de «{products[pk].name}» para continuar esta venta.')
    for line in lines:
        for item in line.components.all():
            if products[item.product_id].track_inventory and not item.stock_deducted:
                _record_movement(products[item.product_id], -line.quantity * item.quantity_per_unit, user,
                    'Reserva renovada al continuar venta rápida', InventoryMovement.MovementType.SALE,
                    metadata={'order_id':current.pk,'line_id':line.pk,'reservation_renewed':True})
                item.stock_deducted = True
                save_tracked(item, update_fields=['stock_deducted'])
    current.reservation_released_at = None
    save_tracked(current, update_fields=['reservation_released_at','updated_at'])
    return current


@sync_atomic('local')
@transaction.atomic
def cancel_quick_sale(order, user, reason):
    _require(user, 'cancel_quick_sale')
    current = release_quick_sale_stock(order, user, reason)
    from apps.payments.queries import get_financial_summary
    financial = get_financial_summary(current)
    if financial['confirmed_paid'] or financial['pending_verification'] or current.adjustments.exists():
        # No inventar devolución de efectivo ni borrar pagos. Gerencia debe resolverlos.
        return current
    current.lines.exclude(status='CANCELLED').update(status='CANCELLED')
    current.status, current.closed_at = 'CANCELLED', timezone.now()
    save_tracked(current, update_fields=['status','closed_at','updated_at'])
    _log(current, user, 'LINE_CANCELLED', 'Venta rápida anulada: ' + reason, sale_cancelled=True)
    return current

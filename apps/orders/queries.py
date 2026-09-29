from decimal import Decimal

from django.db.models import Q, Sum, F, DecimalField, ExpressionWrapper

from .models import ACTIVE_STATUSES, OrderActivity, OrderLine, OrderTableLink, PreparationTicket


def get_active_order_for_table(table):
    link = OrderTableLink.objects.filter(
        table=table, released_at__isnull=True, order__status__in=ACTIVE_STATUSES,
    ).select_related("order").first()
    return link.order if link else None


def get_operational_table_state(table):
    if not table.is_active or table.operational_status != "ACTIVE" or not table.area.is_active:
        return "OUT_OF_SERVICE"
    order = get_active_order_for_table(table)
    if order:
        return order.status if order.status in ("PAYMENT_PENDING", "PARTIALLY_PAID") else "OCCUPIED"
    from apps.reservations.queries import current_reserved_tables
    return "RESERVED" if current_reserved_tables().filter(table=table).exists() else "AVAILABLE"


def get_order_draft_lines(order, subaccount=None):
    lines = order.lines.filter(status=OrderLine.Status.DRAFT)
    return lines.filter(subaccount=subaccount) if subaccount is not None else lines


def get_order_sent_lines(order, subaccount=None):
    lines = order.lines.filter(status=OrderLine.Status.SENT)
    return lines.filter(subaccount=subaccount) if subaccount is not None else lines


def _total(lines, statuses):
    amount = ExpressionWrapper(F("quantity") * F("unit_price"), output_field=DecimalField(max_digits=22, decimal_places=2))
    return lines.filter(status__in=statuses).aggregate(total=Sum(amount))["total"] or Decimal("0.00")


def get_order_committed_total(order):
    return _total(order.lines, ["SENT"])


def get_order_pending_total(order):
    return _total(order.lines, ["DRAFT"])


def get_order_grand_total(order):
    return _total(order.lines, ["DRAFT", "SENT"])


get_order_total = get_order_grand_total


def get_subaccount_committed_total(subaccount):
    return _total(subaccount.lines, ["SENT"])


def get_subaccount_pending_total(subaccount):
    return _total(subaccount.lines, ["DRAFT"])


def get_subaccount_grand_total(subaccount):
    return _total(subaccount.lines, ["DRAFT", "SENT"])


get_subaccount_total = get_subaccount_grand_total


def get_order_timeline(order):
    return OrderActivity.objects.filter(Q(order=order) | Q(origin_order=order)).select_related("user", "origin_order")


def get_order_tickets(order):
    # Las comandas originales no se renumeran ni se reescriben al unir cuentas.
    return PreparationTicket.objects.filter(Q(order=order) | Q(items__order_line__order=order)).distinct().order_by("created_at", "pk")


def get_line_combo_components(line):
    if not line.is_combo_snapshot:
        return []
    return [{"product_id": item.product_id, "name": item.name_snapshot,
             "quantity": item.quantity_per_unit * line.quantity, "route": item.route_snapshot}
            for item in line.components.all()]

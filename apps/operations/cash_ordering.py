"""Orquestación de ventas y adiciones: los servicios originales conservan la contabilidad."""
from apps.sync.services import sync_atomic
import hashlib
import json

from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.urls import reverse

from apps.cash import services as cash
from apps.orders import services as orders
from apps.orders.models import TableOrder, ACTIVE_STATUSES
from apps.payments import services as payments
from . import accounting, ordering
from .cash_views import session_error


def operating(context, permission):
    problem = session_error(context)
    if problem:
        raise ValidationError(problem)
    if not context["user"].has_perm(permission):
        raise PermissionDenied("No tienes permiso para realizar esta operación.")
    if not context["session"]:
        raise ValidationError("Abre la caja antes de continuar.")
    return cash._session(context["session"], receiving=True)


def origin(context):
    return f"cash:{context['session'].pk}"


def payment_context(context):
    return {"session": context["access"], "kind": "cash"}


def resolve_order(context, order_id, *, closed=False):
    session = operating(context, "orders.create_quick_sale" if TableOrder.objects.filter(pk=order_id, order_type="QUICK_SALE").exists() else "orders.add_products_from_cash_register")
    order = TableOrder.objects.select_for_update().filter(pk=order_id, area=context["register"].area, business_day=context["day"]).first()
    if order is None or (order.status not in ACTIVE_STATUSES and not (closed and order.status == "CLOSED")):
        raise ValidationError("Esta cuenta ya no está disponible. Vuelve a caja y actualiza la selección.")
    if order.order_type == "QUICK_SALE":
        if order.cash_session_id != session.pk:
            raise ValidationError("Esta venta pertenece a otra sesión de caja.")
    elif not order.table_links.filter(released_at__isnull=True, table__area=context["register"].area, table__is_active=True, table__operational_status="ACTIVE").exists():
        raise ValidationError("La mesa ya no está disponible.")
    return order


@sync_atomic('local')
@transaction.atomic
def create_quick_sale(context):
    session = operating(context, "orders.create_quick_sale")
    orders._require(context["user"], "add_order_line")
    # Reabrir el borrador vacío evita ventas vacías causadas por doble clic.
    existing = TableOrder.objects.filter(cash_session=session, order_type="QUICK_SALE", status="OPEN", lines__isnull=True).first()
    if existing:
        return existing
    order = orders._save(TableOrder(order_type="QUICK_SALE", area=context["register"].area,
        business_day=context["day"], cash_session=session, opened_by=context["user"], responsible_waiter=context["user"]))
    orders._log(order, context["user"], "OPENED", "Venta rápida creada", cash_session_id=session.pk, register_id=session.register_id)
    return order


def draft_revision(order, context, account=None):
    rows = order.lines.filter(status="DRAFT", draft_origin=origin(context), subaccount=account).order_by("pk")
    return hashlib.sha256(json.dumps(list(rows.values_list("pk", "quantity", "notes", "unit_price")), default=str).encode()).hexdigest()


def draft_token(order, context, account):
    return signing.dumps({"order": order.pk, "session": context["access"].pk, "account": account.pk if account else None,
        "revision": draft_revision(order, context, account)}, salt="cash.table-addition.v1")


def verify_drafts(value, order, context, account):
    try:
        plan = signing.loads(value, salt="cash.table-addition.v1", max_age=600)
    except (signing.BadSignature, TypeError, ValueError):
        raise ValidationError("La confirmación venció. Actualiza el pedido.")
    if plan != {"order": order.pk, "session": context["access"].pk, "account": account.pk if account else None,
                "revision": draft_revision(order, context, account)}:
        raise ValidationError("El pedido cambió. Revisa los productos antes de confirmar.")


def catalog_state(context, order, account=None):
    state = ordering.order_state(order, context["user"], account, draft_origin=origin(context))
    state.update(cash_mode="quick" if order.order_type == "QUICK_SALE" else "table",
        has_kitchen=order.lines.exclude(status="CANCELLED").filter(components__route_snapshot="KITCHEN").exists(),
        send_token=draft_token(order, context, account), customer_alias=order.customer_alias,
        checkout_url=reverse("cash_operations:sale-account", args=[order.pk]))
    if order.order_type == "QUICK_SALE" and order.payments.exists():
        state["permissions"]["add_order_line"] = False
        state["permissions"]["send_order"] = False
    return state


def checkout_state(context, order):
    state = accounting.account_state(order, context["user"], include_drafts=True)
    state.update(reservation_released=bool(order.reservation_released_at), quick_sale=True, has_drafts=False, can_add=not order.payments.exists(),
        selected_name="Venta rápida",
        order_url=reverse("cash_operations:sale-order", args=[order.pk]),
        completed=order.status == "CLOSED", completion_url=reverse("cash_operations:sale-complete", args=[order.pk]))
    return state


@sync_atomic('local')
@transaction.atomic
def pay_quick_sale(context, order, token, method, data):
    order = resolve_order(context, order.pk)
    if order.order_type != "QUICK_SALE":
        raise ValidationError("El cobro desde este flujo solo corresponde a una venta rápida.")
    user = context["user"]
    payments._require(user, "record_payment")
    payments._require(user, "close_order")
    orders._require(user, "send_order")
    plan = accounting.read_plan(token, payment_context(context), order, None)
    if order.lines.filter(status="DRAFT").exists():
        orders.send_order(order, user, draft_origin=origin(context), fulfillment_mode="TAKE_AT_BAR", defer_ticket=True)
    orders.reserve_quick_sale_stock(order, user)
    options = {"cash_session": context["session"], "received_amount": data.get("received", "")} if method == "CASH" else {"card_approved": True} if method == "CARD" else {"reference": data.get("reference", "")}
    payment = payments.create_amount_payment(order, plan["amount"], method, user, unit_keys=plan["scope_keys"], **options)
    # El primer pago inmoviliza stock; un fallo revierte stock, líneas, pago y movimiento.
    # Cocina espera hasta que todos los métodos estén confirmados y sin saldo.
    if payments.can_close_order(order):
        payments.close_order(order, user)
    order.refresh_from_db()
    return payment

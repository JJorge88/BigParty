from apps.core.configuration import enabled_methods
from django.contrib import messages
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from apps.printing.services import order_print_status

from apps.orders import services as orders
from apps.orders.models import TableOrder, ACTIVE_STATUSES
from apps.payments import services as payments
from apps.payments.queries import get_financial_summary
from . import cash_ordering as ops, ordering, accounting
from .cash_views import required, safe_context, error, json_request
from .catalog_actions import apply_action
from .queries import get_operational_map, money_label


def fail(request, exc):
    return error(request, ordering.friendly_error(exc) if isinstance(exc, ValidationError) else str(exc), 403 if isinstance(exc, PermissionDenied) else 409)


def paths(order):
    return {"order_url": reverse("cash_operations:sale-order", args=[order.pk]),
        "account_url": reverse("cash_operations:sale-account", args=[order.pk]),
        "back_url": reverse("cash_operations:quick-sales" if order.order_type == "QUICK_SALE" else "cash_operations:tables")}


@require_GET
@required
def quick_sales(request):
    try:
        ops.operating(request.cash, "orders.create_quick_sale")
    except (ValidationError, PermissionDenied) as exc:
        return fail(request, exc)
    rows = TableOrder.objects.filter(cash_session=request.cash["session"], order_type="QUICK_SALE", status__in=ACTIVE_STATUSES).order_by("-pk")
    data = {**safe_context(request.cash), "sales": [{"id": row.pk, "number": row.order_number, "alias": row.customer_alias,
        "cancel_url": reverse("cash_operations:cancel-sale", args=[row.pk]) if request.cash["user"].has_perm("orders.cancel_quick_sale") else "",
        "status": "Reserva liberada · resolver o continuar" if row.reservation_released_at else "Pago pendiente de verificación" if row.status == "PAYMENT_PENDING" else "Pago parcial" if row.payments.exists() else "Borrador",
        "url": reverse("cash_operations:sale-account" if row.payments.exists() else "cash_operations:sale-order", args=[row.pk])} for row in rows]}
    return render(request, "operations/cash/quick_sales.html", data)


@require_POST
@required
def new_sale(request):
    try:
        order = ops.create_quick_sale(request.cash)
    except (ValidationError, PermissionDenied) as exc:
        return fail(request, exc)
    next_url = reverse("cash_operations:sale-order", args=[order.pk])
    return JsonResponse({"next": next_url}) if json_request(request) else redirect(next_url)


@require_GET
@required
def tables(request):
    try:
        ops.operating(request.cash, "orders.add_products_from_cash_register")
    except (ValidationError, PermissionDenied) as exc:
        return fail(request, exc)
    area = request.cash["register"].area
    data = get_operational_map(area)
    for group in data["groups"]:
        for table in group["tables"]:
            table["url"] = (reverse("cash_operations:sale-order", args=[table["order_id"]])
                if table["order_id"] and table["state"] != "OUT_OF_SERVICE" else "")
    return render(request, "operations/cash/tables.html", {
        **safe_context(request.cash), "map": data, "area": area})


@require_GET
@required
def catalog(request, order_id):
    try:
        order = ops.resolve_order(request.cash, order_id)
        account = ordering.selected_account(order, request.GET.get("subaccount"))
        state = ops.catalog_state(request.cash, order, account)
    except (ValidationError, PermissionDenied) as exc:
        return fail(request, exc)
    if json_request(request):
        return JsonResponse({"success": True, "state": state})
    return render(request, "operations/cash/catalog.html", {**safe_context(request.cash), **paths(order), "order": order,
        "state": state, "area": order.area, "quick_sale": order.order_type == "QUICK_SALE",
        "cart_title": "Venta actual" if order.order_type == "QUICK_SALE" else "Productos a cargar",
        "send_label": "Cobrar" if order.order_type == "QUICK_SALE" else "Cargar a " + order.display_name,
        "total_label": "Total", "cart_hint": "Sin entrega hasta completar el pago." if order.order_type == "QUICK_SALE" else "Se suma a la cuenta existente.",
        "catalog_eyebrow": "PRODUCTOS"})


@require_POST
@required
def catalog_action(request, order_id, action):
    allowed = {"agregar", "cotizar", "aumentar", "reducir", "eliminar", "nota", "cuenta", "enviar", "cobrar"}
    if action not in allowed:
        return error(request, "Esta acción no está disponible.", 404)
    try:
        with transaction.atomic():
            order = ops.resolve_order(request.cash, order_id)
            user = request.cash["user"]
            account = ordering.selected_account(order, request.POST.get("subaccount"), required=action != "cuenta")
            quick = order.order_type == "QUICK_SALE"
            if quick and order.payments.exists() and action != "cobrar":
                raise ValidationError("Esta venta ya tiene pagos. Continúa al cobro para completar el saldo.")
            if action == "cobrar":
                if not quick:
                    raise ValidationError("Este flujo solo carga productos a la mesa; no realiza cobros.")
                if not order.lines.exclude(status="CANCELLED").exists():
                    raise ValidationError("Agrega productos antes de cobrar.")
                alias = request.POST.get("alias", "").strip()
                if len(alias) > 100:
                    raise ValidationError("El alias admite hasta 100 caracteres.")
                if order.payments.exists() and alias != order.customer_alias:
                    raise ValidationError("El alias ya está confirmado con el primer pago.")
                if order.customer_alias != alias:
                    before = order.customer_alias
                    order.customer_alias = alias
                    orders._save(order)
                    orders._log(order, user, "NOTE_UPDATED", "Alias de venta rápida actualizado", before=before, customer_alias=alias)
                return JsonResponse({"next": reverse("cash_operations:sale-account", args=[order.pk])})
            if action == "enviar":
                if quick:
                    raise ValidationError("Utiliza Cobrar para confirmar esta venta rápida.")
                ops.verify_drafts(request.POST.get("send_token"), order, request.cash, account)
            result = apply_action(order, user, account, action, request.POST, draft_origin=ops.origin(request.cash),
                fulfillment_mode=request.POST.get("fulfillment_mode", "NORMAL_TABLE_SEND"))
            account = result.pop("account")
            if "quote" in result:
                return JsonResponse({"success": True, **result})
            order.refresh_from_db()
            if action == "enviar":
                result["message"] = ("Productos cargados a " if request.POST.get("fulfillment_mode") == "TAKE_AT_BAR" else "Pedido enviado a ") + order.display_name
                if "Cocina" in result["destinations"]:
                    result["message"] += " · Cocina"
            return JsonResponse({"success": True, **result, "state": ops.catalog_state(request.cash, order, account)})
    except (ValidationError, PermissionDenied) as exc:
        response = fail(request, exc)
        # El cliente puede actualizar para recuperar borradores sin repetir escrituras.
        return response


@require_GET
@required
def checkout(request, order_id):
    try:
        order = ops.resolve_order(request.cash, order_id, closed=True)
        if order.order_type != "QUICK_SALE":
            raise ValidationError("El cobro de mesas no está disponible desde este flujo.")
        if not request.cash["user"].has_perm("payments.record_payment"):
            raise PermissionDenied("No tienes permiso para cobrar ventas.")
        if order.status == "CLOSED":
            return JsonResponse({"next": reverse("cash_operations:sale-complete", args=[order.pk])}) if json_request(request) else redirect("cash_operations:sale-complete", order_id=order.pk)
        state = ops.checkout_state(request.cash, order)
    except (ValidationError, PermissionDenied) as exc:
        return fail(request, exc)
    if json_request(request):
        return JsonResponse({"state": state})
    return render(request, "operations/cash/checkout.html", {**safe_context(request.cash), **paths(order), "order": order, "state": state, "payment_methods": enabled_methods(), "area": order.area})


@require_POST
@required
def checkout_action(request, order_id, action):
    methods = {"efectivo": "CASH", "tarjeta": "CARD", "transferencia": "TRANSFER", "deposito": "DEPOSIT"}
    if action not in (*methods, "preparar", "mixto", "cerrar"):
        return error(request, "Esta acción no está disponible.", 404)
    try:
        with transaction.atomic():
            order = ops.resolve_order(request.cash, order_id)
            if order.order_type != "QUICK_SALE":
                raise ValidationError("No se cobra una mesa desde este flujo.")
            payments._require(request.cash["user"], "record_payment")
            if action in ("preparar", "mixto"):
                data = request.POST.copy()
                data["mode"] = "amount" if action == "mixto" else "full"
                quote = accounting.prepare_payment(ops.payment_context(request.cash), order, None, data)
                return JsonResponse({"quote": quote})
            if action == "cerrar":
                payments.close_order(order, request.cash["user"])
                return JsonResponse({"next": reverse("cash_operations:sale-complete", args=[order.pk])})
            payment = ops.pay_quick_sale(request.cash, order, request.POST.get("token"), methods[action], request.POST)
            # El servicio relee su propia instancia; volver a leer la cabecera original.
            order.refresh_from_db()
            if order.status == "CLOSED":
                return JsonResponse({"next": reverse("cash_operations:sale-complete", args=[order.pk])})
            return JsonResponse({"success": True, "message": "Pago pendiente de verificación. No entregar todavía." if payment.status == "PENDING" else "Pago parcial registrado. Completa el saldo antes de entregar.",
                "payment": {"amount": money_label(payment.amount), "change": money_label(payment.change_due), "status": payment.status},
                "state": ops.checkout_state(request.cash, order)})
    except (ValidationError, PermissionDenied) as exc:
        return fail(request, exc)


@require_GET
@required
def complete(request, order_id):
    try:
        order = ops.resolve_order(request.cash, order_id, closed=True)
        if order.order_type != "QUICK_SALE" or order.status != "CLOSED":
            raise ValidationError("Esta venta todavía no está completada.")
        data = {"printing": order_print_status(order),
            "receipt_url": reverse("cash_operations:receipt", args=[order.pk]) if request.cash["user"].has_perm("printing.print_customer_receipt") else "",
            "number": order.order_number, "alias": order.customer_alias, "total": money_label(get_financial_summary(order)["charge_total"]),
            "methods": ", ".join(dict.fromkeys(payment.get_method_display() for payment in order.payments.filter(status="CONFIRMED").order_by("pk"))),
            "kitchen": order.tickets.filter(items__route="KITCHEN").exists()}
    except (ValidationError, PermissionDenied) as exc:
        return fail(request, exc)
    return render(request, "operations/cash/complete.html", {**safe_context(request.cash), **data})


@require_http_methods(["GET", "POST"])
@required
def cancel_sale(request, order_id):
    try:
        order = ops.resolve_order(request.cash, order_id)
        orders._require(request.cash["user"], "cancel_quick_sale")
        if order.order_type != "QUICK_SALE":
            raise ValidationError("Esta acción solo corresponde a ventas rápidas.")
        if request.method == "POST":
            with transaction.atomic():
                order = orders.cancel_quick_sale(order, request.cash["user"], request.POST.get("reason", ""))
            messages.success(request, "Venta anulada y reserva liberada." if order.status == "CANCELLED" else
                "Reserva liberada. La venta conserva pagos o ajustes: resuélvelos antes de anularla. Continuar volverá a validar existencias.")
            return JsonResponse({"next": reverse("cash_operations:quick-sales")}) if json_request(request) else redirect("cash_operations:quick-sales")
        return render(request, "operations/cash/cancel_sale.html", {**safe_context(request.cash), "order":order})
    except (ValidationError, PermissionDenied) as exc:
        return fail(request, exc)

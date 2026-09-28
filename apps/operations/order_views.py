from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from apps.orders import services
from . import ordering as ops
from .queries import money_label
from .accounting import can_view_account
from .views import operational_required, _json


def failure(message, *, status=409, state=None):
    return JsonResponse({"success": False, "message": message, "state": state, "destinations": []}, status=status)


@require_GET
@operational_required
def order_page(request, order_id):
    context = request.operational
    try:
        order = ops.operational_order(context, order_id)
        account = ops.selected_account(order, request.GET.get("subaccount"))
        state = ops.order_state(order, context["user"], account,
            category=request.GET.get("category", "") if _json(request) else "",
            search=request.GET.get("q", "") if _json(request) else "")
    except (ValidationError, PermissionDenied) as exc:
        message = ops.friendly_error(exc) if isinstance(exc, ValidationError) else str(exc)
        status = 404 if isinstance(exc, ValidationError) else 403
        if _json(request):
            return failure(message, status=status)
        return render(request, "operations/order_unavailable.html", {"message": message}, status=status)
    if _json(request):
        return JsonResponse({"success": True, "state": state, "message": "", "destinations": []})
    return render(request, "operations/order.html", {**context, "order": order, "state": state,
        "operator_name": context["user"].get_full_name().strip() or context["user"].username,
        "idle_timeout": settings.OPERATIONAL_IDLE_TIMEOUT_SECONDS, "can_view_account": can_view_account(context["user"])})


@require_POST
@operational_required
def order_action(request, order_id, action):
    permissions = {"agregar": "add_order_line", "cotizar": "add_order_line", "aumentar": "add_order_line",
        "reducir": "add_order_line", "eliminar": "add_order_line", "nota": "add_order_line",
        "enviar": "send_order", "cuenta": "manage_subaccounts"}
    if action not in permissions:
        return failure("Esta acción no está disponible.", status=404)
    context = request.operational
    try:
        order = ops.operational_order(context, order_id, write=True, permission=permissions[action])
    except PermissionDenied as exc:
        return failure(str(exc), status=403)
    except ValidationError as exc:
        return failure(ops.friendly_error(exc))
    account = None
    try:
        if action != "cuenta":
            account = ops.selected_account(order, request.POST.get("subaccount"), required=True)
        message, destinations = "Pedido actualizado", []
        if action in ("agregar", "cotizar"):
            product = ops.product_for_order(request.POST.get("product"))
            quantity = ops.positive_id(request.POST.get("quantity", "1"), "La cantidad")
            if quantity > 9999:
                raise ValidationError("La cantidad máxima por operación es 9999.")
            modifiers = [ops.positive_id(value, "La opción") for value in request.POST.getlist("modifiers")]
            if action == "cotizar":
                quote = services.get_order_product_quote(product, order.area, quantity, modifier_option_ids=modifiers)
                return JsonResponse({"success": True, "message": "", "quote": {"total": money_label(quote["total"]),
                    "unit_price": money_label(quote["unit_price"])}, "destinations": []})
            services.add_product_to_order(order, product, quantity, context["user"], subaccount=account,
                modifier_option_ids=modifiers, notes=request.POST.get("notes", ""))
            message = f"{product.name} agregado"
        elif action in ("aumentar", "reducir", "eliminar", "nota"):
            line = order.lines.filter(pk=ops.positive_id(request.POST.get("line"), "El producto"), status="DRAFT", subaccount=account).first()
            if line is None:
                raise ValidationError("Este producto ya fue enviado, retirado o pertenece a otra cuenta. Actualiza el pedido.")
            function = {"aumentar": services.increase_draft_line, "reducir": services.decrease_draft_line,
                "eliminar": services.remove_draft_line, "nota": services.update_draft_line_note}[action]
            if action == "nota":
                function(line, request.POST.get("notes", ""), context["user"])
            else:
                function(line, context["user"])
        elif action == "cuenta":
            account = services.create_subaccount(order, request.POST.get("name", ""), context["user"])
            message = "Cuenta creada"
        elif action == "enviar":
            if not order.lines.filter(status="DRAFT", subaccount=account).exists():
                raise ValidationError("No hay productos pendientes para enviar.")
            addition = order.activities.filter(activity_type="ORDER_SENT").exists()
            ticket = services.send_order(order, context["user"], subaccount=account)
            destinations = ops.ticket_destinations(ticket, order.area)
            message = " · ".join(["Pedido enviado"] + (["Adición"] if addition else []) + destinations)
        order.refresh_from_db()
        if account:
            account.refresh_from_db()
            if account.status != "OPEN":
                account = None
        return JsonResponse({"success": True, "message": message, "state": ops.order_state(order, context["user"], account),
            "destinations": destinations})
    except ValidationError as exc:
        # Cada servicio tiene su propio savepoint: un rechazo no pierde borradores.
        order.refresh_from_db()
        if account and not order.subaccounts.filter(pk=account.pk, status="OPEN").exists():
            account = None
        return failure(ops.friendly_error(exc), state=ops.order_state(order, context["user"], account))

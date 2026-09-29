from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from apps.payments import services as payments
from . import accounting as accounts
from .ordering import operational_order, friendly_error
from .queries import money_label
from .views import operational_required, _json


def failure(message, *, status=409, state=None):
    return JsonResponse({"success": False, "message": message, "state": state}, status=status)


@require_GET
@operational_required
def account_page(request, order_id):
    context = request.operational
    try:
        order = operational_order(context, order_id, access_check=accounts.can_view_account)
        account = accounts.account_target(order, request.GET.get("subaccount"))
        state = accounts.account_state(order, context["user"], account)
    except (ValidationError, PermissionDenied) as exc:
        message = friendly_error(exc) if isinstance(exc, ValidationError) else str(exc)
        status = 404 if isinstance(exc, ValidationError) else 403
        if _json(request):
            return failure(message, status=status)
        return render(request, "operations/order_unavailable.html", {"message": message}, status=status)
    if _json(request):
        return JsonResponse({"success": True, "state": state})
    return render(request, "operations/account.html", {**context, "order": order, "state": state,
        "operator_name": context["user"].get_full_name().strip() or context["user"].username,
        "idle_timeout": settings.OPERATIONAL_IDLE_TIMEOUT_SECONDS})


@require_POST
@operational_required
def account_action(request, order_id, action):
    methods = {"efectivo": "CASH", "tarjeta": "CARD", "transferencia": "TRANSFER", "deposito": "DEPOSIT"}
    if action not in (*methods, "seleccion", "preparar", "mixto", "cerrar"):
        return failure("Esta acción no está disponible.", status=404)
    context = request.operational
    try:
        order = operational_order(context, order_id, write=True,
            permission="payments.close_order" if action == "cerrar" else "payments.record_payment")
    except PermissionDenied as exc:
        return failure(str(exc), status=403)
    except ValidationError as exc:
        return failure(friendly_error(exc))
    account = None
    try:
        if action == "cerrar":
            payments.close_order(order, context["user"])
            return JsonResponse({"success": True, "closed": True,
                "receipt_url": reverse("operations:receipt", args=[order.pk]) if context["user"].has_perm("printing.print_customer_receipt") else "",
                "message": "Cuenta cerrada", "table_name": order.primary_table.name})
        account = accounts.account_target(order, request.POST.get("subaccount"), writable=True)
        if action in ("seleccion", "preparar", "mixto"):
            data = request.POST.copy()
            if action == "seleccion":
                data["mode"] = "selection"
            if action == "mixto":
                data["mode"] = "amount"
            quote = accounts.prepare_payment(context, order, account, data)
            return JsonResponse({"success": True, "quote": quote})
        plan = accounts.read_plan(request.POST.get("token"), context, order, account)
        method = methods[action]
        options = {}
        if method == "CASH":
            options["received_amount"] = request.POST.get("received", "")
        elif method == "CARD":
            # El botón comunica que confirma un cobro ya aprobado en terminal bancaria.
            options["card_approved"] = True
        else:
            options["reference"] = request.POST.get("reference", "")
        target = account or order
        if plan["mode"] == "selection":
            payment = payments.create_selected_payment(target, plan["selection"], method, context["user"], **options)
        elif plan["mode"] == "full" and not plan["restricted"]:
            payment = payments.pay_full_balance(target, method, context["user"], **options)
        else:
            payment = payments.create_amount_payment(target, plan["amount"], method, context["user"],
                unit_keys=plan["scope_keys"], **options)
        order.refresh_from_db()
        if account:
            account.refresh_from_db()
        message = "Pago pendiente de verificación por Gerencia." if payment.status == "PENDING" else "Pago registrado"
        return JsonResponse({"success": True, "message": message,
            "payment": {"amount": money_label(payment.amount), "change": money_label(payment.change_due), "status": payment.status},
            "state": accounts.account_state(order, context["user"], account)})
    except (ValidationError, PermissionDenied) as exc:
        order.refresh_from_db()
        if account:
            account.refresh_from_db()
        message = friendly_error(exc) if isinstance(exc, ValidationError) else str(exc)
        return failure(message, status=403 if isinstance(exc, PermissionDenied) else 409,
            state=accounts.account_state(order, context["user"], account))

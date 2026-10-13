"""Adaptador de caja: permisos y navegación; la contabilidad vive en apps.cash."""
from functools import wraps

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404, JsonResponse
from django.middleware.csrf import rotate_token
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from apps.cash import services
from apps.cash.models import CashRegister, CashHandoff
from apps.cash.queries import get_pending_cash_handoffs
from . import cash_security as security

NO_DAY = "Abre tu caja para comenzar."
SCREENS = {"abrir", "activa", "meseros", "retiro", "movimientos", "cierre", "resultado", "cerrada", "comprobante"}
PERMISSIONS = {"quick": "orders.create_quick_sale", "tables": "orders.add_products_from_cash_register", "abrir": "cash.open_cash_session", "meseros": "cash.receive_waiter_cash",
    "retiro": "operations.request_cash_withdrawal", "movimientos": "cash.view_cashmovement",
    "cierre": "cash.close_cash_session", "resultado": "cash.close_cash_session",
    "cerrada": "cash.close_cash_session", "comprobante": "cash.close_cash_session"}


class ConfigurationForm(forms.Form):
    register = forms.ModelChoiceField(label="Estación de caja", queryset=CashRegister.objects.none(), empty_label="Selecciona una estación")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["register"].queryset = CashRegister.objects.filter(is_active=True, area__is_active=True).order_by("name")


def json_request(request):
    return "application/json" in request.headers.get("Accept", "")


def url(screen):
    return reverse("cash_operations:page", args=[screen])


def error(request, message, status=400, **extra):
    if json_request(request):
        return JsonResponse({"message": message, **extra}, status=status)
    return render(request, "operations/cash/message.html", {**safe_context(getattr(request, "cash", None)),
        "message": message, "back": reverse("cash_operations:index")}, status=status)


def required(view):
    @wraps(view)
    @never_cache
    @transaction.atomic
    def wrapped(request, *args, **kwargs):
        request.cash = security.context(request)
        if not request.cash:
            response = (JsonResponse({"message": "Ingresa nuevamente con tu PIN.", "next": reverse("cash_operations:access")}, status=401)
                        if json_request(request) else redirect("cash_operations:access"))
            security.delete_access(response)
            return response
        return view(request, *args, **kwargs)
    return wrapped


def safe_context(context):
    """Lista explícita: ni CashSession ni consultas de totales llegan a plantillas."""
    if not context:
        return {}
    user, register, session = context["user"], context["register"], context["session"]
    return {"authenticated": True, "register_name": register.name, "operator_name": security.name(user),
        "operator_role": user.get_role_display(), "idle_timeout": settings.CASH_IDLE_TIMEOUT_SECONDS,
        "cash_session_id": session.pk if session else "",
        "can_print_jobs": any(user.has_perm("printing." + permission) for permission in
            ("view_printjob", "retry_print_job", "reprint_preparation_ticket", "manage_printers")),
        "permissions": {
            key: user.has_perm(permission) for key, permission in PERMISSIONS.items()}}


def destination(context):
    session = context["session"]
    if not session:
        return "abrir"
    return "cerrada" if session.status == "CLOSED" else "resultado" if session.counted_at else "activa"


def session_error(context):
    session = context["session"]
    if not context["day"] and session:
        return NO_DAY
    if session and (session.register_id != context["register"].pk or session.business_day_id != context["day"].pk):
        return "Esta sesión no corresponde a la estación o jornada actual. Vuelve a ingresar."
    if session and session.cashier_id != context["user"].pk:
        return f"Esta caja tiene una sesión abierta por {security.name(session.cashier)}. Solicita al cajero titular volver a ingresar."
    return None


@never_cache
@require_GET
@required
def index(request):
    return redirect(url(destination(request.cash)))


def access_context(request, message=None):
    binding = security.identity(request)
    return {"register_name": binding[0].name if binding else None,
        "candidates": security.candidates() if binding else [], "error": message,
        "can_configure": request.user.is_authenticated and request.user.is_active and request.user.has_perm("cash.configure_cash_register_device")}


@never_cache
@sensitive_post_parameters("pin")
@require_http_methods(["GET", "POST"])
def access(request):
    if request.method == "GET":
        with transaction.atomic():
            if security.context(request, touch=False):
                return redirect("cash_operations:index")
        return render(request, "operations/cash/access.html", access_context(request))
    result = security.authenticate(request)
    if "token" not in result:
        return (JsonResponse({"message": result["message"]}, status=result["status"]) if json_request(request)
                else render(request, "operations/cash/access.html", access_context(request, result["message"]), status=result["status"]))
    rotate_token(request)
    response = JsonResponse({"next": reverse("cash_operations:index")}) if json_request(request) else redirect("cash_operations:index")
    security.set_access(response, result["token"])
    return response


@never_cache
@login_required(login_url="management:login")
@require_http_methods(["GET", "POST"])
@transaction.atomic
def configure(request):
    if not request.user.is_active or not request.user.has_perm("cash.configure_cash_register_device"):
        raise PermissionDenied
    # Misma puerta que desactivar estaciones: no emitir una vinculación obsoleta.
    security.lock_operation_gate()
    form = ConfigurationForm(request.POST or None)
    current = security.identity(request)
    if request.method == "POST" and form.is_valid():
        register = form.cleaned_data["register"]
        current_register = current[0] if current else None
        if current_register and current_register.pk != register.pk and current_register.sessions.filter(status="OPEN").exists():
            form.add_error("register", "Cierra la sesión abierta de la caja actual antes de cambiar esta computadora.")
        elif register.sessions.filter(status="OPEN").exists() and (not current_register or current_register.pk != register.pk):
            form.add_error("register", "Esta caja tiene una sesión abierta en otra computadora. Ciérrala antes de vincular este navegador.")
        else:
            security.revoke(request)
            response = redirect("cash_operations:access")
            security.set_register(response, register)
            security.delete_access(response)
            security.audit(request.user, register, "browser_configured")
            return response
    return render(request, "operations/cash/configure.html", {"form": form,
        "registers": form.fields["register"].queryset, "current_register": current[0] if current else None})


@never_cache
@require_POST
def lock(request):
    security.revoke(request)
    response = JsonResponse({"next": reverse("cash_operations:access")}) if json_request(request) else redirect("cash_operations:access")
    security.delete_access(response)
    return response


@require_POST
@required
def activity(request):
    return JsonResponse({"active": True})


def withdrawal_version(context):
    session = context["session"]
    return {"access": context["access"].pk, "session": session.pk,
            "last_movement": session.movements.order_by("-pk").values_list("pk", flat=True).first()}


def handoff_rows(day):
    return [{"id": row.pk, "waiter": security.name(row.waiter), "table": row.payment.order.display_name,
             "amount": row.amount, "time": row.created_at} for row in get_pending_cash_handoffs(day=day)]


def movement_rows(session):
    result = []
    for row in session.movements.select_related("payment__order__primary_table", "handoff__waiter").order_by("created_at", "pk"):
        reference = row.reason
        if row.payment_id:
            reference = row.payment.order.display_name
        if row.handoff_id:
            reference = f"{security.name(row.handoff.waiter)} · {reference}"
        result.append({"time": row.created_at, "type": row.get_movement_type_display(), "reference": reference,
            "amount": row.amount, "sign": "+" if row.movement_type in ("DIRECT_CASH_PAYMENT", "WAITER_HANDOFF") else "−"})
    return result


@require_GET
@required
def page(request, screen):
    if screen not in SCREENS:
        raise Http404
    context = request.cash
    problem = session_error(context)
    if problem:
        return error(request, problem, 409)
    permission = PERMISSIONS.get(screen)
    if permission and not context["user"].has_perm(permission):
        return error(request, "No tienes permiso para realizar esta operación.", 403)
    session = context["session"]
    target = destination(context)
    if (not session and screen != "abrir") or (session and screen == "abrir"):
        return redirect(url(target))
    if session and (session.status == "CLOSED" and screen not in ("cerrada", "comprobante")
                    or session.counted_at and session.status != "CLOSED" and screen != "resultado"):
        return redirect(url(target))
    if screen in ("resultado", "cerrada", "comprobante") and (not session or not session.counted_at):
        return error(request, "Primero registra el conteo físico de efectivo.", 409)
    if screen in ("cerrada", "comprobante") and session.status != "CLOSED":
        return redirect(url(target))
    data = safe_context(context)
    data["screen"] = screen
    if screen == "meseros":
        data["rows"] = handoff_rows(context["day"])
    elif screen == "movimientos":
        data["rows"] = movement_rows(session)
    elif screen == "retiro":
        data["withdrawal_token"] = signing.dumps(withdrawal_version(context), salt="cash.withdrawal.v1")
    elif screen in ("resultado", "cerrada", "comprobante"):
        # Único punto de revelación. La consulta vuelve a exigir permiso y conteo.
        data["result"] = services.get_blind_close_result(session, context["user"])
        data["difference_absolute"] = abs(data["result"]["difference"])
        data["closed_at"], data["closing_reason"] = session.closed_at, session.closing_reason
    if json_request(request):
        return JsonResponse(data)
    return render(request, "operations/cash/" + screen + ".html", data)


@require_POST
@sensitive_post_parameters("pin", "approver_pin")
@required
def action(request, action):
    screens = {"abrir": "abrir", "recibir": "meseros", "retirar": "retiro", "contar": "cierre", "cerrar": "resultado"}
    if action not in screens:
        raise Http404
    context = request.cash
    user, session = context["user"], context["session"]
    problem = session_error(context)
    if problem:
        return error(request, problem, 409)
    if not user.has_perm(PERMISSIONS[screens[action]]):
        return error(request, "No tienes permiso para realizar esta operación.", 403)
    if action == "abrir":
        if session or request.POST.get("cash_session"):
            return error(request, "Esta estación ya tiene una sesión. Actualiza la pantalla.", 409)
    else:
        if not session or str(session.pk) != request.POST.get("cash_session"):
            return error(request, "La sesión cambió. Actualiza la pantalla antes de continuar.", 409)
        if session.status != "OPEN" or (session.counted_at and action != "cerrar"):
            return error(request, "Esta caja ya está cerrada o tiene un conteo registrado. No admite nuevos movimientos.", 409)
    next_screen, message = "activa", ""
    if action == "retirar":
        try:
            token = signing.loads(request.POST.get("withdrawal_token", ""), salt="cash.withdrawal.v1", max_age=settings.CASH_IDLE_TIMEOUT_SECONDS)
        except (signing.BadSignature, ValueError, TypeError):
            token = None
        if token != withdrawal_version(context):
            return error(request, "El formulario cambió o este retiro ya fue registrado. Actualiza la pantalla.", 409)
    try:
        # Savepoint permite informar errores sin confirmar cambios parciales ni borrar intentos de PIN.
        with transaction.atomic():
            if action == "abrir":
                session = services.open_cash_session(context["register"], user, request.POST.get("opening_float"), user)
                context["access"].cash_session = session
                context["access"].business_day_id = session.business_day_id
                context["access"].save(update_fields=["cash_session", "business_day"])
                message = "Caja abierta correctamente"
            elif action == "recibir":
                handoff = CashHandoff.objects.filter(pk=request.POST.get("handoff"), payment__order__business_day=context["day"]).first()
                if not handoff:
                    return error(request, "Esta entrega no está disponible en la jornada actual.", 404)
                if handoff.status != "PENDING":
                    return error(request, "Este efectivo ya fue recibido en otra caja.", 409, refresh=True)
                services.confirm_cash_handoff(handoff, session, user)
                next_screen, message = "meseros", "Efectivo recibido"
            elif action == "retirar":
                services.create_cash_withdrawal(session, request.POST.get("amount"), request.POST.get("reason", ""), user)
                message = "Retiro registrado"
            elif action == "contar":
                services.submit_blind_cash_count(session, request.POST.get("counted_cash"), user)
                next_screen, message = "resultado", "Conteo registrado"
            elif action == "cerrar":
                services.close_cash_session(session, user, request.POST.get("reason", ""))
                next_screen, message = "cerrada", "Caja cerrada"
    except PermissionDenied:
        return error(request, "No tienes permiso para realizar esta operación.", 403)
    except (ValidationError, ValueError, TypeError, OverflowError) as exc:
        message = " ".join(exc.messages) if isinstance(exc, ValidationError) else "Revisa los datos e intenta nuevamente."
        if "inconsisten" in message.lower() or "Movimiento #" in message or "congelado" in message:
            message = "La caja necesita una revisión de Gerencia antes de continuar."
        return error(request, message, 400)
    messages.success(request, message)
    return JsonResponse({"message": message, "next": url(next_screen)}) if json_request(request) else redirect(url(next_screen))

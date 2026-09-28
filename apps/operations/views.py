from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.middleware.csrf import rotate_token
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from apps.orders.queries import get_active_order_for_table
from apps.tables.models import VenueTable
from . import security
from .forms import DeviceConfigurationForm
from .queries import get_operational_map
from .services import open_operational_table
from .ordering import can_order
from .accounting import can_view_account


def _json(request):
    return "application/json" in request.headers.get("Accept", "")


def _access_context(request, error=None):
    identity = security.device_identity(request)
    return {"device": identity[0] if identity else None,
            "waiters": security.visible_waiters() if identity else [], "error": error,
            "can_configure": request.user.is_authenticated and request.user.is_staff and request.user.has_perm("operations.configure_operational_device")}


def operational_required(view):
    @wraps(view)
    @never_cache
    @transaction.atomic
    def wrapped(request, *args, **kwargs):
        context = security.operational_context(request, touch=True)
        if context is None:
            response = JsonResponse({"message": "Tu acceso está bloqueado. Ingresa nuevamente con tu PIN.", "next": reverse("operations:access")}, status=401) if _json(request) else redirect("operations:access")
            security.delete_session_cookie(response)
            return response
        request.operational = context
        return view(request, *args, **kwargs)
    return wrapped


@never_cache
@require_GET
@transaction.atomic
def index(request):
    return redirect("operations:tables" if security.operational_context(request) else "operations:access")


@never_cache
@ensure_csrf_cookie
@sensitive_post_parameters("pin")
@require_http_methods(["GET", "POST"])
def access(request):
    if request.method == "GET":
        with transaction.atomic():
            if security.operational_context(request):
                return redirect("operations:tables")
        return render(request, "operations/access.html", _access_context(request))
    result = security.authenticate_pin(request, request.POST.get("user_id"), request.POST.get("pin"))
    if not result["ok"]:
        if _json(request):
            return JsonResponse({"message": result["message"]}, status=result["status"])
        return render(request, "operations/access.html", _access_context(request, result["message"]), status=result["status"])
    rotate_token(request)
    response = JsonResponse({"next": reverse("operations:tables")}) if _json(request) else redirect("operations:tables")
    security.set_session_cookie(response, result["token"])
    return response


@never_cache
@login_required(login_url="admin:login")
@require_http_methods(["GET", "POST"])
def configure_device(request):
    if not request.user.is_active or not request.user.is_staff or not request.user.has_perm("operations.configure_operational_device"):
        raise PermissionDenied
    form = DeviceConfigurationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        device = form.cleaned_data["device"]
        security.revoke_browser_session(request)
        response = redirect("operations:access")
        security.set_device_cookie(response, device)
        security.delete_session_cookie(response)
        security.audit(request.user, device, "browser_configured")
        return response
    return render(request, "operations/configure.html", {"form": form})


@never_cache
@require_POST
def lock(request):
    security.revoke_browser_session(request)
    response = JsonResponse({"next": reverse("operations:access")}) if _json(request) else redirect("operations:access")
    security.delete_session_cookie(response)
    return response


@require_POST
@operational_required
def activity(request):
    return JsonResponse({"active": True})


@require_GET
@operational_required
def tables(request):
    context = request.operational
    data = get_operational_map(context["area"])
    if _json(request):
        return JsonResponse(data)
    return render(request, "operations/tables.html", {**context, "map": data,
        "operator_name": context["user"].get_full_name().strip() or context["user"].username,
        "can_open": context["user"].has_perm("orders.open_table_order"),
        "can_order": can_order(context["user"]),
        "can_view_account": can_view_account(context["user"]),
        "idle_timeout": settings.OPERATIONAL_IDLE_TIMEOUT_SECONDS})


@require_POST
@operational_required
def open_table(request, table_id):
    context = request.operational
    if not context["user"].has_perm("orders.open_table_order"):
        return JsonResponse({"message": "No tienes permiso para abrir mesas."}, status=403)
    table = VenueTable.objects.filter(pk=table_id, area=context["area"], is_active=True).first()
    if table is None:
        return JsonResponse({"message": "Esta mesa no está disponible en el área del dispositivo."}, status=404)
    try:
        open_operational_table(context, table_id, request.POST.get("billing_mode"))
    except ValidationError as exc:
        occupied = get_active_order_for_table(table) is not None
        data = get_operational_map(context["area"])
        message = ("La mesa acaba de ser ocupada por otro usuario." if occupied else
                   "Esta mesa está fuera de servicio." if table.operational_status != "ACTIVE" else
                   "No hay una jornada abierta." if not data["has_open_day"] else " ".join(exc.messages))
        return JsonResponse({"message": message, "map": data}, status=409)
    return JsonResponse({"message": f"{table.name} abierta", "map": get_operational_map(context["area"]), "table_id": table_id}, status=201)

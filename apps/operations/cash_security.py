"""Identidad del navegador y PIN independientes de Admin y del dispositivo de mesero."""
from datetime import timedelta
import re
import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare

from apps.audit.models import AuditLog
from apps.cash.guards import lock_operation_gate
from apps.cash.models import BusinessDay, CashRegister, CashSession
from .models import CashAccessSession, CashPinAttempt
from .security import digest, user_auth_hash, initials, PIN_MESSAGE, LOCKED_MESSAGE

REGISTER_COOKIE = "bigparty_cash_register"
ACCESS_COOKIE = "bigparty_cash_access"
REGISTER_SALT = "bigparty.cash-register.v1"
OPERATING_PERMISSIONS = ("orders.create_quick_sale", "orders.add_products_from_cash_register", "cash.open_cash_session", "cash.receive_waiter_cash", "cash.close_cash_session",
                         "cash.view_cashmovement", "operations.request_cash_withdrawal")


def name(user):
    return user.get_full_name().strip() or user.username


def eligible(user):
    return user.is_active and user.role in ("CAJERO", "GERENTE") and any(user.has_perm(p) for p in OPERATING_PERMISSIONS)


def candidates(*, approvers=False):
    users = get_user_model().objects.filter(is_active=True).order_by("first_name", "last_name", "username")
    if not approvers:
        users = users.filter(role__in=("CAJERO", "GERENTE"))
    return [{"id": u.pk, "name": name(u), "initials": initials(name(u))} for u in users
            if (u.has_perm("cash.approve_cash_withdrawal") if approvers else eligible(u))]


def identity(request, *, lock=False):
    # Todos los bloqueos de caja comparten el orden puerta → estación → acceso.
    if lock:
        lock_operation_gate()
    try:
        payload = signing.loads(request.COOKIES.get(REGISTER_COOKIE, ""), salt=REGISTER_SALT,
                                max_age=settings.CASH_REGISTER_COOKIE_AGE)
        if not isinstance(payload, dict) or not isinstance(payload.get("browser"), str) or len(payload["browser"]) < 32:
            return None
        rows = CashRegister.objects.select_for_update(of=("self",)) if lock else CashRegister.objects
        register = rows.filter(pk=payload.get("register"), is_active=True, area__is_active=True).first()
        if register and constant_time_compare(str(register.binding_version), str(payload.get("version", ""))):
            return register, digest(payload["browser"])
    except (signing.BadSignature, ValueError, TypeError, OverflowError):
        pass
    return None


def set_register(response, register, *, browser=None):
    browser = browser or secrets.token_urlsafe(32)
    value = signing.dumps({"register": register.pk, "version": str(register.binding_version),
                           "browser": browser}, salt=REGISTER_SALT)
    response.set_cookie(REGISTER_COOKIE, value, max_age=settings.CASH_REGISTER_COOKIE_AGE,
                        httponly=True, secure=settings.SESSION_COOKIE_SECURE, samesite="Lax", path="/caja/")


def automatic_register(user):
    """Elige una caja segura sin exigir configuración previa del navegador."""
    registers = list(CashRegister.objects.select_for_update().filter(
        is_active=True, area__is_active=True).order_by("code", "pk"))
    if not registers:
        return None, "Todavía no hay cajas activas. Pide al gerente crear una caja."
    day = BusinessDay.objects.filter(status="OPEN").first()
    if day:
        own_session = CashSession.objects.filter(
            register__in=registers, business_day=day, cashier=user, status="OPEN").first()
        if own_session:
            return own_session.register, None
    cutoff = timezone.now() - timedelta(seconds=settings.CASH_IDLE_TIMEOUT_SECONDS)
    CashAccessSession.objects.filter(
        revoked_at__isnull=True, last_activity_at__lt=cutoff).update(revoked_at=timezone.now())
    previous = CashAccessSession.objects.filter(
        register__in=registers, user=user, revoked_at__isnull=True,
        cash_session__isnull=True).select_related("register").first()
    if previous:
        return previous.register, None
    occupied = set(CashAccessSession.objects.filter(
        register__in=registers, revoked_at__isnull=True).values_list("register_id", flat=True))
    open_registers = set(CashSession.objects.filter(
        register__in=registers, status="OPEN").values_list("register_id", flat=True))
    register = next((row for row in registers if row.pk not in occupied | open_registers), None)
    if register:
        return register, None
    return None, "Todas las cajas están en uso. Cierra una sesión o vuelve a intentarlo."


def set_access(response, token):
    response.set_cookie(ACCESS_COOKIE, token, httponly=True, secure=settings.SESSION_COOKIE_SECURE,
                        samesite="Lax", path="/caja/")


def delete_access(response):
    response.delete_cookie(ACCESS_COOKIE, path="/caja/", samesite="Lax")


def audit(user, register, action, **data):
    AuditLog.objects.create(user=user, action="operations.cash_" + action,
        entity="cash.cashregister", entity_id=str(register.pk), data=data)


def verify_pin(register, user_id, pin, *, approval=False):
    """Dentro de atomic y con estación bloqueada. Los errores no revierten intentos."""
    try:
        user = get_user_model().objects.get(pk=user_id)
    except (get_user_model().DoesNotExist, TypeError, ValueError, OverflowError):
        return None, PIN_MESSAGE, 400
    allowed = user.is_active and user.has_perm("cash.approve_cash_withdrawal") if approval else eligible(user)
    if not allowed:
        return None, "Este usuario no tiene permiso para autorizar retiros." if approval else PIN_MESSAGE, 403
    attempt, _ = CashPinAttempt.objects.get_or_create(register=register, user=user)
    now = timezone.now()
    if attempt.locked_until and attempt.locked_until > now:
        return None, LOCKED_MESSAGE, 429
    if attempt.locked_until:
        attempt.failed_attempts, attempt.locked_until = 0, None
    if not isinstance(pin, str) or not re.fullmatch(r"[0-9]{4,6}", pin) or not user.check_pin(pin):
        attempt.failed_attempts += 1
        attempt.last_failed_at = now
        if attempt.failed_attempts >= settings.CASH_PIN_MAX_ATTEMPTS:
            attempt.locked_until = now + timedelta(seconds=settings.CASH_PIN_LOCK_SECONDS)
        attempt.save()
        audit(user, register, "pin_failed", approval=approval, locked=bool(attempt.locked_until))
        return None, LOCKED_MESSAGE if attempt.locked_until else PIN_MESSAGE, 429 if attempt.locked_until else 400
    attempt.failed_attempts, attempt.locked_until, attempt.last_failed_at = 0, None, None
    attempt.save()
    return user, None, 200


@transaction.atomic
def authenticate(request):
    lock_operation_gate()
    try:
        proposed_user = get_user_model().objects.get(pk=request.POST.get("user_id"))
    except (get_user_model().DoesNotExist, TypeError, ValueError, OverflowError):
        return {"message": PIN_MESSAGE, "status": 400}
    if not eligible(proposed_user):
        return {"message": PIN_MESSAGE, "status": 403}
    register, selection_error = automatic_register(proposed_user)
    if selection_error:
        return {"message": selection_error, "status": 409}
    browser = secrets.token_urlsafe(32)
    binding_hash = digest(browser)
    user, error, status = verify_pin(register, request.POST.get("user_id"), request.POST.get("pin"))
    if error:
        return {"message": error, "status": status}
    CashAccessSession.objects.filter(register=register, revoked_at__isnull=True).update(revoked_at=timezone.now())
    token = secrets.token_urlsafe(32)
    day = BusinessDay.objects.filter(status="OPEN").first()
    cash_session = CashSession.objects.filter(register=register, status="OPEN", business_day=day).first() if day else None
    CashAccessSession.objects.create(register=register, user=user, business_day=day, cash_session=cash_session,
        token_hash=digest(token), binding_hash=binding_hash, auth_hash=user_auth_hash(user))
    audit(user, register, "access_granted")
    return {"token": token, "register": register, "browser": browser}


def context(request, *, touch=True):
    binding = identity(request, lock=True)
    token = request.COOKIES.get(ACCESS_COOKIE, "")
    if not binding or not token or len(token) > 128:
        return None
    register, binding_hash = binding
    access = CashAccessSession.objects.select_for_update().filter(register=register, binding_hash=binding_hash,
        token_hash=digest(token), revoked_at__isnull=True).first()
    if not access:
        return None
    now = timezone.now()
    user = access.user
    day = BusinessDay.objects.filter(status="OPEN").first()
    if (now - access.last_activity_at >= timedelta(seconds=settings.CASH_IDLE_TIMEOUT_SECONDS)
        or not eligible(user) or not constant_time_compare(access.auth_hash, user_auth_hash(user))
        or (access.cash_session_id and access.business_day_id != (day.pk if day else None))):
        access.revoked_at = now
        access.save(update_fields=["revoked_at"])
        return None
    if not access.cash_session_id and access.business_day_id != (day.pk if day else None):
        access.business_day = day
        access.save(update_fields=["business_day"])
    if touch:
        access.last_activity_at = now
        access.save(update_fields=["last_activity_at"])
    if not access.cash_session_id and day:
        existing = CashSession.objects.filter(register=register, business_day=day, status="OPEN").first()
        if existing:
            access.cash_session = existing
            access.save(update_fields=["cash_session"])
    return {"access": access, "user": user, "register": register, "day": day, "session": access.cash_session}


@transaction.atomic
def revoke(request):
    binding = identity(request, lock=True)
    if binding:
        register, binding_hash = binding
        sessions = CashAccessSession.objects.filter(register=register, binding_hash=binding_hash, revoked_at__isnull=True)
        current = sessions.first()
        sessions.update(revoked_at=timezone.now())
        if current:
            audit(current.user, register, "access_locked")

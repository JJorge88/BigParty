"""Acceso independiente del login administrativo; el servidor decide vigencia y permisos."""
from datetime import timedelta
import hashlib
import re
import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from apps.audit.models import AuditLog
from .models import OperationalDevice, OperationalSession, PinAttempt

DEVICE_COOKIE = "bigparty_device"
SESSION_COOKIE = "bigparty_operation"
DEVICE_SALT = "bigparty.operational-device.v1"
LOCKED_MESSAGE = "Demasiados intentos. Intenta nuevamente en unos minutos."
PIN_MESSAGE = "No pudimos ingresar. Revisa tu PIN e intenta nuevamente."


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def user_auth_hash(user):
    return salted_hmac("bigparty.operational-auth", user.password + "|" + user.pin_hash, algorithm="sha256").hexdigest()


def eligible(user):
    return user.is_active and user.role == "MESERO" and user.has_perm("tables.view_venuetable")


def visible_waiters():
    return [{"id": user.pk, "name": user.get_full_name().strip() or user.username,
             "initials": initials(user.get_full_name().strip() or user.username)}
            for user in get_user_model().objects.filter(is_active=True, role="MESERO").order_by("first_name", "last_name", "username") if eligible(user)]


def initials(name):
    return "".join(part[0] for part in name.split()[:2]).upper()


def device_identity(request, *, lock=False):
    value = request.COOKIES.get(DEVICE_COOKIE, "")
    try:
        payload = signing.loads(value, salt=DEVICE_SALT, max_age=settings.OPERATIONAL_DEVICE_COOKIE_AGE)
        if not isinstance(payload, dict) or not isinstance(payload.get("browser"), str) or len(payload["browser"]) < 32:
            return None
        devices = OperationalDevice.objects.select_for_update(of=("self",)) if lock else OperationalDevice.objects
        device = devices.filter(pk=payload.get("device_id"), is_active=True, area__is_active=True).first()
        if device is None or not constant_time_compare(str(device.binding_version), str(payload.get("version", ""))):
            return None
        return device, digest(payload["browser"])
    except (signing.BadSignature, ValueError, TypeError, OverflowError):
        return None


def set_device_cookie(response, device):
    value = signing.dumps({"device_id": device.pk, "version": str(device.binding_version), "browser": secrets.token_urlsafe(32)}, salt=DEVICE_SALT)
    response.set_cookie(DEVICE_COOKIE, value, max_age=settings.OPERATIONAL_DEVICE_COOKIE_AGE,
                        httponly=True, secure=settings.SESSION_COOKIE_SECURE, samesite="Lax", path="/")


def set_session_cookie(response, token):
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=settings.SESSION_COOKIE_SECURE, samesite="Lax", path="/operacion/")


def delete_session_cookie(response):
    response.delete_cookie(SESSION_COOKIE, path="/operacion/", samesite="Lax")


def audit(user, device, action, **data):
    AuditLog.objects.create(user=user, action="operations." + action, entity="operations.operationaldevice", entity_id=str(device.pk), data=data)


@transaction.atomic
def authenticate_pin(request, user_id, pin):
    identity = device_identity(request, lock=True)
    if identity is None:
        return {"ok": False, "message": "Este dispositivo aún no está configurado.", "status": 403}
    device, binding_hash = identity
    try:
        user = get_user_model().objects.get(pk=user_id)
    except (get_user_model().DoesNotExist, TypeError, ValueError, OverflowError):
        return {"ok": False, "message": PIN_MESSAGE, "status": 400}
    if not eligible(user):
        return {"ok": False, "message": PIN_MESSAGE, "status": 403}
    attempt, _ = PinAttempt.objects.get_or_create(device=device, user=user)
    now = timezone.now()
    if attempt.locked_until and attempt.locked_until > now:
        return {"ok": False, "message": LOCKED_MESSAGE, "status": 429}
    if attempt.locked_until:
        attempt.failed_attempts, attempt.locked_until = 0, None
    valid_format = isinstance(pin, str) and re.fullmatch(r"[0-9]{4,6}", pin) is not None
    if not valid_format or not user.check_pin(pin):
        attempt.failed_attempts += 1
        attempt.last_failed_at = now
        if attempt.failed_attempts >= settings.OPERATIONAL_PIN_MAX_ATTEMPTS:
            attempt.locked_until = now + timedelta(seconds=settings.OPERATIONAL_PIN_LOCK_SECONDS)
        attempt.save()
        audit(user, device, "pin_failed", locked=bool(attempt.locked_until))
        # Se devuelve el error, no se lanza: el contador debe confirmar su transacción.
        return {"ok": False, "message": LOCKED_MESSAGE if attempt.locked_until else PIN_MESSAGE,
                "status": 429 if attempt.locked_until else 400}
    attempt.failed_attempts, attempt.locked_until, attempt.last_failed_at = 0, None, None
    attempt.save()
    OperationalSession.objects.filter(device=device, binding_hash=binding_hash, revoked_at__isnull=True).update(revoked_at=now)
    token = secrets.token_urlsafe(32)
    OperationalSession.objects.create(device=device, user=user, area=device.area,
        token_hash=digest(token), binding_hash=binding_hash, auth_hash=user_auth_hash(user), last_activity_at=now)
    audit(user, device, "access_granted")
    return {"ok": True, "token": token}


def operational_context(request, *, touch=False):
    """Llamar dentro de atomic; bloquea dispositivo antes de sesión para cambios/revocaciones coherentes."""
    identity = device_identity(request, lock=True)
    token = request.COOKIES.get(SESSION_COOKIE, "")
    if identity is None or not token or len(token) > 128:
        return None
    device, binding_hash = identity
    session = OperationalSession.objects.select_for_update().filter(token_hash=digest(token), device=device, binding_hash=binding_hash, revoked_at__isnull=True).first()
    if session is None:
        return None
    now = timezone.now()
    user = session.user
    if (now - session.last_activity_at >= timedelta(seconds=settings.OPERATIONAL_IDLE_TIMEOUT_SECONDS)
        or session.area_id != device.area_id or not eligible(user)
        or not constant_time_compare(session.auth_hash, user_auth_hash(user))):
        session.revoked_at = now
        session.save(update_fields=["revoked_at"])
        return None
    if touch:
        session.last_activity_at = now
        session.save(update_fields=["last_activity_at"])
    return {"session": session, "user": user, "device": device, "area": device.area}


@transaction.atomic
def revoke_browser_session(request):
    identity = device_identity(request, lock=True)
    if identity:
        device, binding_hash = identity
        sessions = OperationalSession.objects.filter(device=device, binding_hash=binding_hash, revoked_at__isnull=True)
        current = sessions.first()
        sessions.update(revoked_at=timezone.now())
        if current:
            audit(current.user, device, "session_locked")

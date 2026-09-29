from datetime import timedelta
from functools import wraps
import json
import re
from urllib.parse import urlparse
from django.conf import settings
from django.contrib.auth import get_user_model, login, logout
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.crypto import salted_hmac, constant_time_compare
from django.views.decorators.debug import sensitive_post_parameters
from apps.operations.security import user_auth_hash
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST
from .models import GuardLoginAttempt
from .services import validate_and_use_ticket


def eligible(user):
    return user.is_authenticated and user.is_active and user.role == 'GUARDIA' and user.has_perm('events.scan_event_ticket')


def required(view):
    @wraps(view)
    @never_cache
    def wrapped(request, *args, **kwargs):
        last = request.session.get('guard_last_activity', 0)
        if (not eligible(request.user) or timezone.now().timestamp() - last >= settings.EVENT_GUARD_IDLE_SECONDS
                or not constant_time_compare(request.session.get('guard_auth_hash', ''), user_auth_hash(request.user))):
            logout(request)
            if request.method == 'POST':
                return JsonResponse({'error': 'Sesión terminada. Ingresa nuevamente.'}, status=401)
            return redirect('event-access:login')
        request.session['guard_last_activity'] = timezone.now().timestamp()
        return view(request, *args, **kwargs)
    return wrapped


def pin_login(username, pin, ip):
    user_model = get_user_model()
    keys = sorted([salted_hmac('event-pin-user', username.casefold()).hexdigest(), salted_hmac('event-pin-ip', ip).hexdigest()])
    with transaction.atomic():
        attempts = []
        for key in keys:
            GuardLoginAttempt.objects.get_or_create(key=key)
            attempts.append(GuardLoginAttempt.objects.select_for_update().get(key=key))
        now = timezone.now()
        if any(a.locked_until and a.locked_until > now for a in attempts):
            return None
        user = user_model.objects.filter(username__iexact=username).first()
        valid = bool(user and eligible(user) and len(pin) <= 12 and user.check_pin(pin))
        for attempt in attempts:
            if attempt.locked_until and attempt.locked_until <= now:
                attempt.failed = 0
            if valid:
                attempt.failed, attempt.locked_until = 0, None
            else:
                attempt.failed += 1
                if attempt.failed >= 5:
                    attempt.locked_until = now + timedelta(minutes=5)
            attempt.save()
        return user if valid else None


@never_cache
@sensitive_post_parameters('pin')
@require_http_methods(['GET', 'POST'])
def sign_in(request):
    error = ''
    if request.method == 'POST':
        user = pin_login(request.POST.get('username', '').strip()[:150], request.POST.get('pin', ''), request.META.get('REMOTE_ADDR', ''))
        if user:
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            request.session['guard_last_activity'] = timezone.now().timestamp()
            request.session['guard_auth_hash'] = user_auth_hash(user)
            request.session.set_expiry(settings.EVENT_GUARD_IDLE_SECONDS)
            return redirect('event-access:scanner')
        error = 'Acceso no disponible. Revisa usuario/PIN o espera 5 minutos si agotaste los intentos.'
    return render(request, 'events/access_login.html', {'error': error})


@required
@require_http_methods(['GET'])
def scanner(request):
    return render(request, 'events/scanner.html', {'debug': settings.DEBUG})


@required
@require_POST
def scan(request):
    try:
        payload = json.loads(request.body)
        raw = payload.get('token', '')
        if not isinstance(raw, str) or len(raw) > 2048:
            raise ValueError
    except (ValueError, AttributeError):
        return JsonResponse({'result': 'INVALID', 'label': 'Inválida'}, status=400)
    raw = raw.strip()
    if raw.startswith(('http://', 'https://')):
        parsed, base = urlparse(raw), urlparse(settings.PUBLIC_BASE_URL)
        match = re.fullmatch(r'/entrada/([A-Za-z0-9_-]{43})/', parsed.path)
        raw = match[1] if match and parsed.netloc == base.netloc and parsed.scheme == base.scheme and not parsed.query and not parsed.fragment else ''
    return JsonResponse(validate_and_use_ticket(raw, request.user))


@require_POST
@never_cache
def sign_out(request):
    logout(request)
    return redirect('event-access:login')

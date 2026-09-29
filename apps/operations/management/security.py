from functools import wraps
import secrets
from django.conf import settings
from django.contrib.auth import logout
from django.contrib.auth.forms import AuthenticationForm
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache

ROLES = ('GERENTE', 'PROPIETARIO')


class ManagementAuthenticationForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.role not in ROLES:
            raise ValidationError('Este usuario no tiene acceso a Gerencia.', code='invalid_login')


def touch(request):
    stamp = timezone.now().timestamp()
    last = request.session.get('management_last_activity')
    if (not request.user.is_authenticated or not request.user.is_active or request.user.role not in ROLES
            or not isinstance(last, (int, float)) or stamp - last >= settings.MANAGEMENT_IDLE_TIMEOUT_SECONDS):
        logout(request)
        return False
    request.session['management_last_activity'] = stamp
    request.session.set_expiry(settings.MANAGEMENT_IDLE_TIMEOUT_SECONDS)
    return True


def required(view):
    @wraps(view)
    @never_cache
    def wrapped(request, *args, **kwargs):
        if not touch(request):
            if request.headers.get('Accept') == 'application/json':
                return JsonResponse({'active':False, 'next':reverse('management:login')}, status=401)
            return redirect('management:login')
        return view(request, *args, **kwargs)
    return wrapped


def require(user, permission):
    if not user.is_active or not user.has_perm(permission):
        raise PermissionDenied('No tienes permiso para esta operación.')


def financial(user):
    return user.has_perm('cash.view_cash_session_financials')


def can_review(user):
    return any(user.has_perm('payments.' + p) for p in ('view_payment', 'verify_transfer_payment', 'reject_transfer_payment'))


def confirmation(request, action, target, revision):
    return signing.dumps({'user':request.user.pk, 'session':request.session.session_key,
        'nonce':request.session.get('management_nonce'), 'action':action, 'target':target,
        'revision':str(revision)}, salt='management.confirm.v1')


def verify_confirmation(request, action, target, revision):
    try:
        data = signing.loads(request.POST.get('confirmation', ''), salt='management.confirm.v1', max_age=600)
        expected = {'user':request.user.pk, 'session':request.session.session_key,
            'nonce':request.session.get('management_nonce'), 'action':action, 'target':target, 'revision':str(revision)}
        if request.POST.get('confirmed') != 'yes' or data != expected:
            raise ValueError
    except (signing.BadSignature, TypeError, ValueError):
        raise ValidationError('La confirmación cambió o venció. Actualiza la pantalla y confirma nuevamente.')


def start(request):
    request.session['management_nonce'] = secrets.token_urlsafe(24)
    request.session['management_last_activity'] = timezone.now().timestamp()
    request.session.set_expiry(settings.MANAGEMENT_IDLE_TIMEOUT_SECONDS)

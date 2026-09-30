"""Administración de identidades y permisos, sin asignaciones implícitas por rol."""
from apps.sync.services import sync_atomic, save_tracked
import hashlib
import re
from django.contrib.auth.hashers import is_password_usable
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from apps.audit.models import AuditLog
from apps.cash.guards import lock_operation_gate
from apps.operations.models import OperationalSession, CashAccessSession
from .models import User
from .permissions import GUARD, permission_map, whitelist, suggested


def require(actor, permission):
    # Refrescar permisos en cada escritura evita reutilizar un cache anterior.
    actor = User.objects.get(pk=actor.pk)
    if not actor.is_active or not actor.has_perm(permission):
        raise PermissionDenied('No tienes permiso para esta operación.')
    return actor


def audit(actor, target, action, **data):
    AuditLog.objects.create(user=actor, entity='accounts.user', entity_id=str(target.pk),
                            action='accounts.' + action, data=data)


def codes(target):
    return {app + '.' + code for app, code in target.user_permissions.values_list('content_type__app_label', 'codename')}


def group_codes(target):
    # ModelBackend oculta permisos de inactivos; la administración debe protegerlos igualmente.
    return {app + '.' + code for app, code in target.groups.values_list(
        'permissions__content_type__app_label', 'permissions__codename') if app and code}


def revision(target):
    inherited = sorted(group_codes(target))
    raw = repr((target.username, target.first_name, target.last_name, target.role, target.is_active,
                sorted(codes(target)), inherited, target.is_superuser, target.is_staff))
    return hashlib.sha256(raw.encode()).hexdigest()


def check_revision(target, expected):
    if expected is not None and revision(target) != expected:
        raise ValidationError('Otro administrador modificó este usuario. Actualiza la pantalla antes de guardar.')


def protect_target(actor, target):
    # Restablecer credenciales o editar un usuario más privilegiado también eleva privilegios.
    if not actor.is_superuser and (target.is_superuser or target.is_staff or
                                  not (codes(target) | group_codes(target)).issubset(actor.get_all_permissions())):
        raise PermissionDenied('Este usuario requiere un administrador con sus mismos permisos.')


def validate_new_pin(pin):
    if not isinstance(pin, str) or re.fullmatch(r'[0-9]{4,6}', pin) is None:
        raise ValidationError('El PIN debe contener entre 4 y 6 dígitos.')


def revoke_pin_sessions(target):
    now = timezone.now()
    OperationalSession.objects.filter(user=target, revoked_at__isnull=True).update(revoked_at=now)
    CashAccessSession.objects.filter(user=target, revoked_at__isnull=True).update(revoked_at=now)
    # Guardia valida huella del PIN en cada request. La sesión Gerencia no depende del PIN.


@sync_atomic('local')
@sensitive_variables()
@transaction.atomic
def save_user(data, *, actor, pk=None, expected=None):
    lock_operation_gate()
    permission = 'accounts.activate_user' if pk and set(data) == {'is_active'} else 'accounts.change_user' if pk else 'accounts.add_user'
    actor = require(actor, permission)
    target = User.objects.select_for_update().get(pk=pk) if pk else User()
    if pk:
        protect_target(actor, target)
        check_revision(target, expected)
    old = {f: getattr(target, f) for f in ('username', 'first_name', 'last_name', 'role', 'is_active')}
    new_role, new_active = data.get('role', target.role), data.get('is_active', target.is_active)
    if pk and new_role != target.role:
        require(actor, 'accounts.change_user_role')
    if pk and new_active != target.is_active:
        require(actor, 'accounts.activate_user')
    if pk and target.role == 'PROPIETARIO' and target.is_active and (new_role != 'PROPIETARIO' or not new_active):
        if not User.objects.filter(role='PROPIETARIO', is_active=True).exclude(pk=pk).exists():
            raise ValidationError('No puedes desactivar ni cambiar el rol del último propietario activo.')
    if new_role == 'GUARDIA' and pk and (target.is_superuser or (codes(target) | group_codes(target)) - GUARD):
        raise ValidationError('Retira explícitamente los permisos incompatibles antes de cambiar a Guardia.')
    for field in old:
        if field in data:
            setattr(target, field, data[field])
    if not pk:
        target.set_unusable_password()
        if new_role in ('GERENTE', 'PROPIETARIO'):
            password = data.get('password', '')
            if not password:
                raise ValidationError('Establece una contraseña segura para Gerencia.')
            validate_password(password, target)
            target.set_password(password)
        else:
            pin = data.get('pin', '')
            validate_new_pin(pin)
            target.set_pin(pin)
    elif new_role in ('GERENTE', 'PROPIETARIO') and not is_password_usable(target.password):
        raise ValidationError('Establece primero una contraseña segura antes de cambiar a este rol.')
    if User.objects.filter(username__iexact=target.username).exclude(pk=target.pk).exists():
        raise ValidationError('Ya existe un usuario con ese identificador.')
    target.full_clean(exclude=['password', 'pin_hash'])
    save_tracked(target)
    if not pk:
        audit(actor, target, 'user_created', role=target.role, active=target.is_active)
    else:
        for field, before in old.items():
            after = getattr(target, field)
            if before != after:
                action = 'role_changed' if field == 'role' else ('activated' if after else 'deactivated') if field == 'is_active' else 'identity_changed'
                audit(actor, target, action, field=field, before=before, after=after)
        if not target.is_active or old['role'] != target.role:
            revoke_pin_sessions(target)
    return target


@sync_atomic('local')
@sensitive_variables()
@transaction.atomic
def reset_credential(pk, value, *, actor, kind):
    lock_operation_gate()
    if kind not in ('pin', 'password'):
        raise ValidationError('Selecciona una credencial válida.')
    actor = require(actor, 'accounts.reset_user_pin' if kind == 'pin' else 'accounts.change_user_credentials')
    target = User.objects.select_for_update().get(pk=pk)
    protect_target(actor, target)
    if kind == 'pin':
        validate_new_pin(value)
        target.set_pin(value)
        save_tracked(target, update_fields=['pin_hash'])
        revoke_pin_sessions(target)
    else:
        validate_password(value, target)
        target.set_password(value)
        save_tracked(target, update_fields=['password'])
    audit(actor, target, 'pin_reset' if kind == 'pin' else 'password_reset')
    return target


@sync_atomic('local')
@transaction.atomic
def update_permissions(pk, selection, *, actor, expected, preset=False):
    lock_operation_gate()
    actor = require(actor, 'accounts.manage_user_permissions')
    target = User.objects.select_for_update().get(pk=pk)
    protect_target(actor, target)
    check_revision(target, expected)
    available = permission_map()
    before = codes(target)
    selected = set(selection)
    if preset:
        selected = (before & whitelist()) | suggested(target.role)
    if not selected.issubset(available):
        raise ValidationError('Selecciona únicamente permisos del catálogo BIG PARTY.')
    if target.role == 'GUARDIA' and (target.is_superuser or (selected | (before - whitelist()) | group_codes(target)) - GUARD):
        raise ValidationError('Guardia sólo admite el permiso de escanear entradas.')
    added, removed = selected - before, (before & whitelist()) - selected
    if not (added | removed).issubset(actor.get_all_permissions()) and not actor.is_superuser:
        raise PermissionDenied('Sólo puedes administrar permisos que tú mismo posees.')
    target.user_permissions.add(*(available[code] for code in added))
    target.user_permissions.remove(*(available[code] for code in removed))
    for code in sorted(added):
        audit(actor, target, 'permission_added', permission=code)
    for code in sorted(removed):
        audit(actor, target, 'permission_removed', permission=code)
    if preset:
        audit(actor, target, 'preset_applied', role=target.role, added=sorted(added))
    return target

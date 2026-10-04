from django.contrib import messages
from django.contrib.auth.hashers import is_password_usable
from django.core.exceptions import ValidationError
from django.db.models import Q, OuterRef, Subquery
from django.db.models.functions import Greatest
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from apps.accounts.models import User
from apps.accounts import management_services as services, permissions
from apps.audit.models import AuditLog
from apps.operations.models import OperationalSession, CashAccessSession
from . import security, user_forms as forms
from .catalog_views import paginate, error_on
from .views import page


def target_url(user):
    return reverse('management:user', args=[user.pk])


def pin_configured(user):
    return bool(user.pin_hash and is_password_usable(user.pin_hash))


@require_GET
@security.required
def users(request):
    security.require(request.user, 'accounts.view_user')
    rows = User.objects.annotate(recent_access=Greatest('last_login',
        Subquery(OperationalSession.objects.filter(user_id=OuterRef('pk')).order_by('-created_at').values('created_at')[:1]),
        Subquery(CashAccessSession.objects.filter(user_id=OuterRef('pk')).order_by('-created_at').values('created_at')[:1]))).order_by('first_name', 'last_name', 'username')
    role = request.GET.get('role', '')
    if role == 'inactive':
        rows = rows.filter(is_active=False)
    elif role in User.Role.values:
        rows = rows.filter(role=role)
    query = request.GET.get('q', '').strip()[:150]
    if query:
        rows = rows.filter(Q(first_name__icontains=query) | Q(last_name__icontains=query) | Q(username__icontains=query))
    data = paginate(request, rows)
    for user in data['rows']:
        user.pin_configured = pin_configured(user)
    return page(request, 'users', {**data, 'roles': User.Role.choices}, section='usuarios')


def detail_data(request, target):
    labels = {'user_created': 'Usuario creado', 'identity_changed': 'Información actualizada',
        'role_changed': 'Rol cambiado', 'activated': 'Usuario activado', 'deactivated': 'Usuario desactivado',
        'pin_reset': 'PIN restablecido', 'password_reset': 'Contraseña actualizada',
        'permission_added': 'Permiso agregado', 'permission_removed': 'Permiso retirado',
        'preset_applied': 'Permisos sugeridos aplicados', 'login': 'Ingreso a Gerencia', 'logout': 'Salida de Gerencia'}
    recent = list(AuditLog.objects.filter(entity='accounts.user', entity_id=str(target.pk)).select_related('user').order_by('-created_at')[:10])
    for item in recent:
        item.action_label = labels.get(item.action.rsplit('.', 1)[-1], 'Actividad administrativa')
    abilities = [('Tomar pedidos', 'orders.add_order_line'), ('Enviar pedidos', 'orders.send_order'), ('Cobrar', 'payments.record_payment'), ('Administrar inventario', 'inventory.receive_inventory')]
    return {'abilities': [(label, target.has_perm(code)) for label, code in abilities], 'target': target, 'has_pin': pin_configured(target), 'has_password': target.has_usable_password(),
        'pin_form': forms.CredentialForm(), 'password_form': forms.CredentialForm(kind='password'),
        'revision': services.revision(target),
        'state_confirmation': security.confirmation(request, 'user-state', target.pk, services.revision(target)),
        'recent': recent}


@require_GET
@security.required
def user(request, pk):
    security.require(request.user, 'accounts.view_user')
    target = get_object_or_404(User, pk=pk)
    return page(request, 'user', detail_data(request, target), section='usuarios')


@sensitive_variables()
@sensitive_post_parameters('pin', 'password', 'confirm')
@require_http_methods(['GET', 'POST'])
@security.required
def user_edit(request, pk=None):
    security.require(request.user, 'accounts.view_user')
    security.require(request.user, 'accounts.change_user' if pk else 'accounts.add_user')
    target = get_object_or_404(User, pk=pk) if pk else None
    form = forms.UserForm(request.POST or None, instance=target, actor=request.user)
    # Capturar antes de que ModelForm modifique la instancia en memoria.
    revision = services.revision(target) if target else ''
    if request.method == 'POST' and form.is_valid():
        try:
            if pk and not request.POST.get('revision'):
                raise ValidationError('Actualiza la pantalla antes de guardar.')
            target = services.save_user(form.cleaned_data, actor=request.user, pk=pk, expected=request.POST.get('revision') if pk else None)
            messages.success(request, 'Usuario actualizado.' if pk else 'Usuario creado. Revisa sus permisos antes de que comience a trabajar.')
            return redirect(target_url(target))
        except ValidationError as exc:
            error_on(form, exc)
    return page(request, 'user_form', {'form': form, 'target': target, 'revision': revision,
        'title': 'Editar usuario' if pk else 'Crear usuario', 'back': target_url(target) if target else reverse('management:users')}, section='usuarios', status=400 if form.errors else 200)


@sensitive_variables()
@sensitive_post_parameters('value', 'confirm')
@require_POST
@security.required
def credential(request, pk, kind):
    security.require(request.user, 'accounts.view_user')
    security.require(request.user, 'accounts.reset_user_pin' if kind == 'pin' else 'accounts.change_user_credentials')
    target = get_object_or_404(User, pk=pk)
    form = forms.CredentialForm(request.POST, kind=kind)
    if form.is_valid():
        try:
            services.reset_credential(pk, form.cleaned_data['value'], actor=request.user, kind=kind)
            messages.success(request, 'PIN restablecido' if kind == 'pin' else 'Contraseña actualizada')
            return redirect(target_url(target))
        except ValidationError as exc:
            error_on(form, exc)
    data = detail_data(request, target)
    data.update({kind + '_form': form, 'credential_error': True, 'open_dialog': kind + '-dialog'})
    return page(request, 'user', data, section='usuarios', status=400)


@require_POST
@security.required
def user_state(request, pk):
    security.require(request.user, 'accounts.view_user')
    security.require(request.user, 'accounts.activate_user')
    target = get_object_or_404(User, pk=pk)
    revision = services.revision(target)
    try:
        security.verify_confirmation(request, 'user-state', pk, revision)
        services.save_user({'is_active': not target.is_active}, actor=request.user, pk=pk, expected=revision)
        messages.success(request, 'Usuario desactivado' if target.is_active else 'Usuario activado')
        return redirect(target_url(target))
    except ValidationError as exc:
        return page(request, 'user', {**detail_data(request, target), 'error': ' '.join(exc.messages)}, section='usuarios', status=409)


@require_http_methods(['GET', 'POST'])
@security.required
def user_permissions(request, pk):
    security.require(request.user, 'accounts.view_user')
    security.require(request.user, 'accounts.manage_user_permissions')
    target = get_object_or_404(User, pk=pk)
    error = ''
    if request.method == 'POST':
        try:
            if not request.POST.get('revision'):
                raise ValidationError('Actualiza la pantalla antes de guardar.')
            preset = request.POST.get('action') == 'preset'
            if preset:
                security.verify_confirmation(request, 'user-preset', pk, services.revision(target))
            services.update_permissions(pk, request.POST.getlist('permission'), actor=request.user,
                expected=request.POST['revision'], preset=preset)
            messages.success(request, 'Permisos sugeridos aplicados' if preset else 'Permisos actualizados')
            return redirect(target_url(target))
        except ValidationError as exc:
            error = ' '.join(exc.messages)
        target = User.objects.get(pk=pk)
    selected, inherited = services.codes(target), services.group_codes(target)
    held = request.user.get_all_permissions()
    groups = []
    for title, entries in permissions.catalog().items():
        entries = {code: label for code, label in entries.items() if target.role != 'GUARDIA' or code in permissions.GUARD}
        if entries:
            groups.append({'title': title, 'entries': [{'code': code, 'label': label, 'selected': code in selected,
                'inherited': code in inherited, 'locked': not request.user.is_superuser and code not in held} for code, label in entries.items()]})
    preset_codes = permissions.suggested(target.role)
    labels = {code: label for entries in permissions.catalog().values() for code, label in entries.items()}
    return page(request, 'user_permissions', {'target': target, 'groups': groups, 'revision': services.revision(target),
        'preset_labels': [labels[code] for code in sorted(preset_codes)], 'error': error,
        'preset_confirmation': security.confirmation(request, 'user-preset', pk, services.revision(target))}, section='usuarios', status=409 if error else 200)

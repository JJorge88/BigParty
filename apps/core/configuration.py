from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from apps.audit.models import AuditLog
from apps.cash.guards import lock_operation_gate
from apps.payments.models import Payment
from .models import BusinessSettings, PaymentMethodSettings, BankTransferSettings


def business():
    return BusinessSettings.objects.first() or BusinessSettings()


def bank():
    obj = BankTransferSettings.objects.first() or BankTransferSettings()
    return obj if obj.ready else None


def payment_methods():
    saved = {x.method: x for x in PaymentMethodSettings.objects.all()}
    slugs = dict(zip(Payment.Method.values, ('efectivo', 'tarjeta', 'transferencia', 'deposito')))
    rows = []
    for index, (code, label) in enumerate(Payment.Method.choices):
        item = saved.get(code)
        rows.append(dict(code=code, name=label, slug=slugs[code], enabled=item.enabled if item else True,
                         display_order=item.display_order if item else index))
    return sorted(rows, key=lambda x: (x['display_order'], x['code']))


def enabled_methods():
    return [row for row in payment_methods() if row['enabled']]


def require_method(method):
    if PaymentMethodSettings.objects.filter(method=method, enabled=False).exists():
        raise ValidationError('Este método de pago está deshabilitado. Selecciona otro método disponible.')


@transaction.atomic
def save_configuration(user, kind, values):
    from apps.core.ops.recovery import require_operational
    require_operational()
    from apps.sync.services import enabled, own_authority
    if enabled() and ((kind == "bank") != (own_authority() == "cloud")):
        raise PermissionDenied("Configuración administrada desde su entorno de origen.")
    permissions = {'business': 'change_business_configuration', 'methods': 'change_payment_method_configuration',
                   'bank': 'change_bank_transfer_configuration'}
    if not user.is_active or not user.has_perm('core.' + permissions[kind]):
        raise PermissionDenied
    if enabled():
        from apps.sync.services import source_gate
        source_gate()
    lock_operation_gate()
    changes = {}
    if kind == 'methods':
        for index, code in enumerate(Payment.Method.values):
            obj, _ = PaymentMethodSettings.objects.get_or_create(method=code, defaults={'display_order': index})
            before = {'enabled': obj.enabled, 'display_order': obj.display_order}
            obj.enabled, obj.display_order = values[code + '_enabled'], values[code + '_order']
            obj.full_clean()
            obj.save()
            changes[code] = {'before': before, 'after': {'enabled': obj.enabled, 'display_order': obj.display_order}}
        entity = 'PaymentMethodSettings'
    else:
        model = BusinessSettings if kind == 'business' else BankTransferSettings
        allowed = ('business_name',) if kind == 'business' else ('enabled', 'bank_name', 'account_name', 'account_number', 'instructions')
        obj, _ = model.objects.get_or_create(pk=1)
        for field in allowed:
            changes[field] = {'before': getattr(obj, field), 'after': values[field]}
            setattr(obj, field, values[field])
        obj.full_clean()
        obj.save()
        entity = model.__name__
    from apps.sync.services import capture_objects
    if enabled() and kind=='bank':capture_objects([obj])
    AuditLog.objects.create(user=user, action='CONFIGURATION_UPDATED', entity=entity, entity_id='1', data={'changes': changes})

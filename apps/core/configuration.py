from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from apps.audit.models import AuditLog
from apps.cash.guards import lock_operation_gate
from apps.payments.models import Payment
from .models import BusinessSettings, BusinessOpeningHours, PaymentMethodSettings, BankTransferSettings


BUSINESS_FIELDS = {
    'business': ('business_name',),
    'location': ('latitude', 'longitude', 'address_text', 'public_phone'),
    'entry': ('minimum_entry_age', 'identification_text', 'dress_code', 'dress_code_description', 'security_text', 'admission_policy'),
}


def audit_value(value):
    from datetime import time
    from decimal import Decimal
    return str(value) if isinstance(value, (Decimal, time)) else value


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
    permissions = {**dict.fromkeys((*BUSINESS_FIELDS, 'hours'), 'change_business_configuration'), 'methods': 'change_payment_method_configuration',
                   'bank': 'change_bank_transfer_configuration'}
    if not user.is_active or not user.has_perm('core.' + permissions[kind]):
        raise PermissionDenied
    if enabled():
        from apps.sync.services import source_gate
        source_gate()
    lock_operation_gate()
    changes = {}
    if kind == 'hours':
        if len(values) != 7 or {row['weekday'] for row in values} != set(range(7)):
            raise ValidationError('Configura los siete días de la semana.')
        for row in values:
            obj, _ = BusinessOpeningHours.objects.get_or_create(weekday=row['weekday'])
            change = {}
            for field in ('is_open', 'opens_at', 'closes_at', 'sort_order'):
                change[field] = {'before': audit_value(getattr(obj, field)), 'after': audit_value(row[field])}
                setattr(obj, field, row[field])
            obj.full_clean()
            obj.save()
            changes[obj.get_weekday_display()] = change
        entity = 'BusinessOpeningHours'
    elif kind == 'methods':
        for index, code in enumerate(Payment.Method.values):
            obj, _ = PaymentMethodSettings.objects.get_or_create(method=code, defaults={'display_order': index})
            before = {'enabled': obj.enabled, 'display_order': obj.display_order}
            obj.enabled, obj.display_order = values[code + '_enabled'], values[code + '_order']
            obj.full_clean()
            obj.save()
            changes[code] = {'before': before, 'after': {'enabled': obj.enabled, 'display_order': obj.display_order}}
        entity = 'PaymentMethodSettings'
    else:
        model = BusinessSettings if kind in BUSINESS_FIELDS else BankTransferSettings
        allowed = BUSINESS_FIELDS[kind] if kind in BUSINESS_FIELDS else ('enabled', 'bank_name', 'account_name', 'account_number', 'instructions')
        obj, _ = model.objects.get_or_create(pk=1)
        for field in allowed:
            changes[field] = {'before': audit_value(getattr(obj, field)), 'after': audit_value(values[field])}
            setattr(obj, field, values[field])
        obj.full_clean()
        obj.save()
        entity = model.__name__
    from apps.sync.services import capture_objects
    if enabled() and kind=='bank':capture_objects([obj])
    AuditLog.objects.create(user=user, action='CONFIGURATION_UPDATED', entity=entity, entity_id='1', data={'changes': changes})

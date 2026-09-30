"""Visor de auditoría: proyección explícita, nunca serialización del JSON original."""
import re
from decimal import Decimal, InvalidOperation
from django import forms
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET
from apps.audit.models import AuditLog
from . import security
from .views import page

MODULES = {'Operación': ('orders.', 'operations.'), 'Caja': ('cash.', 'operations.cash_'), 'Inventario': ('catalog.', 'inventory.'),
           'Pagos': ('payments.',), 'Reservas': ('reservations.',), 'Eventos': ('events.',),
           'Impresión': ('printing.',), 'Usuarios': ('accounts.',), 'Configuración': ('CONFIGURATION_',)}
# Payment mutations use the established orders audit stream.
PAYMENT_ACTIONS = ('refund', 'adjustment_applied', 'payment_recorded', 'payment_confirmed', 'payment_rejected', 'payment_refunded', 'adjustment_created', 'discount_applied', 'courtesy_applied')
LABELS = dict(identity_changed='Editó la identidad', role_changed='Cambió el rol', activated='Activó un usuario', deactivated='Desactivó un usuario', access_granted='Inició una sesión operativa', session_locked='Bloqueó una sesión operativa', pin_failed='Registró un intento de acceso fallido', browser_configured='Configuró un dispositivo', refund='Registró un reembolso', adjustment_applied='Autorizó un ajuste', line_cancelled='Anuló un producto', order_opened='Abrió una cuenta', order_sent='Envió un pedido',
    line_added='Agregó un producto', order_closed='Cerró una cuenta', payment_recorded='Registró un pago',
    payment_confirmed='Confirmó un pago', payment_rejected='Rechazó un pago', payment_refunded='Registró un reembolso',
    discount_applied='Autorizó un descuento', courtesy_applied='Autorizó una cortesía',
    price_changed='Cambió un precio', area_price_removed='Retiró un precio de área', receipt='Registró una entrada',
    adjustment='Ajustó existencias', sale='Registró consumo', cancellation_return='Devolvió existencias por anulación',
    refund_return='Devolvió existencias por reembolso', day_opened='Abrió la jornada', day_closed='Cerró la jornada',
    day_reopened='Reabrió la jornada', session_opened='Abrió una caja', session_closed='Cerró una caja',
    withdrawal='Autorizó un retiro', handoff_received='Recibió efectivo de mesero', handoff_pending='Registró entrega pendiente',
    cash_refund='Devolvió efectivo', blind_count_submitted='Registró un conteo', direct_cash_payment='Registró cobro en caja',
    created='Creó un registro', edited='Editó un registro', published='Publicó un evento', confirmed='Confirmó una reserva',
    approved='Aprobó una reserva', arrived='Registró una llegada', cancelled='Canceló un registro', rejected='Rechazó una solicitud',
    no_show='Marcó ausencia', expired='Registró vencimiento', configured='Cambió la configuración', settings='Cambió la configuración',
    purchase_created='Registró una compra', payment_submitted='Recibió comprobante', tickets_issued='Emitió entradas',
    courtesy_issued='Emitió cortesías', scan_valid='Validó una entrada', scan_duplicate='Detectó un acceso repetido',
    user_created='Creó un usuario', user_updated='Editó un usuario', user_activated='Activó un usuario', user_deactivated='Desactivó un usuario',
    pin_reset='Restableció una credencial operativa', password_reset='Restableció una contraseña', permission_added='Concedió un permiso',
    permission_removed='Retiró un permiso', preset_applied='Aplicó permisos sugeridos', product_created='Creó un producto', product_updated='Editó un producto',
    printed='Imprimió un documento', failed='Registró una impresión fallida', retry_requested='Solicitó reimpresión', CONFIGURATION_UPDATED='Actualizó la configuración')
ENTITIES = {'tableorder':'Pedido', 'product':'Producto', 'category':'Categoría', 'user':'Usuario', 'reservation':'Reserva',
            'event':'Evento', 'eventpurchase':'Compra de evento', 'eventpurchasepayment':'Pago de evento', 'eventticket':'Entrada',
            'businessday':'Jornada', 'cashsession':'Sesión de caja', 'cashmovement':'Movimiento de caja', 'cashhandoff':'Entrega de efectivo',
            'printjob':'Impresión', 'printer':'Impresora', 'businesssettings':'Negocio', 'banktransfersettings':'Datos de transferencia',
            'paymentmethodsettings':'Métodos de pago', 'settings':'Configuración'}
NUMBERS = {'amount':'Importe', 'old_price':'Precio anterior', 'new_price':'Precio nuevo', 'quantity':'Cantidad', 'quantity_delta':'Variación',
    'stock_before':'Existencias anteriores', 'stock_after':'Existencias posteriores', 'opening_float':'Fondo inicial', 'expected':'Esperado',
    'counted':'Contado', 'counted_cash':'Efectivo contado', 'difference':'Diferencia', 'capacity':'Capacidad', 'maximum_capacity':'Capacidad máxima'}
IDS = {'order_id':'Pedido', 'line_id':'Producto del pedido', 'payment_id':'Pago', 'refund_id':'Reembolso', 'session_id':'Sesión de caja',
       'area_id':'Área', 'waiter_id':'Mesero', 'movement_id':'Movimiento', 'day_id':'Jornada'}
CONFIG_FIELDS = {'business_name':'Nombre del negocio', 'enabled':'Habilitado', 'display_order':'Orden', 'bank_name':'Banco', 'account_name':'Titular', 'account_number':'Cuenta', 'instructions':'Instrucciones'}
CONFIG_FIELDS.update(latitude='Latitud', longitude='Longitud', address_text='Dirección pública', public_phone='Teléfono público',
    minimum_entry_age='Edad mínima', identification_text='Identificación', dress_code='Vestimenta',
    dress_code_description='Detalle de vestimenta', security_text='Seguridad', admission_policy='Política de ingreso')
ENTITIES['businessopeninghours'] = 'Horarios'
SECRET = re.compile(r'password|passwd|\bpin\b|hash|secret|(?:qr|secure)[_-]?token|session[_ -]?(?:key|id)|token', re.I)


def text_value(value):
    if not isinstance(value, (str, bool, int)):
        return None
    if isinstance(value, bool):
        return 'Sí' if value else 'No'
    value = str(value)
    if SECRET.search(value) or re.search(r'[A-Za-z0-9_+/=-]{40,}', value):
        return 'Contenido reservado'
    return value[:500]


def visible_data(data):
    if not isinstance(data, dict):
        return []
    visible = []
    for key, label in {**NUMBERS, **IDS}.items():
        value = data.get(key)
        if value is None or isinstance(value, bool):
            continue
        try:
            number = Decimal(str(value))
            if not number.is_finite() or abs(number) > Decimal('1e15'):
                continue
            visible.append((label, str(number)))
        except (InvalidOperation, ValueError):
            continue
    for key, label in [('reason','Motivo'), ('business_date','Fecha comercial')]:
        value = text_value(data.get(key))
        if value:
            visible.append((label, value))
    identity_fields = {'username':'Usuario', 'first_name':'Nombre', 'last_name':'Apellido', 'role':'Rol', 'is_active':'Activo'}
    field = data.get('field')
    if isinstance(field, str) and field in identity_fields:
        before, after = text_value(data.get('before')), text_value(data.get('after'))
        if before is not None and after is not None:
            visible.append((identity_fields[field], f'{before} → {after}'))
    permission = data.get('permission')
    if isinstance(permission, str):
        from apps.accounts.permissions import catalog
        labels = {key: label for group in catalog().values() for key, label in group.items()}
        if permission in labels:
            visible.append(('Permiso', labels[permission]))
    changes = data.get('changes', {})
    if isinstance(changes, dict):
        from apps.core.models import BusinessOpeningHours
        for _, day in BusinessOpeningHours.Weekday.choices:
            row = changes.get(day)
            if not isinstance(row, dict):
                continue
            for field, label in [('is_open', 'Abierto'), ('opens_at', 'Apertura'), ('closes_at', 'Cierre'), ('sort_order', 'Orden')]:
                change = row.get(field)
                if isinstance(change, dict):
                    before = text_value(change.get('before') if change.get('before') is not None else 'Sin horario')
                    after = text_value(change.get('after') if change.get('after') is not None else 'Sin horario')
                    if before is not None and after is not None:
                        visible.append((f'{day} · {label}', f'{before} → {after}'))
        for field, label in CONFIG_FIELDS.items():
            change = changes.get(field)
            if isinstance(change, dict):
                before, after = text_value(change.get('before')), text_value(change.get('after'))
                if before is not None and after is not None:
                    visible.append((label, f'{before} → {after}'))
        for method, label in [('CASH','Efectivo'), ('CARD','Tarjeta'), ('TRANSFER','Transferencia'), ('DEPOSIT','Depósito')]:
            change = changes.get(method)
            if not isinstance(change, dict): continue
            for key, name in [('enabled','Habilitado'), ('display_order','Orden')]:
                before, after = change.get('before'), change.get('after')
                if not isinstance(before, dict) or not isinstance(after, dict): continue
                b, a = before.get(key), after.get(key)
                if type(b) is type(a) and type(a) in (bool, int):
                    def val(v): return ('Sí' if v else 'No') if isinstance(v, bool) else str(v)
                    visible.append((label+' · '+name, val(b)+' → '+val(a)))
    return visible


def module_filter(module):
    q = Q(pk__in=[])
    for prefix in MODULES.get(module, ()):
        q |= Q(action__startswith=prefix)
    payment = Q(action__in=['orders.'+x for x in PAYMENT_ACTIONS])
    configuration = Q(action__in=['reservations.configured','events.settings'])
    if module == 'Operación': q &= ~Q(action__startswith='operations.cash_')
    if module == 'Pagos': q |= payment
    elif module == 'Operación': q &= ~payment
    if module == 'Configuración': q |= configuration
    elif module in ('Reservas','Eventos'): q &= ~configuration
    return q


def present(log):
    action = log.action.split('.')[-1]
    module = next((name for name, prefixes in MODULES.items() if log.action.startswith(prefixes)), 'Operación')
    if log.action in ['orders.'+x for x in PAYMENT_ACTIONS]: module = 'Pagos'
    if log.action in ('reservations.configured','events.settings'): module = 'Configuración'
    if log.action.startswith('operations.cash_'): module = 'Caja'
    label = LABELS.get(action, 'Registró una operación')
    context = visible_data(log.data)
    entity = ENTITIES.get(log.entity.lower().split('.')[-1], 'Registro')
    reference = '#'+log.entity_id if log.entity_id.isdecimal() and len(log.entity_id)<16 else '—'
    summary = ' · '.join(f'{key}: {value}' for key,value in context[:3]) or 'Operación registrada; sin contexto adicional publicable.'
    return dict(log=log, module=module, action=label, entity=entity, reference=reference, summary=summary, context=context)


def present_many(logs):
    from apps.orders.models import TableOrder, OrderLine
    from apps.catalog.models import Product
    logs = list(logs)
    def pk(value):
        value = str(value)
        return int(value) if value.isdecimal() and len(value) < 16 else None
    order_ids = {pk(log.entity_id) for log in logs if log.entity.lower() == 'orders.tableorder'}
    product_ids = {pk(log.entity_id) for log in logs if log.entity.lower() == 'catalog.product'}
    line_ids = {pk(log.data.get('line_id')) for log in logs if isinstance(log.data, dict)}
    orders = {obj.pk: obj for obj in TableOrder.objects.filter(pk__in=order_ids-{None}).select_related('primary_table')}
    products = dict(Product.objects.filter(pk__in=product_ids-{None}).values_list('pk', 'name'))
    lines = {obj.pk: obj for obj in OrderLine.objects.filter(pk__in=line_ids-{None})}
    result = []
    for log in logs:
        item = present(log)
        context = []
        order = orders.get(pk(log.entity_id)) if log.entity.lower() == 'orders.tableorder' else None
        product = products.get(pk(log.entity_id)) if log.entity.lower() == 'catalog.product' else None
        line = lines.get(pk(log.data.get('line_id'))) if isinstance(log.data, dict) else None
        if order: context.append(('Cuenta', text_value(order.display_name)))
        if product: context.append(('Producto', text_value(product)))
        if line: context.append(('Producto', f'{line.quantity} × {text_value(line.product_name_snapshot)}'))
        item['human_reference'] = text_value(product) if product else (text_value(order.display_name) if order else item['entity'])
        item['context'] = context + item['context']
        item['summary'] = ' · '.join(f'{key}: {value}' for key,value in item['context'][:4]) or item['summary']
        result.append(item)
    return result


class AuditFilter(forms.Form):
    start = forms.DateField(label='Desde', required=False, widget=forms.DateInput(attrs={'type':'date'}))
    end = forms.DateField(label='Hasta', required=False, widget=forms.DateInput(attrs={'type':'date'}))
    user = forms.CharField(label='Usuario o nombre', max_length=100, required=False)
    module = forms.ChoiceField(label='Módulo', required=False, choices=[('', 'Todos los módulos')]+[(x,x) for x in MODULES])
    action = forms.ChoiceField(label='Acción', required=False, choices=[('', 'Todas las acciones')]+sorted(LABELS.items(), key=lambda x:x[1]))
    q = forms.CharField(label='Buscar referencia', max_length=100, required=False)

    def clean(self):
        data = super().clean()
        if data.get('start') and data.get('end') and data['end'] < data['start']:
            raise forms.ValidationError('La fecha final debe ser posterior a la inicial.')
        return data


@require_GET
@security.required
def listing(request):
    security.require(request.user, 'audit.view_audit_log')
    form = AuditFilter(request.GET)
    logs = AuditLog.objects.select_related('user').all()
    if form.is_valid():
        data = form.cleaned_data
        if data['start']: logs = logs.filter(created_at__date__gte=data['start'])
        if data['end']: logs = logs.filter(created_at__date__lte=data['end'])
        if data['user']: logs = logs.filter(Q(user__username__icontains=data['user']) | Q(user__first_name__icontains=data['user']) | Q(user__last_name__icontains=data['user']))
        if data['module']: logs = logs.filter(module_filter(data['module']))
        if data['action']: logs = logs.filter(Q(action=data['action']) | Q(action__endswith='.'+data['action']))
        if data['q']: logs = logs.filter(entity_id=data['q'].lstrip('#'))
    else:
        logs = logs.none()
    rows = Paginator(logs, 25).get_page(request.GET.get('page'))
    params = request.GET.copy(); params.pop('page', None)
    return page(request, 'audit', dict(form=form, rows=rows, entries=present_many(rows), filter_query=params.urlencode()), section='auditoria')


@require_GET
@security.required
def detail(request, pk):
    security.require(request.user, 'audit.view_audit_log')
    return page(request, 'audit_detail', present_many([get_object_or_404(AuditLog.objects.select_related('user'), pk=pk)])[0], section='auditoria')

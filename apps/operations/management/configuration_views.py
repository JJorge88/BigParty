from datetime import timedelta
from django import forms
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods
from apps.core import configuration as config
from apps.core.models import BusinessSettings, BankTransferSettings
from apps.cash.models import CashRegister
from apps.operations.models import OperationalDevice
from apps.printing.models import Printer, PrintJob
from apps.reservations.queries import get_settings as reservation_settings
from apps.events.queries import get_settings as event_settings
from . import security
from .views import page


class BusinessForm(forms.ModelForm):
    class Meta:
        model = BusinessSettings
        fields = ('business_name',)


class BankForm(forms.ModelForm):
    class Meta:
        model = BankTransferSettings
        fields = ('enabled', 'bank_name', 'account_name', 'account_number', 'instructions')
        widgets = {'instructions': forms.Textarea(attrs={'rows': 3})}


class MethodsForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for row in config.payment_methods():
            self.fields[row['code'] + '_enabled'] = forms.BooleanField(label=row['name'] + ' · habilitado', required=False, initial=row['enabled'])
            self.fields[row['code'] + '_order'] = forms.IntegerField(label=row['name'] + ' · orden', min_value=0, max_value=999, initial=row['display_order'])


@require_GET
@security.required
def hub(request):
    security.require(request.user, 'core.view_configuration')
    reserve, event = reservation_settings(), event_settings()
    cards = []
    def card(title, description, permission=None, route=None, args=None):
        cards.append(dict(title=title, description=description,
                          url=reverse(route, args=args) if route and request.user.has_perm(permission) else ''))
    card('Negocio', f'{config.business().business_name} · GTQ · America/Guatemala', 'core.change_business_configuration', 'management:configuration-edit', ['business'])
    card('Operación', 'La jornada se abre y cierra manualmente. Las ventas conservan su jornada después de medianoche.', 'cash.view_cash_session_financials', 'management:closures')
    card('Métodos de pago', 'Efectivo, tarjeta, transferencia y depósito. Los cambios afectan únicamente nuevos cobros.', 'core.change_payment_method_configuration', 'management:configuration-edit', ['methods'])
    card('Datos de transferencia', 'Datos públicos para recibir pagos en reservas y eventos. ' + ('Configurados.' if config.bank() else 'Pendiente de configuración.'), 'core.change_bank_transfer_configuration', 'management:configuration-edit', ['bank'])
    card('Reservas', f'{"Habilitadas" if reserve.reservations_enabled else "Deshabilitadas"} · duración {reserve.default_duration_minutes} min · retención {reserve.public_hold_minutes} min · anticipo {"activo" if reserve.advance_payment_enabled else "inactivo"}', 'reservations.configure_reservations', 'reservations:configure')
    card('Eventos', f'Retención {event.purchase_hold_minutes} min · ventana de pago {event.payment_window_minutes} min', 'events.change_event', 'events:settings')
    card('Mesas', 'La distribución se administra en la configuración técnica existente.')
    card('Impresoras', f'{Printer.objects.count()} configuradas · {Printer.objects.filter(is_active=True).count()} activas · {PrintJob.objects.filter(status="FAILED", printer__isnull=False, created_at__gte=timezone.now()-timedelta(days=7)).values("printer_id").distinct().count()} con fallos en 7 días', 'printing.manage_printers', 'printing:printers')
    card('Dispositivos', f'{OperationalDevice.objects.count()} dispositivos operativos · {CashRegister.objects.count()} cajas registradas. La vinculación de navegadores conserva sus controles actuales.')
    card('Seguridad y accesos', 'Usuarios, credenciales y permisos individuales.', 'accounts.view_user', 'management:users')
    if request.user.is_staff:
        if request.user.has_perm('tables.view_venuetable'):
            cards[6]['url'] = reverse('admin:tables_venuetable_changelist')
        if request.user.has_perm('operations.view_operationaldevice'):
            cards[8]['url'] = reverse('admin:operations_operationaldevice_changelist')
    system = [('URL pública', settings.PUBLIC_BASE_URL), ('Zona horaria', settings.TIME_ZONE),
              ('Modo de desarrollo', 'Activo' if settings.DEBUG else 'Inactivo'), ('Impresión', settings.PRINTER_BACKEND),
              ('Sesión operativa', f'{settings.OPERATIONAL_IDLE_TIMEOUT_SECONDS // 60} min'),
              ('Sesión de caja', f'{settings.CASH_IDLE_TIMEOUT_SECONDS // 60} min'),
              ('Sesión de Gerencia', f'{settings.MANAGEMENT_IDLE_TIMEOUT_SECONDS // 60} min'),
              ('Intentos de PIN operativo / caja', f'{settings.OPERATIONAL_PIN_MAX_ATTEMPTS} / {settings.CASH_PIN_MAX_ATTEMPTS}'),
              ('Bloqueo de PIN operativo / caja', f'{settings.OPERATIONAL_PIN_LOCK_SECONDS // 60} / {settings.CASH_PIN_LOCK_SECONDS // 60} min')]
    return page(request, 'configuration', dict(cards=cards, system=system), section='configuracion')


@require_http_methods(['GET', 'POST'])
@security.required
def edit(request, kind):
    specs = {'business': (BusinessForm, 'Negocio', 'change_business_configuration'),
             'methods': (MethodsForm, 'Métodos de pago', 'change_payment_method_configuration'),
             'bank': (BankForm, 'Datos de transferencia', 'change_bank_transfer_configuration')}
    if kind not in specs:
        raise Http404
    security.require(request.user, 'core.view_configuration')
    cls, title, permission = specs[kind]
    security.require(request.user, 'core.' + permission)
    kwargs = {}
    if kind == 'business':
        kwargs['instance'] = config.business()
    elif kind == 'bank':
        kwargs['instance'] = BankTransferSettings.objects.first() or BankTransferSettings()
    form = cls(request.POST if request.method == 'POST' else None, **kwargs)
    if request.method == 'POST' and form.is_valid():
        try:
            config.save_configuration(request.user, kind, form.cleaned_data)
            messages.success(request, 'Configuración guardada. El cambio quedó registrado en auditoría.')
            return redirect('management:configuration-edit', kind=kind)
        except ValidationError as exc:
            form.add_error(None, ' '.join(exc.messages))
    return page(request, 'configuration_form', dict(form=form, title=title, kind=kind), section='configuracion')

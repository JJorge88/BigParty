from datetime import timedelta
from django import forms
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.db.models import Q
from django.views.decorators.http import require_GET, require_http_methods
from apps.core import configuration as config
from apps.core.models import BusinessSettings, BusinessOpeningHours, BankTransferSettings
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


class LocationForm(forms.ModelForm):
    class Meta:
        model = BusinessSettings
        fields = config.BUSINESS_FIELDS['location']


class EntryForm(forms.ModelForm):
    class Meta:
        model = BusinessSettings
        fields = config.BUSINESS_FIELDS['entry']
        widgets = {field: forms.Textarea(attrs={'rows': 3}) for field in fields if field != 'minimum_entry_age'}


class OpeningHoursForm(forms.Form):
    weekday = forms.TypedChoiceField(label='Día', choices=BusinessOpeningHours.Weekday.choices, coerce=int, disabled=True)
    is_open = forms.TypedChoiceField(label='Estado', choices=((False, 'Cerrado'), (True, 'Abierto')), coerce=lambda v: v == 'True')
    opens_at = forms.TimeField(label='Hora de apertura', required=False, widget=forms.TimeInput(format='%H:%M', attrs={'type': 'time'}))
    closes_at = forms.TimeField(label='Hora de cierre', required=False, widget=forms.TimeInput(format='%H:%M', attrs={'type': 'time'}))
    sort_order = forms.IntegerField(label='Orden', min_value=0, max_value=32767)

    @property
    def day_label(self):
        return dict(BusinessOpeningHours.Weekday.choices)[self.initial['weekday']]

    def clean(self):
        data = super().clean()
        if data.get('is_open'):
            if not data.get('opens_at') or not data.get('closes_at') or data['opens_at'] == data['closes_at']:
                raise ValidationError('Para un día abierto, indica una apertura y un cierre diferentes.')
        else:
            data['opens_at'] = data['closes_at'] = None
        return data


HoursFormSet = forms.formset_factory(OpeningHoursForm, extra=0, min_num=7, max_num=7, absolute_max=7, validate_min=True, validate_max=True)


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
    card('Negocio', f'{config.business().business_name} · Información, ubicación, horarios e ingreso.', 'core.change_business_configuration', 'management:configuration-business')
    card('Operación diaria', 'Cada cajero abre su caja con el fondo inicial. La jornada interna se administra automáticamente.', 'cash.view_cash_session_financials', 'management:closures')
    card('Métodos de pago', 'Efectivo, tarjeta, transferencia y depósito. Los cambios afectan únicamente nuevos cobros.', 'core.change_payment_method_configuration', 'management:configuration-edit', ['methods'])
    card('Datos de transferencia', 'Datos públicos para recibir pagos en reservas y eventos. ' + ('Configurados.' if config.bank() else 'Pendiente de configuración.'), 'core.change_bank_transfer_configuration', 'management:configuration-edit', ['bank'])
    card('Reservas', f'{"Habilitadas" if reserve.reservations_enabled else "Deshabilitadas"} · duración {reserve.default_duration_minutes} min · retención {reserve.public_hold_minutes} min · anticipo {"activo" if reserve.advance_payment_enabled else "inactivo"}', 'reservations.configure_reservations', 'reservations:configure')
    card('Eventos', f'Retención {event.purchase_hold_minutes} min · ventana de pago {event.payment_window_minutes} min', 'events.change_event', 'events:settings')
    card('Mesas', 'Crea mesas y organiza su ubicación, forma y capacidad por área.', 'tables.view_venuetable', 'management:tables')
    configured_printers = Printer.objects.filter(Q(host__gt='') | (Q(bridge__isnull=False) & Q(queue_name__gt=''))).count()
    card('Impresoras', f'{Printer.objects.count()} registradas · {configured_printers} conectadas · {PrintJob.objects.filter(status="FAILED", printer__isnull=False, created_at__gte=timezone.now()-timedelta(days=7)).values("printer_id").distinct().count()} con fallos recientes (7 días)', 'printing.manage_printers', 'printing:printers')
    card('Cajas y cajeros', f'{CashRegister.objects.count()} cajas registradas. El cajero entra con su usuario y PIN; no se configura el navegador.', 'cash.view_cashregister', 'management:registers')
    card('Seguridad y accesos', 'Usuarios, credenciales y permisos individuales.', 'accounts.view_user', 'management:users')
    if request.user.is_staff:
        if request.user.has_perm('operations.view_operationaldevice'):
            cards[8]['url'] = reverse('admin:operations_operationaldevice_changelist')
    if settings.DEPLOYMENT_MODE == 'local_node':
        card('Nodo local', 'Identidad, diagnóstico y snapshots de acceso.', 'core.view_configuration', 'localnode:status')
    if settings.DEPLOYMENT_MODE in ('local_node','cloud'):
        card('Sincronización', 'Último contacto, pendientes y conflictos.', 'core.view_configuration', 'sync-status')
    card('Backups y recuperación', 'Últimas copias, verificaciones y estado de recuperación.', 'core.view_configuration', 'backup-status')
    system = [('URL pública', settings.PUBLIC_BASE_URL), ('Zona horaria', settings.TIME_ZONE),
              ('Modo de desarrollo', 'Activo' if settings.DEBUG else 'Inactivo'), ('Impresión', settings.PRINTER_BACKEND),
              ('Sesión operativa', f'{settings.OPERATIONAL_IDLE_TIMEOUT_SECONDS // 60} min'),
              ('Sesión de caja', f'{settings.CASH_IDLE_TIMEOUT_SECONDS // 60} min'),
              ('Sesión de Gerencia', f'{settings.MANAGEMENT_IDLE_TIMEOUT_SECONDS // 60} min'),
              ('Intentos de PIN operativo / caja', f'{settings.OPERATIONAL_PIN_MAX_ATTEMPTS} / {settings.CASH_PIN_MAX_ATTEMPTS}'),
              ('Bloqueo de PIN operativo / caja', f'{settings.OPERATIONAL_PIN_LOCK_SECONDS // 60} / {settings.CASH_PIN_LOCK_SECONDS // 60} min')]
    return page(request, 'configuration', dict(cards=cards, system=system), section='configuracion')


@require_GET
@security.required
def business_hub(request):
    security.require(request.user, 'core.view_configuration')
    security.require(request.user, 'core.change_business_configuration')
    sections = [('business', 'Información', 'Nombre del negocio.'),
                ('location', 'Ubicación', 'Mapa, dirección pública y contacto opcional.'),
                ('hours', 'Horarios', 'Días abiertos y horarios publicados. El cierre puede ser al día siguiente.'),
                ('entry', 'Ingreso', 'Edad mínima, identificación, vestimenta y reglas públicas.')]
    return page(request, 'business_configuration', {'sections': sections}, section='configuracion')


@require_http_methods(['GET', 'POST'])
@security.required
def edit(request, kind):
    specs = {'business': (BusinessForm, 'Negocio', 'change_business_configuration'),
             'location': (LocationForm, 'Ubicación', 'change_business_configuration'),
             'entry': (EntryForm, 'Ingreso', 'change_business_configuration'),
             'hours': (HoursFormSet, 'Horarios', 'change_business_configuration'),
             'methods': (MethodsForm, 'Métodos de pago', 'change_payment_method_configuration'),
             'bank': (BankForm, 'Datos de transferencia', 'change_bank_transfer_configuration')}
    if kind not in specs:
        raise Http404
    security.require(request.user, 'core.view_configuration')
    cls, title, permission = specs[kind]
    security.require(request.user, 'core.' + permission)
    kwargs = {}
    if kind in config.BUSINESS_FIELDS:
        kwargs['instance'] = config.business()
    elif kind == 'hours':
        saved = {row.weekday: row for row in BusinessOpeningHours.objects.all()}
        kwargs['initial'] = [dict(weekday=day, is_open=saved[day].is_open if day in saved else False,
            opens_at=saved[day].opens_at if day in saved else None, closes_at=saved[day].closes_at if day in saved else None,
            sort_order=saved[day].sort_order if day in saved else day) for day in range(7)]
    elif kind == 'bank':
        kwargs['instance'] = BankTransferSettings.objects.first() or BankTransferSettings()
    form = cls(request.POST if request.method == 'POST' else None, **kwargs)
    if request.method == 'POST' and form.is_valid():
        try:
            config.save_configuration(request.user, kind, form.cleaned_data)
            messages.success(request, 'Configuración guardada. El cambio quedó registrado en auditoría.')
            return redirect('management:configuration-edit', kind=kind)
        except ValidationError as exc:
            if kind == 'hours':
                form._non_form_errors = form.error_class(exc.messages)
            else:
                form.add_error(None, ' '.join(exc.messages))
    return page(request, 'configuration_form', dict(form=form, title=title, kind=kind), section='configuracion')

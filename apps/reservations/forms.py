from django import forms
from apps.tables.models import VenueTable
from .models import AdvanceType, AdvanceApplication, ReservationSettings
from .services import validate_proof


class PaymentTermsForm(forms.Form):
    def __init__(self, *args, **kwargs):
        if args and args[0] is not None:
            data = args[0].copy()
            if not forms.BooleanField(required=False).clean(data.get('payment_required')):
                for key, value in [('payment_type', 'FIXED'), ('payment_value', '0'), ('payment_application', 'CREDIT'), ('payment_base_amount', '0')]:
                    data.setdefault(key, value)
            args = (data, *args[1:])
        super().__init__(*args, **kwargs)

    payment_required = forms.BooleanField(label='Requerir anticipo', required=False)
    payment_type = forms.ChoiceField(label='Tipo de anticipo', choices=AdvanceType.choices)
    payment_value = forms.DecimalField(label='Monto fijo (Q) o porcentaje (%)', min_value=0, max_digits=12, decimal_places=2)
    payment_application = forms.ChoiceField(label='Aplicación del anticipo', choices=AdvanceApplication.choices)
    payment_base_amount = forms.DecimalField(label='Consumo estimado (Q), base para porcentaje', required=False, min_value=0, max_digits=12, decimal_places=2)

    def clean_payment_base_amount(self):
        return self.cleaned_data.get('payment_base_amount') or 0


class ReservationTableChoice(forms.ModelChoiceField):
    def label_from_instance(self, table):
        return f'{table.area.name} · {table.name} — {table.capacity} personas'


class ManualReservationForm(PaymentTermsForm):
    table = ReservationTableChoice(label='Mesa', queryset=VenueTable.objects.filter(is_active=True, operational_status='ACTIVE', area__is_active=True).select_related('area').order_by('area__sort_order', 'area__name', 'sort_order', 'name'))
    customer_name = forms.CharField(label='Nombre del cliente', max_length=120)
    customer_phone = forms.CharField(label='Teléfono internacional', max_length=20, widget=forms.TextInput(attrs={'placeholder': '+502 5555 5555'}))
    date = forms.DateField(label='Fecha', widget=forms.DateInput(attrs={'type': 'date'}))
    time = forms.TimeField(label='Hora', widget=forms.TimeInput(attrs={'type': 'time'}))
    duration = forms.IntegerField(label='Duración', min_value=1, max_value=1440, widget=forms.Select)
    party_size = forms.IntegerField(label='Personas', min_value=1)
    field_order = ['customer_name', 'customer_phone', 'table', 'date', 'time', 'duration', 'party_size',
                   'payment_required', 'payment_type', 'payment_value', 'payment_application', 'payment_base_amount']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['table'].help_text = 'Primero elige fecha, hora y personas para consultar mesas disponibles. Volvemos a comprobar al guardar.'
        durations = [(60, '1 hora'), (90, '1 hora y media'), (120, '2 horas'), (180, '3 horas'), (240, '4 horas'), (360, '6 horas'), (480, '8 horas')]
        selected = self['duration'].value()
        if selected and str(selected).isdigit() and int(selected) not in dict(durations):
            durations.append((int(selected), f'{selected} minutos'))
        self.fields['duration'].widget.choices = durations
        self.fields['duration'].help_text = 'Tiempo durante el que se reservará la mesa.'
        self.fields['payment_required'].help_text = 'Revisa esta opción con el cliente antes de confirmar.'
        self.fields['party_size'].help_text = 'Debe caber en la mesa seleccionada.'


class SettingsForm(forms.ModelForm):
    class Meta:
        model = ReservationSettings
        exclude = ['id']


class SubmitPaymentForm(forms.Form):
    amount = forms.DecimalField(label='Monto transferido (Q)', min_value=0.01, max_digits=12, decimal_places=2)
    reference = forms.CharField(label='Referencia de transferencia', max_length=160)
    proof_image = forms.FileField(label='Comprobante · JPEG, PNG o WebP · máximo 5 MB', required=False,
                                 widget=forms.ClearableFileInput(attrs={'accept': 'image/jpeg,image/png,image/webp'}))

    def clean_proof_image(self):
        file = self.cleaned_data.get('proof_image')
        validate_proof(file)
        return file

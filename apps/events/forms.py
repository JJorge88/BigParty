from django import forms
from .models import Event, EventTicketType, EventPurchasePayment, EventSettings
from .services import validate_image

DATETIME = forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M')

class EventForm(forms.ModelForm):
    class Meta:
        model = Event
        fields = ['name', 'artist_name', 'starts_at', 'ends_at', 'image', 'description', 'ticket_sales_enabled']
        widgets = {'image': forms.FileInput(), 'starts_at': DATETIME, 'ends_at': DATETIME, 'description': forms.Textarea(attrs={'rows': 3})}

    def clean_image(self):
        upload = self.cleaned_data.get('image')
        if upload and hasattr(upload, 'content_type'):
            validate_image(upload)
        return upload

class TicketTypeForm(forms.ModelForm):
    class Meta:
        model = EventTicketType
        fields = ['name', 'price', 'capacity', 'sale_starts_at', 'sale_ends_at', 'max_per_purchase', 'sort_order', 'is_active', 'is_courtesy_type']
        widgets = {'sale_starts_at': DATETIME, 'sale_ends_at': DATETIME}

class PaymentForm(forms.ModelForm):
    class Meta:
        model = EventPurchasePayment
        fields = ['amount', 'reference', 'proof_image']
        widgets = {'proof_image': forms.ClearableFileInput(attrs={'accept':'image/jpeg,image/png,image/webp'})}

class SettingsForm(forms.ModelForm):
    class Meta:
        model = EventSettings
        fields = ['purchase_hold_minutes', 'payment_window_minutes', 'transfer_instructions']
        labels = {'purchase_hold_minutes': 'Retención de cupo (minutos)', 'payment_window_minutes': 'Ventana de pago (minutos)', 'transfer_instructions': 'Instrucciones de transferencia'}

class RescheduleForm(forms.Form):
    starts_at = forms.DateTimeField(label='Nuevo inicio', widget=DATETIME)
    ends_at = forms.DateTimeField(label='Nuevo fin', widget=DATETIME)
    reason = forms.CharField(label='Motivo', max_length=2000)

class TableForm(forms.Form):
    table = forms.ModelChoiceField(label='Mesa', queryset=None)
    ticket_type = forms.ModelChoiceField(label='Tipo de acceso', queryset=None)
    cover_per_person = forms.DecimalField(label='Cover por persona (Q)', min_value=0, max_digits=12, decimal_places=2)
    enabled = forms.BooleanField(label='Habilitada', required=False, initial=True)

    def __init__(self, *args, event, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.tables.models import VenueTable
        self.fields['table'].queryset = VenueTable.objects.filter(is_active=True, area__is_active=True, operational_status='ACTIVE').order_by('area__name', 'name')
        self.fields['ticket_type'].queryset = event.ticket_types.filter(is_active=True)

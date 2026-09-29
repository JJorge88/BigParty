from django import forms
from django.utils import timezone
from apps.reservations.queries import interval


class ReservationSearchForm(forms.Form):
    date = forms.DateField(label='Fecha', widget=forms.DateInput(attrs={'type':'date'}))
    time = forms.TimeField(label='Hora', widget=forms.TimeInput(attrs={'type':'time'}))
    party_size = forms.IntegerField(label='Personas', min_value=1, max_value=100, initial=4)

    def clean(self):
        data = super().clean()
        if data.get('date') and data.get('time'):
            start, _ = interval(data['date'],data['time'],1)
            if start <= timezone.now():
                raise forms.ValidationError('Elige una fecha y hora futuras para tu noche.')
        return data


class GuestForm(forms.Form):
    customer_name = forms.CharField(label='Tu nombre', max_length=120, widget=forms.TextInput(attrs={'autocomplete':'name'}))
    customer_phone = forms.RegexField(label='Teléfono', regex=r'^\+?[\d ()-]{8,20}$', max_length=20,
        error_messages={'invalid':'Escribe un teléfono válido, por ejemplo +502 5555 5555.'},
        widget=forms.TextInput(attrs={'type':'tel','autocomplete':'tel','placeholder':'+502 5555 5555'}))

    def clean_customer_phone(self):
        value = self.cleaned_data['customer_phone']
        digits = ''.join(c for c in value if c.isdigit())
        if not 8 <= len(digits) <= 15:
            raise forms.ValidationError('Escribe un teléfono válido.')
        return value


class ReservationGuestForm(GuestForm):
    def clean_customer_phone(self):
        value = super().clean_customer_phone()
        if not value.startswith('+'):
            raise forms.ValidationError('Incluye el código de país, por ejemplo +502 5555 5555.')
        return value

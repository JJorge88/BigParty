from django import forms
from .models import OperationalDevice


class DeviceConfigurationForm(forms.Form):
    device = forms.ModelChoiceField(label="Dispositivo asignado a este navegador", queryset=OperationalDevice.objects.filter(is_active=True, area__is_active=True).select_related("area"), empty_label="Selecciona un dispositivo")

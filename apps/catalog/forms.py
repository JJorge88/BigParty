from django import forms

from apps.venues.models import Area


class AreaSelectionForm(forms.Form):
    area = forms.ModelChoiceField(label="Área", queryset=Area.objects.all(), required=False, empty_label="Precio general")

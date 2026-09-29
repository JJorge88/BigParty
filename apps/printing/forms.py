from django import forms
from .models import Printer


class PrinterForm(forms.ModelForm):
    class Meta:
        model = Printer
        fields = ['name','host','port','paper_width','encoding','codepage','transliterate','supports_cut','is_active']
        labels = {'name':'Nombre','host':'IP / host','port':'Puerto TCP','paper_width':'Ancho de papel', 'encoding':'Codificación',
                  'codepage':'Tabla ESC t (opcional)','transliterate':'Normalizar acentos al imprimir','supports_cut':'Tiene cortador compatible','is_active':'Activa'}

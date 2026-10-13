from django import forms
from .models import Printer


class PrinterForm(forms.ModelForm):
    class Meta:
        model = Printer
        fields = ['name','printer_type','area','host','paper_width','port','encoding','transliterate','supports_cut','is_active']
        labels = {'name':'Nombre fácil','printer_type':'¿Dónde imprimirá?','area':'Área de la barra','host':'Dirección IP','port':'Puerto de red','paper_width':'Ancho del papel', 'encoding':'Codificación',
                  'codepage':'Tabla ESC t (opcional)','transliterate':'Normalizar acentos al imprimir','supports_cut':'Tiene cortador compatible','is_active':'Activa'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['host'].required = True
        self.fields['host'].help_text = 'Ejemplo: 192.168.1.80. La impresora debe conservar siempre esta dirección.'
        self.fields['printer_type'].help_text = 'Barra imprime bebidas del área. Cocina imprime toda la comida.'
        self.fields['area'].help_text = 'Solo se usa cuando el destino es Barra.'
        self.fields['port'].help_text = 'Normalmente 9100. Cámbialo únicamente si el manual indica otro.'

    def clean(self):
        data = super().clean()
        if data.get('printer_type') == 'BAR' and not data.get('area'):
            self.add_error('area', 'Selecciona el área donde está esta barra.')
        if data.get('printer_type') == 'KITCHEN':
            data['area'] = None
        return data

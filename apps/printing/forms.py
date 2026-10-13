from django import forms
from .models import Printer, PrintBridge


class PrinterForm(forms.ModelForm):
    connection = forms.ChoiceField(choices=[('bridge','Mini app de Windows (recomendado)'),('network','Red directa desde el servidor')], label='¿Cómo está conectada?')
    class Meta:
        model = Printer
        fields = ['name','printer_type','area','bridge','queue_name','host','paper_width','port','encoding','transliterate','supports_cut','is_active']
        labels = {'name':'Nombre fácil','printer_type':'¿Dónde imprimirá?','area':'Área de la barra','host':'Dirección IP','port':'Puerto de red','paper_width':'Ancho del papel', 'encoding':'Codificación',
                  'bridge':'Computadora que imprimirá','queue_name':'Nombre de la impresora en Windows','codepage':'Tabla ESC t (opcional)','transliterate':'Normalizar acentos al imprimir','supports_cut':'Tiene cortador compatible','is_active':'Activa'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['connection'].initial = 'bridge' if self.instance and self.instance.bridge_id else 'network'
        self.fields['connection'].required = False
        self.fields['bridge'].queryset = PrintBridge.objects.filter(is_active=True)
        self.fields['host'].required = False
        self.fields['host'].help_text = 'Ejemplo: 192.168.1.80. La impresora debe conservar siempre esta dirección.'
        self.fields['printer_type'].help_text = 'Barra imprime bebidas del área. Cocina imprime toda la comida.'
        self.fields['area'].help_text = 'Solo se usa cuando el destino es Barra.'
        self.fields['port'].help_text = 'Normalmente 9100. Cámbialo únicamente si el manual indica otro.'

    def clean(self):
        data = super().clean()
        connection = data.get('connection') or ('bridge' if data.get('bridge') else 'network')
        if connection == 'bridge':
            if not data.get('bridge'):
                self.add_error('bridge', 'Selecciona la computadora donde está instalada la mini app.')
            if not (data.get('queue_name') or '').strip():
                self.add_error('queue_name', 'Escribe exactamente el nombre que tiene la impresora en Windows.')
            data['host'] = ''
        else:
            data['bridge'] = None
            data['queue_name'] = ''
            if not data.get('host'):
                self.add_error('host', 'Escribe la dirección IP de la impresora.')
        if data.get('printer_type') == 'BAR' and not data.get('area'):
            self.add_error('area', 'Selecciona el área donde está esta barra.')
        if data.get('printer_type') == 'KITCHEN':
            data['area'] = None
        return data

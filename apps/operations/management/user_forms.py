from django import forms
from django.db.models import Q
from apps.accounts.models import User


class UserForm(forms.ModelForm):
    pin = forms.RegexField(label='PIN inicial', regex=r'^[0-9]{4,6}$', required=False,
        widget=forms.PasswordInput(attrs={'inputmode': 'numeric', 'autocomplete': 'new-password'}),
        error_messages={'invalid': 'Usa entre 4 y 6 dígitos.'})
    password = forms.CharField(label='Contraseña inicial para Gerencia', required=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))
    confirm = forms.CharField(label='Confirmar PIN o contraseña', required=False,
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))

    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'username', 'role', 'work_area', 'is_active')

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            for key in ('pin', 'password', 'confirm', 'is_active'):
                del self.fields[key]
            self.fields['role'].disabled = not actor.has_perm('accounts.change_user_role')
        if not self.instance.pk:
            self.fields['role'].choices = [choice for choice in User.Role.choices
                                           if choice[0] in ('MESERO', 'GERENTE', 'CAJERO', 'PROPIETARIO')]
            role = self.data.get('role', self.initial.get('role', self.instance.role))
            key = 'password' if role in ('GERENTE', 'PROPIETARIO') else 'pin'
            self.fields[key].required = True
            self.fields['confirm'].required = True
        self.fields['username'].help_text = 'El nombre que usará para entrar. Ejemplo: maria.barra'
        self.fields['role'].help_text = 'Mesero atiende mesas; Gerente administra; Cajero cobra; Propietario consulta sus gráficas.'
        current_area = self.instance.work_area_id if self.instance.pk else None
        self.fields['work_area'].queryset = self.fields['work_area'].queryset.filter(
            Q(is_active=True) | Q(pk=current_area)).order_by('sort_order', 'name')
        self.fields['work_area'].label = 'Área de trabajo'
        self.fields['work_area'].help_text = 'Por ejemplo: Discoteca, Barra o Segundo nivel. Se usa para meseros y cajeros.'
        self.fields['work_area'].required = False
        if 'is_active' in self.fields:
            self.fields['is_active'].help_text = ''

    def clean(self):
        data = super().clean()
        if data.get('role') not in (User.Role.MESERO, User.Role.CAJERO):
            data['work_area'] = None
        if not self.instance.pk:
            key = 'password' if data.get('role') in ('GERENTE', 'PROPIETARIO') else 'pin'
            if not data.get(key):
                self.add_error(key, 'Esta credencial es obligatoria para el rol seleccionado.')
            elif data.get(key) != data.get('confirm'):
                self.add_error('confirm', 'La confirmación no coincide.')
        return data


class CredentialForm(forms.Form):
    value = forms.CharField(label='Nuevo PIN', widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))
    confirm = forms.CharField(label='Confirmar PIN', widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))

    def __init__(self, *args, kind='pin', **kwargs):
        kwargs.setdefault('auto_id', kind + '_id_%s')
        super().__init__(*args, **kwargs)
        if kind == 'password':
            self.fields['value'].label = 'Nueva contraseña'
            self.fields['confirm'].label = 'Confirmar contraseña'
        else:
            for field in self.fields.values():
                field.widget.attrs.update(inputmode='numeric', minlength=4, maxlength=6)

    def clean(self):
        data = super().clean()
        if data.get('value') != data.get('confirm'):
            self.add_error('confirm', 'La confirmación no coincide.')
        return data

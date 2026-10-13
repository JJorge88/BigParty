from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_http_methods

from apps.audit.models import AuditLog
from apps.accounts.models import User
from apps.cash.guards import lock_operation_gate
from apps.cash.models import CashRegister
from apps.venues.models import Area
from . import security
from .views import page


def unique_slug(model, value, *, field='slug', limit=100):
    base = slugify(value)[:limit] or 'nuevo'
    candidate, number = base, 2
    while model.objects.filter(**{field: candidate}).exists():
        suffix = f'-{number}'
        candidate, number = base[:limit-len(suffix)] + suffix, number + 1
    return candidate


class RegisterForm(forms.ModelForm):
    area_name = forms.CharField(label='Nombre de la primera área', required=False, max_length=100,
        help_text='Un espacio del negocio, por ejemplo “Discoteca” o “Bar”.')

    class Meta:
        model = CashRegister
        fields = ('name', 'area', 'is_active')
        labels = {'name': 'Nombre de la caja', 'area': 'Área', 'is_active': 'Caja activa'}
        help_texts = {'name': 'Por ejemplo: Caja 1.', 'area': 'El espacio donde trabaja, por ejemplo Discoteca o Bar.'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        areas = Area.objects.filter(is_active=True).order_by('sort_order', 'name')
        self.fields['area'].queryset = areas
        self.no_areas = not areas.exists()
        if self.no_areas:
            self.fields.pop('area')
            self.fields['area_name'].required = True
        elif areas.count() == 1 and not self.is_bound and not self.instance.pk:
            self.initial['area'] = areas.first()
        if self.instance.pk:
            self.fields.pop('area_name')

    def clean_name(self):
        value = self.cleaned_data['name'].strip()
        if CashRegister.objects.filter(name__iexact=value).exclude(pk=self.instance.pk).exists():
            raise ValidationError('Ya existe una caja con este nombre.')
        return value

    def clean_area_name(self):
        value = self.cleaned_data.get('area_name', '').strip()
        if value and Area.objects.filter(name__iexact=value).exists():
            raise ValidationError('Esta área ya existe. Actualiza la página para seleccionarla.')
        return value


def can_view(user):
    return any(user.has_perm(code) for code in ('cash.view_cashregister', 'cash.add_cashregister',
                                                'cash.change_cashregister', 'cash.configure_cash_register_device'))


@require_GET
@security.required
def listing(request):
    if not can_view(request.user):
        security.require(request.user, 'cash.view_cashregister')
    rows = CashRegister.objects.select_related('area').order_by('area__sort_order', 'name')
    return page(request, 'registers', {'registers': rows,
        'cashiers_exist': User.objects.filter(role='CAJERO', is_active=True, pin_hash__gt='').exists()}, section='cajas')


@require_http_methods(['GET', 'POST'])
@security.required
@transaction.atomic
def edit(request, pk=None):
    security.require(request.user, 'cash.change_cashregister' if pk else 'cash.add_cashregister')
    lock_operation_gate()
    register = get_object_or_404(CashRegister.objects.select_for_update(), pk=pk) if pk else CashRegister()
    form = RegisterForm(request.POST or None, instance=register)
    if request.method == 'POST' and form.is_valid():
        try:
            if not pk and form.no_areas:
                area_name = form.cleaned_data['area_name']
                area = Area(name=area_name, slug=unique_slug(Area, area_name), sort_order=10)
                area.save()
                form.instance.area = area
            if not pk:
                form.instance.code = unique_slug(CashRegister, form.cleaned_data['name'], field='code', limit=30)
            form.instance.save()
            AuditLog.objects.create(user=request.user, action='cash.register_updated' if pk else 'cash.register_created',
                entity='cash.cashregister', entity_id=str(form.instance.pk),
                data={'name': form.instance.name, 'area_id': form.instance.area_id, 'active': form.instance.is_active})
            messages.success(request, ('Caja actualizada.' if pk else
                f'{form.instance.name} fue creada. Ahora configura el navegador de esa computadora.'))
            if not pk and request.POST.get('next') == reverse('cash_operations:configure'):
                return redirect('cash_operations:configure')
            return redirect('management:registers')
        except ValidationError as exc:
            form.add_error(None, ' '.join(exc.messages))
    return page(request, 'register_form', {'form': form, 'register': register if pk else None,
        'title': 'Editar caja' if pk else 'Crear una caja',
        'next_url': reverse('cash_operations:configure') if request.GET.get('next') == reverse('cash_operations:configure') else ''},
        section='cajas', status=400 if form.errors else 200)

"""Editor del plano físico de mesas para Gerencia."""
from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views.decorators.http import require_GET, require_http_methods
from apps.tables.models import VenueTable
from apps.tables.management_services import save_table
from apps.venues.models import Area, Zone
from . import security
from .views import page


class TableForm(forms.ModelForm):
    revision = forms.CharField(widget=forms.HiddenInput, required=False)

    class Meta:
        model = VenueTable
        fields = ('name', 'capacity', 'zone', 'level', 'layout_shape', 'layout_x', 'layout_y',
                  'layout_width', 'layout_height', 'is_active', 'operational_status')
        labels = {'is_active': 'Mostrar mesa en la operación', 'reservable_web': 'Permitir reservas en la web'}

    def __init__(self, *args, area, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.area = area
        self.fields['zone'].queryset = Zone.objects.filter(area=area)
        self.fields['revision'].initial = self.instance.updated_at.isoformat() if self.instance.pk else ''
        self.fields['level'].label = '¿En qué nivel está?'
        self.fields['level'].help_text = 'Usa Nivel 1 para la planta principal y Nivel 2 para el segundo piso.'
        if not self.instance.pk:
            self.fields['level'].initial = 'LEVEL_1'
        for key in ('layout_x', 'layout_y', 'layout_width', 'layout_height'):
            self.fields[key].localize = False
            self.fields[key].widget = forms.NumberInput(attrs={'step': '.01', 'min': '0.01' if key in ('layout_width', 'layout_height') else '0', 'max': '100'})


def map_data(area, selected=None, level=None):
    from apps.tables.layout import overlaps
    from django.core import signing
    levels = list(VenueTable._meta.get_field('level').choices)
    level = selected.level if selected else (level if level in dict(levels) else '')
    rows = list(area.tables.filter(level=level)) if area else []
    return {'overlaps': overlaps(rows), 'levels': levels, 'level': level,
            'layout_confirmation': signing.dumps({'area': area.pk, 'level': level,
                'revisions': {str(t.pk): t.updated_at.isoformat() for t in rows}}, salt='tables.arrange') if area else '',
            'areas': Area.objects.all(), 'area': area, 'tables': rows, 'selected_table': selected}


@require_GET
@security.required
def listing(request):
    security.require(request.user, 'tables.view_venuetable')
    area = get_object_or_404(Area, pk=request.GET['area']) if request.GET.get('area', '').isdecimal() else Area.objects.first()
    return page(request, 'tables', map_data(area, level=request.GET.get('level')), section='mesas')


@require_http_methods(['GET', 'POST'])
@security.required
def edit(request, pk=None, area_id=None):
    security.require(request.user, 'tables.view_venuetable')
    security.require(request.user, 'tables.change_venuetable' if pk else 'tables.add_venuetable')
    table = get_object_or_404(VenueTable, pk=pk) if pk else None
    area = table.area if table else get_object_or_404(Area, pk=area_id)
    form = TableForm(request.POST if request.method == 'POST' else None, instance=table, area=area)
    if request.method == 'POST' and form.is_valid():
        try:
            save_table(area, form.cleaned_data, actor=request.user, pk=pk)
            messages.success(request, 'Mesa guardada. El plano de la operación ya está actualizado.')
            if not pk and request.POST.get('after_save') == 'another':
                return redirect('management:table-create', area_id=area.pk)
            return redirect(reverse('management:tables') + f"?area={area.pk}&level={form.cleaned_data.get('level', '')}")
        except ValidationError as exc:
            form.add_error(None, ' '.join(exc.messages))
    return page(request, 'table_edit', {**map_data(area, table), 'form': form,
        'basic_fields': [form[key] for key in ('name', 'capacity', 'level')],
        'advanced_fields': [form[key] for key in ('zone', 'layout_shape', 'layout_x', 'layout_y',
                                                  'layout_width', 'layout_height', 'is_active', 'operational_status')],
        'title': 'Editar mesa' if pk else 'Crear mesa'}, section='mesas', status=400 if form.errors else 200)


@require_GET
@security.required
def start(request):
    security.require(request.user, 'tables.view_venuetable')
    security.require(request.user, 'tables.add_venuetable')
    return page(request, 'table_start', {'areas': Area.objects.filter(is_active=True).prefetch_related('tables')}, section='mesas')


@require_http_methods(['GET', 'POST'])
@security.required
def arrange(request, area_id):
    from django.core import signing
    from apps.tables.layout import suggestion
    from apps.tables.management_services import arrange_tables
    security.require(request.user, 'tables.change_venuetable')
    security.require(request.user, 'tables.view_venuetable')
    area = get_object_or_404(Area, pk=area_id)
    error = ''
    if request.method == 'POST':
        try:
            data = signing.loads(request.POST.get('confirmation', ''), salt='tables.arrange', max_age=600)
            if data['area'] != area.pk: raise signing.BadSignature()
            arrange_tables(area, actor=request.user, revisions=data['revisions'], level=data.get('level', ''))
            messages.success(request, 'Mesas distribuidas sin superposiciones. Puedes ajustar sus posiciones al plano real.')
            return redirect(reverse('management:tables') + f"?area={area.pk}&level={data.get('level', '')}")
        except (signing.BadSignature, ValidationError) as exc:
            error = ' '.join(exc.messages) if isinstance(exc, ValidationError) else 'La propuesta venció. Revisa nuevamente.'
    data = map_data(area, level=request.GET.get('level'))
    for row, position in suggestion(data['tables']):
        for key, value in position.items(): setattr(row, key, value)
    return page(request, 'table_arrange', {**data, 'error': error}, section='mesas', status=400 if error else 200)

from urllib.parse import urlencode
from math import ceil
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods
from django.views.generic import TemplateView
from apps.tables.models import VenueTable
from apps.venues.models import Area
from apps.reservations import queries, services
from . import public_site as site
from .public_forms import ReservationSearchForm, ReservationGuestForm


class HomeView(TemplateView):
    template_name = 'public/home.html'

    def get_context_data(self, **kwargs):
        upcoming = list(site.public_events().filter(status='PUBLISHED')[:4])
        return {**super().get_context_data(**kwargs), **site.context(self.request),
                'featured': upcoming[0] if upcoming else None, 'upcoming': upcoming[1:]}


@require_GET
def events(request):
    rows = Paginator(site.public_events(), 12).get_page(request.GET.get('page'))
    for event in rows:
        event.sale_label = site.sale_label(event)
    return render(request, 'public/events.html', {
        **site.context(request, title='Eventos', description='Descubre las próximas noches de BIG PARTY. Entradas y mesas para una experiencia inolvidable.'),
        'events': rows})


@require_GET
def reservations(request):
    return render(request,'public/reservations.html',{**site.context(request,title='Reserva tu mesa'),
        'form':ReservationSearchForm(initial={'party_size':4}), 'config':queries.get_settings()})


@require_GET
@never_cache
@site.private_view
def table_map(request):
    form = ReservationSearchForm(request.GET)
    config = queries.get_settings()
    groups=[]
    if form.is_valid() and config.reservations_enabled:
        data = form.cleaned_data
        available = set(queries.get_available_tables(data['date'],data['time'],config.default_duration_minutes,data['party_size']).values_list('pk',flat=True))
        # No datos de pedidos, ocupación, clientes ni razones operativas en la proyección pública.
        tables = VenueTable.objects.filter(reservable_web=True,is_active=True,area__is_active=True).select_related('area')
        areas={area.pk:dict(name=area.name,slug=area.slug,tables=[]) for area in Area.objects.filter(is_active=True)}
        for table in tables:
            group=areas.setdefault(table.area_id,dict(name=table.area.name,slug=table.area.slug,tables=[]))
            selection=signing.dumps({'table':table.pk,'date':data['date'].isoformat(),'time':data['time'].isoformat(),'party_size':data['party_size']},salt='public.reservation.choice') if table.pk in available else ''
            group['tables'].append(dict(name=table.name,capacity=table.capacity,available=table.pk in available,selection=selection,
                x=float(table.layout_x),y=float(table.layout_y),width=float(table.layout_width),height=float(table.layout_height),shape=table.layout_shape.lower()))
        groups=list(areas.values())
        # Un plano todavía sin distribución usa una cuadrícula honesta, sin superponer mesas.
        for group in groups:
            group['diagram']=site.has_public_layout(group['tables'])
            if group['diagram']:
                group['minimum_width'] = ceil(max(max(6000 / row['width'], 4800 / row['height']) for row in group['tables']))
    return render(request,'public/table_map.html',{**site.context(request,title='Elige tu mesa',private=True), 'form':form,'groups':groups,'has_available':any(t['available'] for g in groups for t in g['tables']),'config':config,
        'search':urlencode(request.GET.dict()),'selected_area':request.GET.get('area','')})


@require_http_methods(['GET','POST'])
@never_cache
@site.private_view
def reservation_guest(request):
    selection=request.POST.get('selection') if request.method=='POST' else request.GET.get('selection')
    form=ReservationGuestForm(request.POST if request.method=='POST' else None)
    error=''; table=None; data={}; config=queries.get_settings()
    try:
        data=signing.loads(selection or '',salt='public.reservation.choice',max_age=1800)
        search=ReservationSearchForm(data)
        if not search.is_valid(): raise ValidationError('Tu selección venció. Elige nuevamente fecha, hora y mesa.')
        data=search.cleaned_data | {'table':data['table']}
        table=VenueTable.objects.select_related('area').filter(pk=data['table'],reservable_web=True,is_active=True,area__is_active=True).first()
        if not table: raise ValidationError('Esta mesa ya no está disponible. Elige otra mesa para continuar.')
        if not queries.get_available_tables(data['date'],data['time'],config.default_duration_minutes,data['party_size']).filter(pk=table.pk).exists():
            raise ValidationError('Esta mesa acaba de ser reservada o ya no está disponible. Elige otra mesa para continuar.')
        if request.method=='POST' and form.is_valid():
            row=services.create_public_reservation_request(table,form.cleaned_data['customer_name'],form.cleaned_data['customer_phone'],data['date'],data['time'],data['party_size'])
            return redirect('reservation-client:detail',secure_token=row.secure_token)
    except (signing.BadSignature, TypeError, KeyError, ValueError):
        error='Tu selección venció. Elige nuevamente fecha, hora y mesa.'
        table=None
    except ValidationError as exc:
        error=site.public_error(exc)
        table=None
    return render(request,'public/reservation_guest.html',{**site.context(request,title='Tu próxima noche',private=True), 'form':form,'table':table,'selection':selection or '',
        'choice':data,'config':config,'error':error},status=409 if error else 200)


@require_GET
def sitemap(request):
    urls=[site.absolute(reverse(name)) for name in ['core:home','core:events','core:reservations']]
    urls += [site.absolute(reverse('event-public:event',args=[event.slug])) for event in site.public_events()]
    return render(request,'public/sitemap.xml',{'urls':urls},content_type='application/xml')


@require_GET
def robots(request):
    prefixes=['/admin/','/gerencia/','/operacion/','/caja/','/acceso/','/dispositivo/','/impresoras/','/dev/',
        '/reservas/r/','/reservas/mesas/','/reservas/datos/','/eventos/compra/','/entrada/']
    return HttpResponse('User-agent: *\n'+''.join('Disallow: '+prefix+'\n' for prefix in prefixes)+'Sitemap: '+site.absolute('/sitemap.xml')+'\n',content_type='text/plain')

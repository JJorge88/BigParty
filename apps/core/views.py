from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods
from django.views.generic import TemplateView
from . import public_site as site


class HomeView(TemplateView):
    template_name = 'public/home.html'

    def get_context_data(self, **kwargs):
        from .venue_information import venue_context
        upcoming = list(site.public_events().filter(status='PUBLISHED')[:4])
        public = site.context(self.request)
        return {**super().get_context_data(**kwargs), **public, **venue_context(public['brand']),
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
    return redirect('core:events')


@require_GET
@never_cache
def table_map(request):
    return redirect('core:events')


@require_http_methods(['GET', 'POST'])
@never_cache
def reservation_guest(request):
    # Retired public day-to-day booking, including old signed form submissions.
    return redirect('core:events')


@require_GET
def sitemap(request):
    urls=[site.absolute(reverse(name)) for name in ['core:home','core:events']]
    urls += [site.absolute(reverse('event-public:event',args=[event.slug])) for event in site.public_events()]
    return render(request,'public/sitemap.xml',{'urls':urls},content_type='application/xml')


@require_GET
def robots(request):
    prefixes=['/admin/','/gerencia/','/operacion/','/caja/','/acceso/','/dispositivo/','/impresoras/','/dev/',
        '/reservas/r/','/reservas/mesas/','/reservas/datos/','/eventos/compra/','/entrada/']
    return HttpResponse('User-agent: *\n'+''.join('Disallow: '+prefix+'\n' for prefix in prefixes)+'Sitemap: '+site.absolute('/sitemap.xml')+'\n',content_type='text/plain')

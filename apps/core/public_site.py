"""Presentación pública: utiliza los modelos y servicios de reservas/eventos existentes."""
from urllib.parse import urljoin
from django.conf import settings
from django.db.models import Min, Q
from django.templatetags.static import static
from django.utils import timezone
from apps.events.models import Event
from .configuration import business


def absolute(path):
    return urljoin(settings.PUBLIC_BASE_URL.rstrip('/')+'/', path.lstrip('/'))


def context(request, *, title='La noche comienza aquí.', description='Tres espacios. Una misma noche. Descubre los próximos eventos de BIG PARTY y reserva tu mesa.', image=None, private=False, canonical_path=None):
    hero = getattr(settings, 'PUBLIC_HERO_IMAGE', 'images/public/nightlife-hero.webp')
    return dict(brand=business(), page_title=title, meta_description=description,
                canonical='' if private else absolute(canonical_path or request.path),
                og_image=absolute(image or static(hero)),
                private_page=private, server_now=timezone.now().isoformat(),
                hero_image=hero,
                level_images=getattr(settings, 'PUBLIC_LEVEL_IMAGES', {}))


def public_events():
    now = timezone.now()
    return Event.objects.filter(status__in=('PUBLISHED','RESCHEDULED'), ends_at__gt=now).annotate(
        from_price=Min('ticket_types__price', filter=Q(ticket_types__is_active=True, ticket_types__is_courtesy_type=False,
            ticket_types__price__gt=0, ticket_types__sale_ends_at__gte=now))).order_by('starts_at','pk')


def public_error(exc, fallback='La disponibilidad cambió. Revisa tu selección e inténtalo de nuevo.'):
    """Solo mensajes de validación del dominio, sin nombres de campos/valores internos."""
    from django.core.exceptions import ValidationError
    if not isinstance(exc, ValidationError) or hasattr(exc, 'error_dict'):
        return fallback
    text = ' '.join(exc.messages)
    if any(value in text.lower() for value in ('token', 'constraint', 'unique', 'integrity', 'id=', 'pk=')):
        return fallback
    return text


def private_view(view):
    from functools import wraps
    @wraps(view)
    def wrapped(*args, **kwargs):
        response = view(*args, **kwargs)
        response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
        response['Referrer-Policy'] = 'same-origin'
        response['X-Content-Type-Options'] = 'nosniff'
        return response
    return wrapped


def sale_label(event):
    from apps.events import queries
    if not event.ticket_sales_enabled:
        return 'Venta cerrada'
    types = queries.ticket_type_rows(event)
    if any(kind.sellable for kind in types):
        return 'Entradas disponibles'
    remaining = queries.get_event_capacity_summary(event)['remaining']
    for table in queries.table_rows(event):
        if (table.available and table.cover_per_person > 0 and table.capacity_snapshot <= remaining
                and table.table.is_active and table.table.area.is_active
                and table.table.operational_status == 'ACTIVE' and table.ticket_type.is_active):
            return 'Mesas disponibles'
    if any(kind.is_active and not kind.is_courtesy_type and kind.price > 0
           and kind.sale_starts_at > timezone.now() for kind in types):
        return 'Próximamente'
    return 'Sin disponibilidad'

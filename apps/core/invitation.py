"""Temporary inauguration invitation, independent of ticketing and reservations."""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import Http404
from django.shortcuts import render
from django.templatetags.static import static
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET
from . import public_site as site
from .venue_information import venue_context


@require_GET
@never_cache
def inauguration(request):
    if not settings.PUBLIC_INVITATION_ENABLED:
        raise Http404
    starts_at = parse_datetime(settings.PUBLIC_INVITATION_STARTS_AT)
    if starts_at is None or timezone.is_naive(starts_at):
        raise ImproperlyConfigured('PUBLIC_INVITATION_STARTS_AT requiere una fecha ISO con zona horaria.')
    starts_at = timezone.localtime(starts_at)
    public = site.context(request, title='Estás invitado a nuestra inauguración',
        description='Celebremos el comienzo de BIG PARTY. Consulta la fecha, la hora y cómo llegar.',
        image=static('images/invitation/big-party-logo.png'), canonical_path='/ignaguracion')
    response = render(request, 'public/inauguration.html', {
        **public, 'venue_directions_url': venue_context(public['brand'])['venue_directions_url'],
        'invitation_starts_at': starts_at,
    })
    response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    return response

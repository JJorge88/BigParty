"""Public venue projection: one source for map, practical information and JSON-LD."""
import json
from decimal import Decimal
from urllib.parse import urlencode
from django.utils.safestring import mark_safe
from .models import BusinessOpeningHours
from .public_site import absolute

SCHEMA_DAYS = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
RESERVATION_RULES = (
    'Una solicitud no equivale a una reserva confirmada: BIG PARTY debe aprobarla. '
    'Algunas reservas requieren anticipo; en ese caso, se confirman después de verificar el pago. '
    'Conserva tu enlace privado para seguir el estado de tu solicitud.'
)
EVENT_RULES = (
    'Las entradas son individuales y cada entrada confirmada tiene un QR único. '
    'En una mesa de evento se reserva su capacidad completa: una mesa para 6 incluye 6 accesos individuales. '
    'El precio depende del evento. No se requiere consumo mínimo adicional para la mesa de evento.'
)
COVER_RULES = (
    'El cover es el valor de ingreso asociado a un evento. Su precio y condiciones se muestran antes de confirmar la compra. '
    'Cuando una mesa de evento incluye accesos, el total se calcula según la capacidad configurada de la mesa.'
)
EVENT_CHANGES = (
    'Si el evento se reprograma, tus entradas existentes continúan siendo válidas para la nueva fecha. '
    'Si se cancela, las entradas dejan de ser válidas. BIG PARTY comunica y gestiona la devolución; no es automática.'
)


def venue_context(brand):
    coordinates = f'{brand.latitude},{brand.longitude}'
    directions = 'https://www.google.com/maps/dir/?' + urlencode({'api': '1', 'destination': coordinates})
    latitude, longitude = Decimal(brand.latitude), Decimal(brand.longitude)
    bounds = (max(Decimal('-180'), longitude - Decimal('.008')), max(Decimal('-90'), latitude - Decimal('.006')),
              min(Decimal('180'), longitude + Decimal('.008')), min(Decimal('90'), latitude + Decimal('.006')))
    embed = 'https://www.openstreetmap.org/export/embed.html?' + urlencode({
        'bbox': ','.join(map(str, bounds)), 'layer': 'mapnik', 'marker': coordinates})
    hours = list(BusinessOpeningHours.objects.filter(is_open=True))
    hours_text = '; '.join(f'{row.get_weekday_display()}: {row.opens_at:%H:%M} — {row.closes_at:%H:%M}'
                          + (' del día siguiente' if row.crosses_midnight else '') for row in hours)
    faq = [
        dict(question='¿Dónde está BIG PARTY?', answer=brand.address_text or 'Estamos en Guatemala. Encuentra nuestra ubicación exacta en el mapa y abre la ruta para llegar.', link=directions, label='Cómo llegar', external=True),
        dict(question='¿Qué días abre BIG PARTY?', answer=hours_text or 'Consulta la fecha y hora en la información de cada evento antes de planificar tu visita.'),
        dict(question='¿Cuál es la edad mínima para ingresar?', answer=f'Mayores de {brand.minimum_entry_age} años.'),
        dict(question='¿Necesito identificación para entrar?', answer=brand.identification_text),
        dict(question='¿Existe código de vestimenta?', answer=' '.join(filter(None, [brand.dress_code, brand.dress_code_description]))),
        dict(question='¿Cómo funciona una reserva?', answer=RESERVATION_RULES),
        dict(question='¿Necesito pagar para reservar una mesa?', answer='Algunas reservas pueden requerir anticipo. Si tu solicitud lo requiere, verás las instrucciones en tu enlace privado y se confirmará después de verificar el pago.'),
        dict(question='¿Qué pasa si llegamos menos personas?', answer='Llegar con menos personas no invalida automáticamente una reserva normal. Para una mesa de evento se reserva la capacidad completa de la mesa.'),
        dict(question='¿Qué es el cover?', answer=COVER_RULES),
        dict(question='¿Cómo funcionan las mesas en eventos?', answer=EVENT_RULES),
        dict(question='¿Cómo recibo mis entradas?', answer='Después de confirmar tu compra, tus entradas están disponibles en el enlace privado de la compra. Cada entrada tiene un QR único; consérvalo para el ingreso.'),
        dict(question='¿Qué pasa si un evento es reprogramado o cancelado?', answer=EVENT_CHANGES),
    ]
    structured = {'@context': 'https://schema.org', '@type': 'NightClub', 'name': brand.business_name,
                  'url': absolute('/'), 'geo': {'@type': 'GeoCoordinates', 'latitude': str(brand.latitude), 'longitude': str(brand.longitude)}}
    if brand.address_text:
        structured['address'] = brand.address_text
    if brand.public_phone:
        structured['telephone'] = brand.public_phone
    if hours:
        structured['openingHoursSpecification'] = [
            {'@type': 'OpeningHoursSpecification', 'dayOfWeek': 'https://schema.org/' + SCHEMA_DAYS[row.weekday],
             'opens': row.opens_at.strftime('%H:%M'), 'closes': row.closes_at.strftime('%H:%M')} for row in hours]
    # Escape HTML-significant characters before marking only the serialized JSON safe.
    json_ld = json.dumps(structured, ensure_ascii=False).replace('&', '\\u0026').replace('<', '\\u003C').replace('>', '\\u003E')
    return dict(venue_map_url=embed, venue_directions_url=directions, opening_hours=hours,
                venue_faq=faq, venue_json_ld=mark_safe(json_ld), reservation_rules=RESERVATION_RULES, event_rules=EVENT_RULES,
                whatsapp_url='https://wa.me/' + brand.public_phone.lstrip('+') if brand.public_phone else '',
                telephone_url='tel:' + brand.public_phone if brand.public_phone else '')

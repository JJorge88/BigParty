from urllib.parse import urlencode
from django.conf import settings
from django.urls import reverse
from django.utils import timezone


def client_url(reservation):
    return settings.PUBLIC_BASE_URL + reverse('reservation-client:detail', args=[reservation.secure_token])


def whatsapp_url(reservation):
    date = reservation.reservation_date.strftime('%d/%m/%Y')
    detail = f'BIG PARTY · {reservation.public_code}\nMesa: {reservation.table.name}\nFecha: {date}\nHora: {reservation.start_time:%H:%M}\n'
    if reservation.status == 'AWAITING_PAYMENT':
        text = f'Tu reserva fue aprobada. Completa el anticipo de Q{reservation.payment_amount:.2f} antes del {timezone.localtime(reservation.payment_expires_at):%d/%m/%Y %H:%M}.\n'
    elif reservation.status == 'CONFIRMED':
        text = 'Tu reserva en BIG PARTY está confirmada.\n'
    elif reservation.status == 'REJECTED':
        # Los motivos internos permanecen en Gerencia; enlace permite consultar estado público.
        text = 'Lo sentimos, tu reserva no pudo confirmarse. Contacta a BIG PARTY para recibir atención.\n'
    else:
        text = 'Consulta el estado de tu reserva en BIG PARTY.\n'
    return 'https://wa.me/' + reservation.customer_phone.lstrip('+') + '?' + urlencode({'text': text + detail + 'Consulta tu reserva:\n' + client_url(reservation)})

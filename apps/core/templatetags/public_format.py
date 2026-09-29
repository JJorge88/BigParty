"""Formatting for public HTML only; never used in monetary calculations."""
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from django import template
from django.utils import timezone

register = template.Library()
WEEKDAYS = ('Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo')
MONTHS = ('enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre')


def local(value):
    return timezone.localtime(value) if isinstance(value, datetime) and timezone.is_aware(value) else value


@register.filter
def public_date(value):
    if not value:
        return ''
    value = local(value)
    return f'{WEEKDAYS[value.weekday()]} {value.day} de {MONTHS[value.month - 1]} de {value.year}'


@register.filter
def public_time(value):
    return local(value).strftime('%H:%M') if value else ''


def money(value, fixed):
    try:
        amount = Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        if not amount.is_finite():
            return ''
    except (InvalidOperation, TypeError, ValueError):
        return ''
    digits = 2 if fixed or amount != amount.to_integral_value() else 0
    return f'Q{amount:,.{digits}f}'


@register.filter
def quetzales(value):
    return money(value, False)


@register.filter
def payment_money(value):
    return money(value, True)

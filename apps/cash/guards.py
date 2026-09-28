"""Barrera transaccional de jornada: siempre antes de bloquear órdenes, sesiones o productos."""
from django.core.exceptions import ValidationError
from django.db import connection

from .models import BusinessDay


def lock_operation_gate():
    if not connection.in_atomic_block:
        raise RuntimeError("El bloqueo de jornada requiere una transacción.")
    # Una instalación/local. Evita carreras incluso cuando todavía no existe una jornada.
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [73190421])


def lock_open_day(day_id=None):
    lock_operation_gate()
    days = BusinessDay.objects.select_for_update().filter(status="OPEN")
    if day_id is not None:
        days = days.filter(pk=day_id)
    day = days.first()
    if day is None:
        raise ValidationError("Se requiere una jornada abierta; abre o reabre la jornada correspondiente.")
    return day


def lock_order_day(order_id):
    from apps.orders.models import TableOrder
    lock_operation_gate()
    day_id = TableOrder.objects.values_list("business_day_id", flat=True).get(pk=order_id)
    if day_id is None:
        raise ValidationError("Esta cuenta histórica no tiene jornada. Asígnala explícitamente antes de operarla.")
    return lock_open_day(day_id)

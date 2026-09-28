from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.orders.services import open_table_order
from apps.cash.guards import lock_open_day
from apps.tables.models import VenueTable


@transaction.atomic
def open_operational_table(context, table_id, billing_mode):
    user = context["user"]
    if not user.has_perm("orders.open_table_order"):
        raise PermissionDenied("No tienes permiso para abrir mesas.")
    # La identidad procede de la sesión validada, nunca de campos enviados por el cliente.
    lock_open_day()
    table = VenueTable.objects.select_for_update().filter(pk=table_id, area=context["area"], is_active=True).first()
    if table is None:
        raise ValidationError("Esta mesa no está disponible en el área del dispositivo.")
    if billing_mode not in ("SINGLE", "SPLIT"):
        raise ValidationError("Selecciona cómo deseas manejar la cuenta.")
    return open_table_order(table, user, responsible_waiter=user, billing_mode=billing_mode)

"""Lectura del mapa físico y cambios explícitos de configuración, sin lógica comercial."""
from apps.sync.services import sync_atomic, track, save_tracked
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.models import AuditLog

from .models import VenueTable

CONFIGURATION_FIELDS = (
    "area", "zone", "name", "capacity", "is_active", "operational_status", "reservable_web",
    "level", "sort_order", "layout_x", "layout_y", "layout_width", "layout_height", "layout_shape",
)


def get_area_table_map(area):
    """Incluye registros desactivados para configuración; coordenadas relativas al área.

    Devuelve identificadores, valores primitivos y listas ordenadas por sort_order,
    nombre y pk. No decide disponibilidad operativa ni pública.
    """
    return {
        "area": {
            "id": area.pk, "name": area.name, "slug": area.slug,
            "is_active": area.is_active, "sort_order": area.sort_order,
        },
        "zones": [
            {"id": zone.pk, "name": zone.name, "slug": zone.slug,
             "is_active": zone.is_active, "sort_order": zone.sort_order}
            for zone in area.zones.all()
        ],
        "tables": [
            {
                "id": table.pk, "name": table.name, "zone_id": table.zone_id,
                "capacity": table.capacity, "is_active": table.is_active,
                "operational_status": table.operational_status,
                "operational_status_label": table.get_operational_status_display(),
                "reservable_web": table.reservable_web, "sort_order": table.sort_order,
                "layout": {
                    "x": float(table.layout_x), "y": float(table.layout_y),
                    "width": float(table.layout_width), "height": float(table.layout_height),
                    "shape": table.layout_shape,
                },
            }
            for table in area.tables.all()
        ],
    }


@sync_atomic('local')
@transaction.atomic
def update_table_configuration(table, *, actor, **changes):
    """Guarda y audita en una sola transacción. El llamador debe comprobar permisos.

    Solo modifica los campos suministrados y bloquea la fila para comparar contra
    los valores persistidos actuales. No registra eventos si no cambió el valor.
    """
    unknown = set(changes) - set(CONFIGURATION_FIELDS)
    if unknown:
        raise ValidationError("La actualización contiene campos de configuración no permitidos.")
    if table.pk is None:
        raise ValidationError("La mesa debe estar guardada antes de actualizar su configuración.")
    current = VenueTable.objects.select_for_update().get(pk=table.pk)
    audited_fields = ("operational_status", "capacity", "reservable_web")
    before = {field: getattr(current, field) for field in audited_fields}
    changed = False
    for field, value in changes.items():
        if getattr(current, field) != value:
            setattr(current, field, value)
            changed = True
    if not changed:
        return current
    save_tracked(current)
    for field, old_value in before.items():
        new_value = getattr(current, field)
        if new_value == old_value:
            continue
        if field == "operational_status":
            action = (
                "table.out_of_service"
                if new_value == VenueTable.OperationalStatus.OUT_OF_SERVICE
                else "table.reactivated"
            )
        else:
            action = f"table.{field}_changed"
        track(AuditLog.objects.create(
            user=actor, action=action, entity=VenueTable._meta.label_lower,
            entity_id=str(current.pk),
            data={"field": field, "before": old_value, "after": new_value},
        ))
    return current

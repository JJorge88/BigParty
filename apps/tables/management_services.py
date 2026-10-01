"""Escrituras del editor: permisos, validación, concurrencia y auditoría."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from apps.audit.models import AuditLog
from apps.sync.services import sync_atomic, save_tracked, track
from .models import VenueTable
from .services import update_table_configuration

FIELDS = ('name', 'capacity', 'zone', 'layout_shape', 'layout_x', 'layout_y',
          'layout_width', 'layout_height', 'reservable_web', 'is_active', 'operational_status')


def snapshot(table):
    return {field: str(getattr(table, field + '_id' if field == 'zone' else field)) for field in FIELDS}


@sync_atomic('local')
@transaction.atomic
def save_table(area, data, *, actor, pk=None):
    permission = 'tables.change_venuetable' if pk else 'tables.add_venuetable'
    if not actor.is_active or actor.role not in ('GERENTE', 'PROPIETARIO') or not actor.has_perm(permission) or not actor.has_perm('tables.view_venuetable'):
        raise PermissionDenied('No tienes permiso para configurar mesas.')
    table = VenueTable.objects.select_for_update().get(pk=pk, area=area) if pk else VenueTable(area=area)
    if pk and data.get('revision') != table.updated_at.isoformat():
        raise ValidationError('Esta mesa cambió mientras la editabas. Vuelve al mapa y ábrela de nuevo antes de guardar.')
    before = snapshot(table) if pk else None
    changes = {field: data[field] for field in FIELDS if field in data}
    if pk:
        table = update_table_configuration(table, actor=actor, **changes)
    else:
        for field, value in changes.items():
            setattr(table, field, value)
        save_tracked(table)
    after = snapshot(table)
    if before != after:
        track(AuditLog.objects.create(user=actor, action='table.configuration_updated' if pk else 'table.created',
            entity=VenueTable._meta.label_lower, entity_id=str(table.pk), data={'before': before, 'after': after}))
    return table

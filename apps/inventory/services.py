"""Único punto soportado para entradas y ajustes del inventario global."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.audit.models import AuditLog
from apps.catalog.models import Product

from .models import InventoryMovement


def _require_permission(user, permission):
    if user is None or not user.is_active or not user.has_perm(f"inventory.{permission}"):
        raise PermissionDenied("No tienes permiso para realizar este movimiento de inventario.")


def _record_movement(product, delta, user, reason, movement_type, *, metadata=None):
    # Uso interno de servicios transaccionales; orders comprueba su permiso operativo.
    current = Product.objects.select_for_update().get(pk=product.pk)
    if not current.track_inventory or current.is_combo:
        raise ValidationError("Solo se pueden mover existencias de productos con control de inventario propio.")
    before = current.stock_quantity
    after = before + delta
    if after < 0:
        raise ValidationError("El ajuste dejaría existencias negativas.")
    current.stock_quantity = after
    current.save(update_fields=["stock_quantity", "updated_at"])
    movement = InventoryMovement(
        product=current, movement_type=movement_type, quantity_delta=delta,
        stock_before=before, stock_after=after, reason=reason, user=user, metadata=metadata or {},
    )
    movement.full_clean()
    movement.save()
    AuditLog.objects.create(
        user=user, action=f"inventory.{movement_type.lower()}", entity="catalog.product", entity_id=str(current.pk),
        data={"movement_id": movement.pk, "quantity_delta": delta,
              "stock_before": before, "stock_after": after, "reason": reason},
    )
    return movement


@transaction.atomic
def receive_stock(product, quantity, *, user, reason=""):
    _require_permission(user, "receive_inventory")
    if type(quantity) is not int or quantity <= 0:
        raise ValidationError("La entrada debe ser un número entero mayor que cero.")
    if not isinstance(reason, str):
        raise ValidationError("El motivo debe ser texto.")
    return _record_movement(product, quantity, user, reason.strip(), InventoryMovement.MovementType.RECEIPT)


@transaction.atomic
def adjust_stock(product, quantity_delta, *, user, reason):
    _require_permission(user, "adjust_inventory")
    if type(quantity_delta) is not int or quantity_delta == 0:
        raise ValidationError("El ajuste debe ser un número entero distinto de cero.")
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError("Indica el motivo del ajuste.")
    return _record_movement(product, quantity_delta, user, reason.strip(), InventoryMovement.MovementType.ADJUSTMENT)

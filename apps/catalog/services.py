"""Consultas de catálogo y escrituras explícitas de precios con historial."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Prefetch

from apps.audit.models import AuditLog

from .models import ComboComponent, Product, ProductAreaPrice, ProductPriceHistory


def get_product_price(product, area=None):
    if area is not None:
        override = next((price for price in product.area_prices.all() if price.area_id == area.pk), None)
        if override is not None:
            return override.price
    return product.base_price


def get_combo_max_available(combo):
    """0 si no está disponible; None si todos sus componentes son sin control."""
    if not combo.is_combo:
        raise ValidationError("El producto no es un combo.")
    if not combo.is_active or not combo.visible_in_pos or not combo.category.is_active:
        return 0
    components = list(combo.combo_components.all())
    if not components:
        return 0
    limits = []
    for item in components:
        product = item.component
        # Un insumo oculto puede participar; uno desactivado o anidado no.
        if product.is_combo or not product.is_active or not product.category.is_active:
            return 0
        if product.track_inventory:
            limits.append(product.stock_quantity // item.quantity)
    return min(limits) if limits else None


def is_combo_available(combo):
    maximum = get_combo_max_available(combo)
    return maximum is None or maximum > 0


def is_product_available(product):
    if not product.is_active or not product.visible_in_pos or not product.category.is_active:
        return False
    if product.is_combo:
        return is_combo_available(product)
    return not product.is_out_of_stock


def catalog_products():
    """Carga las relaciones que requieren las consultas de disponibilidad y precio."""
    return Product.objects.select_related("category").prefetch_related(
        "area_prices",
        Prefetch("combo_components", queryset=ComboComponent.objects.select_related("component__category")),
    )


def get_sellable_products(category=None, area=None):
    """Lista ordenada; area es contexto de precio, nunca una ubicación de stock."""
    products = catalog_products().filter(is_active=True, visible_in_pos=True, category__is_active=True)
    if category is not None:
        products = products.filter(category=category)
    return [product for product in products if is_product_available(product)]


def _require_price_permission(user):
    if user is None or not user.is_active or not user.has_perm("catalog.change_product_price"):
        raise PermissionDenied("No tienes permiso para cambiar precios.")


def _price_change(product, area, old_price, new_price, user):
    history = ProductPriceHistory.objects.create(
        product=product, area=area, old_price=old_price, new_price=new_price, changed_by=user,
    )
    AuditLog.objects.create(
        user=user, action="catalog.price_changed", entity="catalog.product", entity_id=str(product.pk),
        data={"area_id": area.pk if area else None,
              "old_price": str(old_price) if old_price is not None else None,
              "new_price": str(new_price), "history_id": history.pk},
    )


@transaction.atomic
def update_base_price(product, new_price, *, user):
    _require_price_permission(user)
    current = Product.objects.select_for_update().get(pk=product.pk)
    price = Product._meta.get_field("base_price").clean(new_price, current)
    old_price = current.base_price
    if old_price != price:
        current.base_price = price
        current.save(update_fields=["base_price", "updated_at"])
        _price_change(current, None, old_price, price, user)
    return current


@transaction.atomic
def update_area_price(product, area, new_price, *, user):
    _require_price_permission(user)
    current = Product.objects.select_for_update().get(pk=product.pk)
    override = ProductAreaPrice.objects.filter(product=current, area=area).first()
    old_price = override.price if override else None
    if override is None:
        override = ProductAreaPrice(product=current, area=area)
    price = ProductAreaPrice._meta.get_field("price").clean(new_price, override)
    if old_price != price:
        override.price = price
        override.save()
        _price_change(current, area, old_price, price, user)
    return override


@transaction.atomic
def remove_area_price(product, area, *, user):
    """Volver al precio general conserva el precio efectivo y la intención en auditoría."""
    _require_price_permission(user)
    current = Product.objects.select_for_update().get(pk=product.pk)
    override = ProductAreaPrice.objects.filter(product=current, area=area).first()
    if override:
        _price_change(current, area, override.price, current.base_price, user)
        override.delete()
        AuditLog.objects.create(user=user, action='catalog.area_price_removed',
            entity='catalog.product', entity_id=str(current.pk), data={'area_id': area.pk})

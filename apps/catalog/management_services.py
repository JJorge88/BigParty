"""Escrituras de catálogo usadas por Gerencia; stock y precios conservan sus servicios."""
from apps.sync.services import sync_atomic, save_tracked, delete_tracked
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from apps.audit.models import AuditLog
from .models import Category, Product, ModifierGroup, ModifierOption, ComboComponent
from .services import update_base_price

PRODUCT_FIELDS = ('barcode', 'name', 'slug', 'category', 'is_active', 'visible_in_pos', 'track_inventory',
                  'minimum_stock', 'preparation_route', 'image', 'is_combo')
FIELDS = {
    Category: ('name', 'slug', 'description', 'sort_order', 'is_active'),
    ModifierGroup: ('name', 'selection_type', 'min_selections', 'max_selections', 'sort_order', 'is_required', 'is_active'),
    ModifierOption: ('name', 'price_delta', 'sort_order', 'is_active'),
    ComboComponent: ('component', 'quantity', 'sort_order'),
}


def require(user, permission):
    if not user.is_active or not user.has_perm(permission):
        raise PermissionDenied('No tienes permiso para esta operación.')


def audit(user, obj, action):
    AuditLog.objects.create(user=user, action='catalog.' + action, entity=obj._meta.label_lower,
                            entity_id=str(obj.pk))


@sync_atomic('local')
@transaction.atomic
def save_product(data, *, user, pk=None):
    require(user, 'catalog.change_product' if pk else 'catalog.add_product')
    obj = Product.objects.select_for_update().get(pk=pk) if pk else Product()
    price = data.get('base_price', obj.base_price)
    if price != obj.base_price:
        require(user, 'catalog.change_product_price')
    for field in PRODUCT_FIELDS:
        if field in data:
            setattr(obj, field, '' if field == 'image' and data[field] is False else data[field])
    save_tracked(obj)
    obj = update_base_price(obj, price, user=user) if price != obj.base_price else obj
    audit(user, obj, 'product_updated' if pk else 'product_created')
    if not pk and data.get('initial_stock'):
        from apps.inventory.services import receive_stock
        receive_stock(obj, data['initial_stock'], user=user, reason='Existencias iniciales al crear el producto')
        obj.refresh_from_db()
    return obj


@sync_atomic('local')
@transaction.atomic
def save_catalog(model, data, *, user, pk=None, parent=None):
    if model not in FIELDS:
        raise ValidationError('Operación de catálogo no disponible.')
    require(user, f'catalog.{"change" if pk else "add"}_{model._meta.model_name}')
    # Siempre producto antes de componente; mismo orden que ComboComponent.save().
    if parent and model == ComboComponent:
        list(Product.objects.select_for_update().filter(pk__in=[parent.pk, data['component'].pk]).order_by('pk'))
    obj = model.objects.select_for_update().get(pk=pk) if pk else model()
    relation = {ModifierGroup: 'product', ModifierOption: 'group', ComboComponent: 'combo'}.get(model)
    if relation:
        if not parent or (pk and getattr(obj, relation + '_id') != parent.pk):
            raise ValidationError('El elemento no pertenece al producto seleccionado.')
        setattr(obj, relation, parent)
    for field in FIELDS[model]:
        if field in data:
            setattr(obj, field, '' if field == 'image' and data[field] is False else data[field])
    save_tracked(obj)
    audit(user, obj, model._meta.model_name + ('_updated' if pk else '_created'))
    return obj


@sync_atomic('local')
@transaction.atomic
def remove_component(pk, *, combo, user):
    require(user, 'catalog.delete_combocomponent')
    Product.objects.select_for_update().get(pk=combo.pk)
    obj = ComboComponent.objects.select_for_update().get(pk=pk, combo=combo)
    audit(user, obj, 'combocomponent_removed')
    delete_tracked(obj)

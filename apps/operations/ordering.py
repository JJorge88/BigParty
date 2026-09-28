"""Contexto y presentación de pedidos de tablet; las escrituras las resuelve orders."""
import re
import unicodedata

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Prefetch

from apps.cash.guards import lock_order_day
from apps.catalog.models import Category, ModifierGroup, ModifierOption
from apps.catalog.services import catalog_products, get_product_price, is_product_available
from apps.orders.models import ACTIVE_STATUSES, TableOrder
from apps.orders.queries import get_order_pending_total, get_subaccount_pending_total, get_subaccount_grand_total
from apps.tables.models import VenueTable
from .queries import money_label

ORDER_PERMISSIONS = ("add_order_line", "send_order", "manage_subaccounts")


def can_order(user):
    return any(user.has_perm("orders." + permission) for permission in ORDER_PERMISSIONS)


def positive_id(value, label="La selección"):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{1,18}", value) or int(value) < 1:
        raise ValidationError(f"{label} no es válida.")
    return int(value)


def operational_order(context, order_id, *, write=False, permission=None, access_check=can_order):
    user = context["user"]
    permission_name = permission if permission and "." in permission else "orders." + (permission or "")
    if (permission and not user.has_perm(permission_name)) or (not permission and not access_check(user)):
        raise PermissionDenied("No tienes permiso para realizar esta acción.")
    order = TableOrder.objects.filter(pk=order_id, area=context["area"]).select_related("area", "primary_table", "business_day").first()
    if order is None:
        raise ValidationError("Esta mesa no está disponible en el área del dispositivo.")
    if write:
        lock_order_day(order.pk)
        order = TableOrder.objects.select_for_update(of=("self",)).select_related("area", "primary_table", "business_day").get(pk=order.pk)
    if order.status not in ACTIVE_STATUSES or order.area_id != context["area"].pk:
        raise ValidationError("La cuenta ya fue cerrada o trasladada.")
    tables = VenueTable.objects.filter(order_links__order=order, order_links__released_at__isnull=True,
        area=context["area"], is_active=True, operational_status="ACTIVE")
    if write:
        tables = tables.select_for_update(of=("self",))
    if not list(tables.order_by("pk")):
        raise ValidationError("La mesa ya no está disponible.")
    return order


def selected_account(order, value, *, required=False):
    if order.billing_mode == "SINGLE":
        if value:
            raise ValidationError("Esta mesa utiliza una sola cuenta.")
        return None
    if not value:
        if required:
            raise ValidationError("Selecciona una cuenta para comenzar el pedido.")
        return None
    account = order.subaccounts.filter(pk=positive_id(value, "La cuenta")).first()
    if account is None or account.status != "OPEN":
        raise ValidationError("La cuenta seleccionada está cerrada o no está disponible.")
    return account


def normalize(text):
    return "".join(c for c in unicodedata.normalize("NFD", text.casefold()) if not unicodedata.combining(c))


def catalog_data(area, *, category="", search=""):
    # catalog_products incluye las relaciones del servicio de precio y disponibilidad;
    # conservamos agotados visibles, a diferencia de get_sellable_products.
    products = catalog_products().filter(is_active=True, visible_in_pos=True, category__is_active=True).prefetch_related(
        Prefetch("modifier_groups", queryset=ModifierGroup.objects.filter(is_active=True).prefetch_related(
            Prefetch("options", queryset=ModifierOption.objects.filter(is_active=True)))))
    if category:
        products = products.filter(category_id=positive_id(category, "La categoría"))
    result = []
    for product in products:
        if search and normalize(search.strip()) not in normalize(product.name):
            continue
        result.append({"id": product.pk, "name": product.name, "category_id": product.category_id,
            "category_name": product.category.name, "price": money_label(get_product_price(product, area)),
            "available": is_product_available(product), "is_combo": product.is_combo,
            "image": product.image.url if product.image else None,
            "groups": [{"id": group.pk, "name": group.name, "type": group.selection_type,
                "min": group.min_selections, "max": group.max_selections, "required": group.is_required,
                "options": [{"id": option.pk, "name": option.name, "extra": money_label(option.price_delta),
                             "has_extra": option.price_delta > 0} for option in group.options.all()]}
                for group in product.modifier_groups.all()]})
    return result


def order_state(order, user, account=None, *, category="", search="", draft_origin=""):
    drafts = order.lines.filter(status="DRAFT", subaccount=account, draft_origin=draft_origin).prefetch_related("modifiers").order_by("created_at", "pk")
    if order.billing_mode == "SPLIT" and account is None:
        drafts = drafts.none()
    total = sum(line.subtotal for line in drafts)
    lines = [{"id": line.pk, "name": line.product_name_snapshot, "quantity": line.quantity,
        "modifiers": [modifier.option_name_snapshot for modifier in line.modifiers.all()],
        "notes": line.notes, "unit_price": money_label(line.unit_price), "subtotal": money_label(line.subtotal)} for line in drafts]
    return {"order_id": order.pk, "table_name": order.display_name, "area": order.area.name,
        "billing_mode": order.billing_mode, "selected_account": account.pk if account else None,
        "selected_name": account.name if account else "Una sola cuenta" if order.billing_mode == "SINGLE" else "Selecciona una cuenta",
        "accounts": [{"id": sub.pk, "name": sub.name, "closed": sub.status == "CLOSED", "total": money_label(get_subaccount_grand_total(sub))}
                     for sub in order.subaccounts.order_by("created_at", "pk")],
        "categories": list(Category.objects.filter(is_active=True).values("id", "name")),
        "products": catalog_data(order.area, category=category, search=search),
        "drafts": lines, "draft_total": money_label(total), "draft_quantity": sum(line["quantity"] for line in lines),
        "has_open_day": bool(order.business_day and order.business_day.status == "OPEN"),
        "permissions": {permission: user.has_perm("orders." + permission) for permission in ORDER_PERMISSIONS}}


def product_for_order(value):
    product = catalog_products().filter(pk=positive_id(value, "El producto"), is_active=True,
        visible_in_pos=True, category__is_active=True).first()
    if product is None:
        raise ValidationError("El producto ya no está disponible.")
    return product


def friendly_error(exc):
    message = " ".join(exc.messages)
    stock = re.search(r"Stock insuficiente de «(.+?)»", message)
    if stock:
        return f"No hay existencias suficientes de {stock.group(1)}. El pedido sigue pendiente para corregirlo."
    return message


def ticket_destinations(ticket, area):
    if ticket is None:
        return []
    bar = {"sport-bar": "Barra 1", "discoteca": "Barra 2", "premium": "Barra 3"}.get(area.slug, f"Barra · {area.name}")
    routes = set(ticket.items.values_list("route", flat=True))
    return ([bar] if "AREA_BAR" in routes else []) + (["Cocina"] if "KITCHEN" in routes else [])

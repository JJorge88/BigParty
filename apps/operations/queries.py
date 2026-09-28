from django.utils import timezone

from apps.cash.models import BusinessDay
from apps.orders.models import ACTIVE_STATUSES, OrderTableLink
from apps.orders.queries import get_order_grand_total
from apps.tables.models import VenueTable

LABELS = {"AVAILABLE": "Libre", "OCCUPIED": "Ocupada", "OUT_OF_SERVICE": "Fuera de servicio",
          "PAYMENT_PENDING": "Pago pendiente", "PARTIALLY_PAID": "Pago parcial"}


def money_label(amount):
    return f"Q{amount:,.2f}"


def table_data(table, order=None):
    state = ("OUT_OF_SERVICE" if table.operational_status != "ACTIVE" else
             order.status if order and order.status in ("PAYMENT_PENDING", "PARTIALLY_PAID") else
             "OCCUPIED" if order else "AVAILABLE")
    seconds = max(0, int((timezone.now() - order.opened_at).total_seconds())) if order else 0
    return {"id": table.pk, "name": table.name, "area": table.area.name, "capacity": table.capacity,
            "state": state, "state_label": LABELS[state], "shape": table.layout_shape.lower(),
            "order_id": order.pk if order else None,
            "total": money_label(get_order_grand_total(order)) if order else None,
            "opened_at": order.opened_at.isoformat() if order else None,
            "elapsed": f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}",
            "responsible": (order.responsible_waiter.get_full_name().strip() or order.responsible_waiter.username) if order else None,
            "zone_id": table.zone_id,
            "layout": {"x": float(table.layout_x), "y": float(table.layout_y),
                       "width": float(table.layout_width), "height": float(table.layout_height)}}


def _has_layout(tables):
    if not tables or not any(t["layout"]["x"] or t["layout"]["y"] for t in tables):
        return False
    for i, first in enumerate(tables):
        a = first["layout"]
        for second in tables[i + 1:]:
            b = second["layout"]
            if a["x"] < b["x"] + b["width"] and b["x"] < a["x"] + a["width"] and a["y"] < b["y"] + b["height"] and b["y"] < a["y"] + a["height"]:
                return False
    return True


def get_operational_map(area):
    tables = list(VenueTable.objects.filter(area=area, is_active=True).select_related("area", "zone").order_by("zone__sort_order", "sort_order", "name", "pk"))
    links = OrderTableLink.objects.filter(table__in=tables, released_at__isnull=True, order__status__in=ACTIVE_STATUSES).select_related("order__responsible_waiter")
    orders = {link.table_id: link.order for link in links}
    groups = {}
    for table in tables:
        key = table.zone_id
        if key not in groups:
            groups[key] = {"id": key, "name": table.zone.name if key else "Área general", "tables": []}
        groups[key]["tables"].append(table_data(table, orders.get(table.pk)))
    for group in groups.values():
        group["has_layout"] = _has_layout(group["tables"])
    return {"groups": list(groups.values()), "has_open_day": BusinessDay.objects.filter(status="OPEN").exists(),
            "table_count": len(tables), "available_count": sum(t["state"] == "AVAILABLE" for g in groups.values() for t in g["tables"]),
            "occupied_count": sum(t["order_id"] is not None for g in groups.values() for t in g["tables"])}

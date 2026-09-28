"""Acciones del catálogo compartidas por mesero y caja."""
from django.core.exceptions import ValidationError
from apps.orders import services
from . import ordering as ops
from .queries import money_label


def apply_action(order, user, account, action, data, *, draft_origin="", fulfillment_mode="NORMAL_TABLE_SEND"):
    services._require(user, "manage_subaccounts" if action == "cuenta" else "send_order" if action == "enviar" else "add_order_line")
    message, destinations = "Pedido actualizado", []
    if action in ("agregar", "cotizar"):
        product = ops.product_for_order(data.get("product"))
        quantity = ops.positive_id(data.get("quantity", "1"), "La cantidad")
        if quantity > 9999:
            raise ValidationError("La cantidad máxima por operación es 9999.")
        modifiers = [ops.positive_id(value, "La opción") for value in data.getlist("modifiers")]
        if action == "cotizar":
            quote = services.get_order_product_quote(product, order.area, quantity, modifier_option_ids=modifiers)
            return {"quote": {"total": money_label(quote["total"]), "unit_price": money_label(quote["unit_price"])}, "account": account}
        services.add_product_to_order(order, product, quantity, user, subaccount=account,
            modifier_option_ids=modifiers, notes=data.get("notes", ""), draft_origin=draft_origin)
        message = f"{product.name} agregado"
    elif action in ("aumentar", "reducir", "eliminar", "nota"):
        line = order.lines.filter(pk=ops.positive_id(data.get("line"), "El producto"), status="DRAFT", subaccount=account, draft_origin=draft_origin).first()
        if line is None:
            raise ValidationError("Este producto ya fue enviado, retirado o pertenece a otra cuenta. Actualiza el pedido.")
        function = {"aumentar": services.increase_draft_line, "reducir": services.decrease_draft_line,
                    "eliminar": services.remove_draft_line, "nota": services.update_draft_line_note}[action]
        if action == "nota":
            function(line, data.get("notes", ""), user)
        else:
            function(line, user)
    elif action == "cuenta":
        account = services.create_subaccount(order, data.get("name", ""), user)
        message = "Cuenta creada"
    elif action == "enviar":
        if not order.lines.filter(status="DRAFT", subaccount=account, draft_origin=draft_origin).exists():
            raise ValidationError("No hay productos pendientes para enviar.")
        addition = order.activities.filter(activity_type="ORDER_SENT").exists()
        ticket = services.send_order(order, user, subaccount=account, draft_origin=draft_origin, fulfillment_mode=fulfillment_mode)
        destinations = ops.ticket_destinations(ticket, order.area)
        message = " · ".join(["Pedido enviado"] + (["Adición"] if addition else []) + destinations)
    return {"account": account, "message": message, "destinations": destinations}

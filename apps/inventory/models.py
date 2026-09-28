from django.conf import settings
from django.db import models


class InventoryMovement(models.Model):
    class MovementType(models.TextChoices):
        RECEIPT = "RECEIPT", "Entrada"
        ADJUSTMENT = "ADJUSTMENT", "Ajuste"
        REFUND_RETURN = "REFUND_RETURN", "Devolución por reembolso"
        SALE = "SALE", "Venta (consumo enviado)"
        CANCELLATION_RETURN = "CANCELLATION_RETURN", "Devolución por anulación"

    product = models.ForeignKey("catalog.Product", verbose_name="producto", on_delete=models.PROTECT, related_name="inventory_movements")
    movement_type = models.CharField("tipo", max_length=25, choices=MovementType.choices)
    quantity_delta = models.IntegerField("variación")
    stock_before = models.PositiveIntegerField("existencias anteriores")
    stock_after = models.PositiveIntegerField("existencias posteriores")
    reason = models.TextField("motivo", blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="usuario", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField("fecha", auto_now_add=True)
    metadata = models.JSONField("datos adicionales", default=dict, blank=True)

    class Meta:
        verbose_name = "Movimiento de inventario"
        verbose_name_plural = "Movimientos de inventario"
        ordering = ("-created_at", "-pk")
        permissions = [
            ("view_inventory", "Puede consultar el inventario global"),
            ("receive_inventory", "Puede registrar entradas de inventario"),
            ("adjust_inventory", "Puede realizar ajustes de inventario"),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(movement_type__in=["RECEIPT", "ADJUSTMENT", "SALE", "CANCELLATION_RETURN", "REFUND_RETURN"]), name="inventory_movement_type_valid"),
            models.CheckConstraint(condition=~models.Q(movement_type="SALE") | models.Q(quantity_delta__lt=0), name="inventory_sale_negative"),
            models.CheckConstraint(condition=~models.Q(movement_type="CANCELLATION_RETURN") | models.Q(quantity_delta__gt=0), name="inventory_return_positive"),
            models.CheckConstraint(condition=~models.Q(movement_type="REFUND_RETURN") | models.Q(quantity_delta__gt=0), name="inventory_refund_return_positive"),
            models.CheckConstraint(condition=~models.Q(quantity_delta=0), name="inventory_delta_nonzero"),
            models.CheckConstraint(condition=models.Q(stock_after=models.F("stock_before") + models.F("quantity_delta")), name="inventory_balance_consistent"),
            models.CheckConstraint(condition=~models.Q(movement_type="RECEIPT") | models.Q(quantity_delta__gt=0), name="inventory_receipt_positive"),
            models.CheckConstraint(condition=~models.Q(movement_type="ADJUSTMENT") | ~models.Q(reason=""), name="inventory_adjustment_reason"),
        ]

    def __str__(self):
        return f"{self.product} · {self.quantity_delta:+d}"

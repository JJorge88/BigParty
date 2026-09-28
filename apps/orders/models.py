from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

ACTIVE_STATUSES = ("OPEN", "PARTIALLY_PAID", "PAYMENT_PENDING")


class TableOrder(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Abierta"
        PARTIALLY_PAID = "PARTIALLY_PAID", "Parcialmente pagada"
        PAYMENT_PENDING = "PAYMENT_PENDING", "Pago pendiente"
        CLOSED = "CLOSED", "Cerrada"
        CANCELLED = "CANCELLED", "Cancelada"
        MERGED = "MERGED", "Unida"

    class BillingMode(models.TextChoices):
        SINGLE = "SINGLE", "Una sola cuenta"
        SPLIT = "SPLIT", "Cuentas separadas"

    business_day = models.ForeignKey("cash.BusinessDay", verbose_name="jornada", on_delete=models.PROTECT, null=True, blank=True, related_name="orders")
    primary_table = models.ForeignKey("tables.VenueTable", verbose_name="mesa principal", on_delete=models.PROTECT, related_name="primary_orders")
    tables = models.ManyToManyField("tables.VenueTable", through="OrderTableLink", related_name="orders", verbose_name="mesas vinculadas")
    area = models.ForeignKey("venues.Area", verbose_name="área de origen", on_delete=models.PROTECT)
    responsible_waiter = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="responsable", on_delete=models.PROTECT, related_name="responsible_orders")
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="abierta por", on_delete=models.PROTECT, related_name="opened_orders")
    status = models.CharField("estado", max_length=20, choices=Status.choices, default=Status.OPEN)
    billing_mode = models.CharField("modalidad", max_length=6, choices=BillingMode.choices, default=BillingMode.SINGLE)
    general_note = models.TextField("nota general", blank=True)
    merged_into = models.ForeignKey("self", verbose_name="unida a", on_delete=models.PROTECT, null=True, blank=True, related_name="merged_orders")
    opened_at = models.DateTimeField("apertura", default=timezone.now)
    closed_at = models.DateTimeField("finalización", null=True, blank=True)
    created_at = models.DateTimeField("creación", auto_now_add=True)
    updated_at = models.DateTimeField("actualización", auto_now=True)

    class Meta:
        verbose_name = "Cuenta de mesa"
        verbose_name_plural = "Cuentas de mesa"
        ordering = ("-opened_at", "-pk")
        permissions = [
            ("open_table_order", "Puede abrir mesas"), ("add_order_line", "Puede agregar y corregir productos"),
            ("send_order", "Puede enviar pedidos"), ("cancel_sent_order_line", "Puede anular productos enviados"),
            ("move_order_table", "Puede mover cuentas de mesa"), ("merge_orders", "Puede unir mesas y cuentas"),
            ("manage_subaccounts", "Puede gestionar subcuentas"),
        ]
        constraints = [
            models.UniqueConstraint(fields=("primary_table",), condition=models.Q(status__in=ACTIVE_STATUSES), name="orders_one_active_primary"),
            models.CheckConstraint(condition=models.Q(status__in=["OPEN", "PARTIALLY_PAID", "PAYMENT_PENDING", "CLOSED", "CANCELLED", "MERGED"]), name="orders_status_valid"),
            models.CheckConstraint(condition=models.Q(billing_mode__in=["SINGLE", "SPLIT"]), name="orders_billing_mode_valid"),
            models.CheckConstraint(condition=~models.Q(pk=models.F("merged_into")), name="orders_not_merged_into_self"),
            models.CheckConstraint(condition=models.Q(status="MERGED", merged_into__isnull=False) | (~models.Q(status="MERGED") & models.Q(merged_into__isnull=True)), name="orders_merge_target_consistent"),
        ]

    @property
    def order_number(self):
        return f"{self.pk:06d}" if self.pk else "Sin guardar"

    def __str__(self):
        return f"Pedido #{self.order_number}"


class OrderTableLink(models.Model):
    order = models.ForeignKey(TableOrder, verbose_name="cuenta", on_delete=models.PROTECT, related_name="table_links")
    table = models.ForeignKey("tables.VenueTable", verbose_name="mesa", on_delete=models.PROTECT, related_name="order_links")
    created_at = models.DateTimeField("vinculada", auto_now_add=True)
    released_at = models.DateTimeField("liberada", null=True, blank=True)

    class Meta:
        verbose_name = "Vínculo de mesa"
        verbose_name_plural = "Vínculos de mesas"
        constraints = [
            models.UniqueConstraint(fields=("order", "table"), name="orders_link_order_table_unique"),
            models.UniqueConstraint(fields=("table",), condition=models.Q(released_at__isnull=True), name="orders_one_active_link_per_table"),
        ]

    @property
    def is_primary(self):
        return self.order.primary_table_id == self.table_id


class SubAccount(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Abierta"
        CLOSED = "CLOSED", "Cerrada"

    order = models.ForeignKey(TableOrder, verbose_name="cuenta", on_delete=models.PROTECT, related_name="subaccounts")
    name = models.CharField("nombre", max_length=100)
    status = models.CharField("estado", max_length=6, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField("creación", auto_now_add=True)
    closed_at = models.DateTimeField("cierre", null=True, blank=True)

    class Meta:
        verbose_name = "Subcuenta"
        verbose_name_plural = "Subcuentas"
        ordering = ("created_at", "pk")
        constraints = [
            models.UniqueConstraint(fields=("id", "order"), name="orders_subaccount_id_order_unique"),
            models.CheckConstraint(condition=~models.Q(name=""), name="orders_subaccount_name_nonempty"),
            models.CheckConstraint(condition=models.Q(status__in=["OPEN", "CLOSED"]), name="orders_subaccount_status_valid"),
        ]

    def __str__(self):
        return self.name


class OrderLine(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Pendiente"
        SENT = "SENT", "Enviada"
        CANCELLED = "CANCELLED", "Cancelada"

    order = models.ForeignKey(TableOrder, verbose_name="cuenta", on_delete=models.PROTECT, related_name="lines")
    subaccount = models.ForeignKey(SubAccount, verbose_name="subcuenta", on_delete=models.PROTECT, null=True, blank=True, related_name="lines")
    product = models.ForeignKey("catalog.Product", verbose_name="producto", on_delete=models.PROTECT)
    product_name_snapshot = models.CharField("producto al agregar", max_length=150)
    is_combo_snapshot = models.BooleanField("era combo", default=False)
    quantity = models.PositiveIntegerField("cantidad", validators=[MinValueValidator(1)])
    unit_price = models.DecimalField("precio unitario (Q)", max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    base_unit_price = models.DecimalField("precio sin extras (Q)", max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    notes = models.TextField("nota", blank=True)
    status = models.CharField("estado", max_length=9, choices=Status.choices, default=Status.DRAFT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="agregada por", on_delete=models.PROTECT)
    source_line = models.ForeignKey("self", verbose_name="línea original", on_delete=models.PROTECT, null=True, blank=True, related_name="split_lines")
    created_at = models.DateTimeField("creación", auto_now_add=True)
    updated_at = models.DateTimeField("actualización", auto_now=True)

    class Meta:
        verbose_name = "Línea de pedido"
        verbose_name_plural = "Líneas de pedido"
        ordering = ("created_at", "pk")
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="orders_line_quantity_positive"),
            models.CheckConstraint(condition=models.Q(base_unit_price__gte=0, unit_price__gte=models.F("base_unit_price")), name="orders_line_price_valid"),
            models.CheckConstraint(condition=models.Q(status__in=["DRAFT", "SENT", "CANCELLED"]), name="orders_line_status_valid"),
        ]

    @property
    def subtotal(self):
        return self.quantity * self.unit_price

    def __str__(self):
        return f"{self.quantity} × {self.product_name_snapshot}"


class OrderLineModifier(models.Model):
    order_line = models.ForeignKey(OrderLine, verbose_name="línea", on_delete=models.PROTECT, related_name="modifiers")
    modifier_option = models.ForeignKey("catalog.ModifierOption", verbose_name="opción", on_delete=models.PROTECT)
    option_name_snapshot = models.CharField("opción al agregar", max_length=100)
    price_delta_snapshot = models.DecimalField("extra (Q)", max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])

    class Meta:
        verbose_name = "Modificador seleccionado"
        verbose_name_plural = "Modificadores seleccionados"
        constraints = [
            models.UniqueConstraint(fields=("order_line", "modifier_option"), name="orders_line_modifier_unique"),
            models.CheckConstraint(condition=models.Q(price_delta_snapshot__gte=0), name="orders_modifier_price_nonnegative"),
        ]


class OrderLineComponent(models.Model):
    """Composición y ruta congeladas; también contiene el producto de una línea normal."""
    order_line = models.ForeignKey(OrderLine, verbose_name="línea", on_delete=models.PROTECT, related_name="components")
    product = models.ForeignKey("catalog.Product", verbose_name="producto consumido", on_delete=models.PROTECT)
    quantity_per_unit = models.PositiveIntegerField("unidades por producto", validators=[MinValueValidator(1)])
    name_snapshot = models.CharField("nombre", max_length=150)
    route_snapshot = models.CharField("ruta", max_length=10, choices=[("AREA_BAR", "Barra del área"), ("KITCHEN", "Cocina"), ("NONE", "Sin preparación")])
    stock_deducted = models.BooleanField("se descontó inventario", default=False)

    class Meta:
        verbose_name = "Componente de línea"
        verbose_name_plural = "Componentes de líneas"
        constraints = [
            models.UniqueConstraint(fields=("order_line", "product"), name="orders_line_component_unique"),
            models.CheckConstraint(condition=models.Q(quantity_per_unit__gt=0), name="orders_component_quantity_positive"),
            models.CheckConstraint(condition=models.Q(route_snapshot__in=["AREA_BAR", "KITCHEN", "NONE"]), name="orders_component_route_valid"),
        ]


class PreparationTicket(models.Model):
    class TicketType(models.TextChoices):
        NEW = "NEW", "Pedido"
        ADDITION = "ADDITION", "Adición"
        CANCELLATION = "CANCELLATION", "Cancelación"
        UPDATE = "UPDATE", "Actualización"

    class Status(models.TextChoices):
        CREATED = "CREATED", "Creada"

    order = models.ForeignKey(TableOrder, verbose_name="cuenta de origen", on_delete=models.PROTECT, related_name="tickets")
    sequence_number = models.PositiveIntegerField("secuencia", validators=[MinValueValidator(1)])
    ticket_type = models.CharField("tipo", max_length=12, choices=TicketType.choices)
    status = models.CharField("estado", max_length=10, choices=Status.choices, default=Status.CREATED)
    table_name_snapshot = models.CharField("mesa al emitir", max_length=100)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="emitida por", on_delete=models.PROTECT)
    created_at = models.DateTimeField("emisión", auto_now_add=True)

    class Meta:
        verbose_name = "Comanda lógica"
        verbose_name_plural = "Comandas lógicas"
        ordering = ("order_id", "sequence_number")
        constraints = [
            models.UniqueConstraint(fields=("order", "sequence_number"), name="orders_ticket_sequence_unique"),
            models.CheckConstraint(condition=models.Q(sequence_number__gt=0), name="orders_ticket_sequence_positive"),
            models.CheckConstraint(condition=models.Q(ticket_type__in=["NEW", "ADDITION", "CANCELLATION", "UPDATE"]), name="orders_ticket_type_valid"),
        ]

    def __str__(self):
        return f"{self.order} · {self.get_ticket_type_display()} {self.sequence_number}"


class PreparationTicketItem(models.Model):
    ticket = models.ForeignKey(PreparationTicket, verbose_name="comanda", on_delete=models.PROTECT, related_name="items")
    order_line = models.ForeignKey(OrderLine, verbose_name="línea", on_delete=models.PROTECT, related_name="ticket_items")
    route = models.CharField("ruta", max_length=10, choices=[("AREA_BAR", "Barra del área"), ("KITCHEN", "Cocina")])
    area = models.ForeignKey("venues.Area", verbose_name="área de origen", on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField("cantidad", validators=[MinValueValidator(1)])
    description_snapshot = models.TextField("descripción")
    notes_snapshot = models.TextField("nota", blank=True)

    class Meta:
        verbose_name = "Detalle de comanda"
        verbose_name_plural = "Detalles de comandas"
        constraints = [
            models.CheckConstraint(condition=models.Q(route__in=["AREA_BAR", "KITCHEN"]), name="orders_ticket_route_valid"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="orders_ticket_quantity_positive"),
        ]


class OrderActivity(models.Model):
    class ActivityType(models.TextChoices):
        PAYMENT_RECORDED = "PAYMENT_RECORDED", "Pago registrado"
        PAYMENT_CONFIRMED = "PAYMENT_CONFIRMED", "Pago confirmado"
        PAYMENT_REJECTED = "PAYMENT_REJECTED", "Pago rechazado"
        ADJUSTMENT_APPLIED = "ADJUSTMENT_APPLIED", "Descuento o cortesía"
        REFUND = "REFUND", "Reembolso"
        CLOSED = "CLOSED", "Cuenta cerrada"
        OPENED = "OPENED", "Mesa abierta"
        PRODUCT_ADDED = "PRODUCT_ADDED", "Producto agregado"
        ORDER_SENT = "ORDER_SENT", "Pedido enviado"
        NOTE_UPDATED = "NOTE_UPDATED", "Nota actualizada"
        SUBACCOUNT_CREATED = "SUBACCOUNT_CREATED", "Subcuenta creada"
        LINE_MOVED = "LINE_MOVED", "Producto trasladado"
        TABLE_MOVED = "TABLE_MOVED", "Mesa trasladada"
        TABLES_MERGED = "TABLES_MERGED", "Mesas unidas"
        LINE_CANCELLED = "LINE_CANCELLED", "Línea anulada"
        DRAFT_UPDATED = "DRAFT_UPDATED", "Borrador corregido"
        BILLING_MODE_CHANGED = "BILLING_MODE_CHANGED", "Modalidad cambiada"

    order = models.ForeignKey(TableOrder, verbose_name="cuenta actual", on_delete=models.PROTECT, related_name="activities")
    origin_order = models.ForeignKey(TableOrder, verbose_name="cuenta de origen", on_delete=models.PROTECT, related_name="original_activities")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="usuario", on_delete=models.PROTECT)
    activity_type = models.CharField("operación", max_length=25, choices=ActivityType.choices)
    description = models.TextField("descripción")
    metadata = models.JSONField("datos", default=dict, blank=True)
    created_at = models.DateTimeField("fecha", auto_now_add=True)

    class Meta:
        verbose_name = "Actividad de cuenta"
        verbose_name_plural = "Historial operativo"
        ordering = ("-created_at", "-pk")

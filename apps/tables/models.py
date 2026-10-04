from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.venues.models import Area, Zone


class VenueTable(models.Model):
    class OperationalStatus(models.TextChoices):
        ACTIVE = "ACTIVE", "Activa"
        OUT_OF_SERVICE = "OUT_OF_SERVICE", "Fuera de servicio"

    class LayoutShape(models.TextChoices):
        RECTANGLE = "RECTANGLE", "Rectangular"
        CIRCLE = "CIRCLE", "Circular"

    area = models.ForeignKey(Area, verbose_name="área", on_delete=models.PROTECT, related_name="tables")
    zone = models.ForeignKey(
        Zone, verbose_name="zona", on_delete=models.PROTECT, related_name="tables", null=True, blank=True,
    )
    level = models.CharField("nivel (opcional)", max_length=12, blank=True, default="",
        choices=[("", "Sin definir"), ("LEVEL_1", "Nivel 1"), ("LEVEL_2", "Nivel 2")],
        help_text="Asígnalo cuando la distribución esté confirmada. El nivel no determina si una mesa es VIP.")
    name = models.CharField("nombre", max_length=100)
    capacity = models.PositiveIntegerField("capacidad", validators=[MinValueValidator(1)])
    is_active = models.BooleanField("activa administrativamente", default=True)
    operational_status = models.CharField(
        "estado operativo", max_length=20, choices=OperationalStatus.choices, default=OperationalStatus.ACTIVE,
    )
    reservable_web = models.BooleanField("reservable en la web", default=False)
    sort_order = models.PositiveIntegerField("orden visual", default=0)
    layout_x = models.DecimalField(
        "posición horizontal (%)", max_digits=5, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    layout_y = models.DecimalField(
        "posición vertical (%)", max_digits=5, decimal_places=2, default=Decimal("0.00"),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    layout_width = models.DecimalField(
        "ancho (%)", max_digits=5, decimal_places=2, default=Decimal("10.00"),
        validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(100)],
    )
    layout_height = models.DecimalField(
        "alto (%)", max_digits=5, decimal_places=2, default=Decimal("10.00"),
        validators=[MinValueValidator(Decimal("0.01")), MaxValueValidator(100)],
    )
    layout_shape = models.CharField(
        "forma", max_length=10, choices=LayoutShape.choices, default=LayoutShape.RECTANGLE,
    )
    created_at = models.DateTimeField("fecha de creación", auto_now_add=True)
    updated_at = models.DateTimeField("última actualización", auto_now=True)

    class Meta:
        verbose_name = "Mesa"
        verbose_name_plural = "Mesas"
        ordering = ("sort_order", "name", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("area", "name"), name="tables_area_name_unique",
                violation_error_message="Ya existe una mesa con este nombre en el área.",
            ),
            models.CheckConstraint(condition=models.Q(capacity__gt=0), name="tables_capacity_positive"),
            models.CheckConstraint(
                condition=models.Q(operational_status__in=["ACTIVE", "OUT_OF_SERVICE"]),
                name="tables_operational_status_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(layout_shape__in=["RECTANGLE", "CIRCLE"]), name="tables_shape_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(layout_x__gte=0, layout_x__lte=100), name="tables_layout_x_range",
            ),
            models.CheckConstraint(
                condition=models.Q(layout_y__gte=0, layout_y__lte=100), name="tables_layout_y_range",
            ),
            models.CheckConstraint(
                condition=models.Q(layout_width__gt=0, layout_width__lte=100), name="tables_width_range",
            ),
            models.CheckConstraint(
                condition=models.Q(layout_height__gt=0, layout_height__lte=100), name="tables_height_range",
            ),
            models.CheckConstraint(
                condition=models.Q(layout_x__lte=100 - models.F("layout_width")), name="tables_right_boundary",
                violation_error_message="La mesa no puede superar el borde derecho del área.",
            ),
            models.CheckConstraint(
                condition=models.Q(layout_y__lte=100 - models.F("layout_height")), name="tables_bottom_boundary",
                violation_error_message="La mesa no puede superar el borde inferior del área.",
            ),
        ]

    def __str__(self):
        return " · ".join(filter(None, [str(self.area), self.get_level_display() if self.level else "", self.name]))

    def clean(self):
        super().clean()
        if self.zone_id and self.area_id:
            zone_area_id = Zone.objects.filter(pk=self.zone_id).values_list("area_id", flat=True).first()
            if zone_area_id is not None and zone_area_id != self.area_id:
                raise ValidationError({"zone": "La zona debe pertenecer a la misma área que la mesa."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

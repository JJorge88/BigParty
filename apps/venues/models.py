from django.core.exceptions import ValidationError
from django.db import models


class Area(models.Model):
    name = models.CharField("nombre", max_length=100, unique=True)
    slug = models.SlugField("identificador", max_length=100, unique=True)
    description = models.TextField("descripción", blank=True)
    is_active = models.BooleanField("activa", default=True)
    sort_order = models.PositiveIntegerField("orden visual", default=0)
    created_at = models.DateTimeField("fecha de creación", auto_now_add=True)
    updated_at = models.DateTimeField("última actualización", auto_now=True)

    class Meta:
        verbose_name = "Área"
        verbose_name_plural = "Áreas"
        ordering = ("sort_order", "name", "pk")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class Zone(models.Model):
    area = models.ForeignKey(Area, verbose_name="área", on_delete=models.PROTECT, related_name="zones")
    name = models.CharField("nombre", max_length=100)
    slug = models.SlugField("identificador", max_length=100)
    description = models.TextField("descripción", blank=True)
    is_active = models.BooleanField("activa", default=True)
    sort_order = models.PositiveIntegerField("orden visual", default=0)
    created_at = models.DateTimeField("fecha de creación", auto_now_add=True)
    updated_at = models.DateTimeField("última actualización", auto_now=True)

    class Meta:
        verbose_name = "Zona"
        verbose_name_plural = "Zonas"
        ordering = ("sort_order", "name", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("area", "name"), name="venues_zone_area_name_unique",
                violation_error_message="Ya existe una zona con este nombre en el área.",
            ),
            models.UniqueConstraint(
                fields=("area", "slug"), name="venues_zone_area_slug_unique",
                violation_error_message="Ya existe una zona con este identificador en el área.",
            ),
            # Clave de referencia para la FK compuesta de mesas (migración tables.0002).
            models.UniqueConstraint(fields=("id", "area"), name="venues_zone_id_area_unique"),
        ]

    def __str__(self):
        return f"{self.area} · {self.name}"

    def clean(self):
        super().clean()
        if self.pk and self.area_id and self.tables.exclude(area_id=self.area_id).exists():
            raise ValidationError({"area": "No puedes trasladar una zona con mesas de otra área."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

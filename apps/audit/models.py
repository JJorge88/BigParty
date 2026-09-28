from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="usuario",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField("acción", max_length=100)
    entity = models.CharField("entidad", max_length=100)
    entity_id = models.CharField("identificador de entidad", max_length=255, blank=True)
    data = models.JSONField("datos", default=dict, blank=True)
    created_at = models.DateTimeField("fecha y hora", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "registro de auditoría"
        verbose_name_plural = "registros de auditoría"
        ordering = ("-created_at", "-pk")

    def __str__(self):
        return f"{self.action}: {self.entity} ({self.entity_id})"

import re

from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


def validate_pin(pin):
    # Texto para conservar ceros iniciales y evitar conversiones ambiguas.
    if not isinstance(pin, str) or re.fullmatch(r"[0-9]{4,12}", pin) is None:
        raise ValidationError("El PIN debe contener entre 4 y 12 dígitos.")


class User(AbstractUser):
    class Role(models.TextChoices):
        MESERO = "MESERO", "Mesero"
        CAJERO = "CAJERO", "Cajero"
        GERENTE = "GERENTE", "Gerente"
        PROPIETARIO = "PROPIETARIO", "Propietario"
        GUARDIA = "GUARDIA", "Guardia"

    role = models.CharField("rol base", max_length=20, choices=Role.choices, default=Role.MESERO)
    pin_hash = models.CharField("hash del PIN", max_length=128, blank=True, editable=False)

    class Meta(AbstractUser.Meta):
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        permissions = [
            ('reset_user_pin', 'Puede restablecer PIN de usuarios'),
            ('change_user_credentials', 'Puede cambiar contraseñas de usuarios'),
            ('change_user_role', 'Puede cambiar roles base'),
            ('activate_user', 'Puede activar y desactivar usuarios'),
            ('manage_user_permissions', 'Puede administrar permisos individuales'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=["MESERO", "CAJERO", "GERENTE", "PROPIETARIO", "GUARDIA"]),
                name="accounts_user_valid_role",
            ),
        ]

    def has_perm(self, perm, obj=None):
        if self.role == self.Role.PROPIETARIO and not self.is_superuser:
            return self.is_active and perm == 'core.view_reports' and obj is None
        return super().has_perm(perm, obj)

    def has_module_perms(self, app_label):
        if self.role == self.Role.PROPIETARIO and not self.is_superuser:
            return False
        return super().has_module_perms(app_label)

    def set_pin(self, raw_pin):
        """Establece un hash con sal; None deshabilita el PIN. Guardar aparte."""
        if raw_pin is not None:
            validate_pin(raw_pin)
        self.pin_hash = make_password(raw_pin)

    def check_pin(self, raw_pin):
        """Solo comprueba el PIN; no inicia una sesión ni autentica al usuario."""
        if not self.pin_hash or not isinstance(raw_pin, str):
            return False
        return check_password(raw_pin, self.pin_hash)

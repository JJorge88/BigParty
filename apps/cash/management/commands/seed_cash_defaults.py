from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.venues.models import Area
from apps.cash.models import CashRegister
from apps.cash.guards import lock_operation_gate


class Command(BaseCommand):
    help = "Crea las tres estaciones de caja sobre las áreas existentes, sin sobrescribir configuración."

    @transaction.atomic
    def handle(self, *args, **options):
        lock_operation_gate()
        defaults = [("SPORT", "Caja Sport Bar", "sport-bar"), ("DISCO", "Caja Discoteca", "discoteca"), ("PREMIUM", "Caja Premium", "premium")]
        created = 0
        for code, name, slug in defaults:
            area = Area.objects.filter(slug=slug).first()
            if area is None:
                raise CommandError(f"Falta el área {slug}; ejecuta primero seed_bigparty_defaults.")
            register = CashRegister.objects.filter(code=code).first()
            if register and register.area_id != area.pk:
                raise CommandError(f"El código {code} ya pertenece a otra área. No se sobrescribió configuración.")
            if register is None:
                try:
                    CashRegister.objects.create(code=code, name=name, area=area)
                except ValidationError as exc:
                    raise CommandError(" ".join(exc.messages)) from exc
                created += 1
        self.stdout.write(self.style.SUCCESS(f"Cajas creadas: {created}. Existentes conservadas: {3-created}."))

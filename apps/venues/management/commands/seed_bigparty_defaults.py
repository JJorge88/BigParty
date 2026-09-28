from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from apps.venues.models import Area


class Command(BaseCommand):
    help = "Crea Sport Bar, Discoteca y Premium sin zonas ni mesas ni cambios a áreas existentes."

    def handle(self, *args, **options):
        defaults = (
            ("Sport Bar", "sport-bar", 10),
            ("Discoteca", "discoteca", 20),
            ("Premium", "premium", 30),
        )
        created_count = 0
        try:
            with transaction.atomic():
                for name, slug, sort_order in defaults:
                    _, created = Area.objects.get_or_create(
                        slug=slug,
                        defaults={"name": name, "sort_order": sort_order},
                    )
                    created_count += int(created)
        except (ValidationError, IntegrityError) as exc:
            raise CommandError(
                "No se cargaron las áreas. Revisa si un nombre inicial ya existe con otro "
                "identificador. No se han sobrescrito registros."
            ) from exc
        self.stdout.write(self.style.SUCCESS(
            f"Áreas creadas: {created_count}. Áreas existentes conservadas: {3 - created_count}."
        ))

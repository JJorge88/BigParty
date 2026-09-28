from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from apps.catalog.models import Category


class Command(BaseCommand):
    help = "Crea las seis categorías iniciales sin productos ni cambios a categorías existentes."

    def handle(self, *args, **options):
        defaults = [("Cervezas", "cervezas"), ("Licores", "licores"), ("Cócteles", "cocteles"),
                    ("Comida", "comida"), ("Snacks", "snacks"), ("Combos", "combos")]
        created_count = 0
        try:
            with transaction.atomic():
                for index, (name, slug) in enumerate(defaults, start=1):
                    _, created = Category.objects.get_or_create(
                        slug=slug, defaults={"name": name, "sort_order": index * 10},
                    )
                    created_count += int(created)
        except (ValidationError, IntegrityError) as exc:
            raise CommandError("Conflicto de nombres o identificadores; no se modificaron las categorías existentes.") from exc
        self.stdout.write(self.style.SUCCESS(f"Categorías creadas: {created_count}. Existentes conservadas: {6 - created_count}."))

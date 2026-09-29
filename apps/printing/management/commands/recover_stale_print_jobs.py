from django.core.management.base import BaseCommand, CommandError
from apps.printing.services import recover_stale_jobs


class Command(BaseCommand):
    help = 'Marca PRINTING abandonados como FAILED para revisión manual; nunca vuelve a imprimir.'

    def add_arguments(self, parser):
        parser.add_argument('--seconds', type=int, default=None)

    def handle(self, *args, **options):
        if options['seconds'] is not None and options['seconds'] < 30:
            raise CommandError('Usa al menos 30 segundos.')
        self.stdout.write(f"Recuperados para revisión: {len(recover_stale_jobs(seconds=options['seconds']))}")

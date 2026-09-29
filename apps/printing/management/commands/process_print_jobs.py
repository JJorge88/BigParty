from django.core.management.base import BaseCommand
from apps.printing.models import PrintJob
from apps.printing.services import print_job


class Command(BaseCommand):
    help = 'Ejecuta una tanda acotada de PENDING; no reintenta fallidos ni PRINTING.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=20)

    def handle(self, *args, **options):
        ids = list(PrintJob.objects.filter(status='PENDING').order_by('pk').values_list('pk',flat=True)[:max(0,min(options['limit'],100))])
        for pk in ids:
            print_job(pk)
        self.stdout.write(f'Tanda revisada: {len(ids)}')

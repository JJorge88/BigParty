from django.core.management.base import BaseCommand
from apps.core.ops.backups import retain
class Command(BaseCommand):
    help='Retención por buckets; simulación por defecto. Solo backups propios verificados.'
    def add_arguments(self,parser):parser.add_argument('--apply',action='store_true')
    def handle(self,*args,**options):
        rows=retain(options['apply']);self.stdout.write(f"{'Eliminados' if options['apply'] else 'Candidatos'}: {len(rows)}")

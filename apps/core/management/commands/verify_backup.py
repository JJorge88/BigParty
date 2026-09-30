from django.core.management.base import BaseCommand
from apps.core.ops.backups import verify
class Command(BaseCommand):
    help='Verifica manifiesto, tamaño, SHA256 y formato sin depender de la base.'
    def add_arguments(self,parser):parser.add_argument('manifest')
    def handle(self,*args,**options):
        info=verify(options['manifest']);self.stdout.write('Verificado: '+info['backup_id'])

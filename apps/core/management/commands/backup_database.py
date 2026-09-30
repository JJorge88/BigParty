from django.core.management.base import BaseCommand,CommandError
from apps.core.ops import backups

class Command(BaseCommand):
    help='Backup database; manifiesto externo, sin secretos.'
    def add_arguments(self,parser):
        parser.add_argument('--secondary',action='store_true')
        parser.add_argument('--offsite',action='store_true')
    def handle(self,*args,**options):
        manifest=backups.backup_database()
        if options['secondary']:backups.copy_secondary(manifest)
        if options['offsite']:backups.offsite(manifest)
        self.stdout.write('Backup creado: '+manifest.name)

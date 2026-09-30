from django.core.management.base import BaseCommand
from apps.core.ops.recovery import complete
class Command(BaseCommand):
    def add_arguments(self,parser):
        parser.add_argument('--confirm',action='store_true');parser.add_argument('--sync-reviewed',action='store_true')
    def handle(self,*args,**options):
        complete(options['confirm'],options['sync_reviewed']);self.stdout.write('Recuperación completada; reinicia el worker explícitamente cuando corresponda.')

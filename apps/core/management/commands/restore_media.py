from django.core.management.base import BaseCommand
from apps.core.ops.backups import restore_media
class Command(BaseCommand):
    help='Extrae a una carpeta privada separada; no sobrescribe sin --force --confirm.'
    def add_arguments(self,parser):
        parser.add_argument('manifest');parser.add_argument('--target-directory',required=True)
        parser.add_argument('--force',action='store_true');parser.add_argument('--confirm',action='store_true')
    def handle(self,*args,**options):
        restore_media(options['manifest'],options['target_directory'],options['force'],options['confirm'])
        self.stdout.write('Media restaurada y verificada; configura sus raíces antes de liberar recuperación.')

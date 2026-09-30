from django.core.management.base import BaseCommand,CommandError
from apps.core.ops.backups import restore_database
import psycopg
class Command(BaseCommand):
    help='Restaura a una base NUEVA. Nunca DROP ni reemplazo de base activa.'
    def add_arguments(self,parser):
        parser.add_argument('manifest',help='Manifiesto verificado del dump; ambos deben conservar su estructura.')
        parser.add_argument('--target-database',required=True)
        parser.add_argument('--confirm',action='store_true')
    def handle(self,*args,**options):
        try:restore_database(options['manifest'],options['target_database'],options['confirm'])
        except psycopg.Error:raise CommandError('RESTORE_DATABASE_ERROR: revisa conectividad y permisos del operador de recuperación.') from None
        self.stdout.write('Restauración terminada. Modo recuperación activo; configura la base destino y verifica antes de operar.')

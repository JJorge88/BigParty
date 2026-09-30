from django.core.management.base import BaseCommand,CommandError
from apps.core.ops.integrity import restored_report
from apps.core.ops.backups import verify,db_parameters,fingerprint
import psycopg
class Command(BaseCommand):
    help='Revisa restauración, migraciones, media y opcionalmente fingerprint exacto del dump.'
    def add_arguments(self,parser):parser.add_argument('--manifest')
    def handle(self,*args,**options):
        report=restored_report()
        for label,count in report['counts'].items():self.stdout.write(f'{label}: {count}')
        if options['manifest']:
            info=verify(options['manifest'])
            if info['kind']!='database':raise CommandError('DATABASE_MANIFEST_REQUIRED')
            with psycopg.connect(**db_parameters()) as connection:
                connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                if fingerprint(connection)!=info.get('verification'):raise CommandError('RESTORED_FINGERPRINT_MISMATCH')
            from apps.localnode.models import LocalNodeIdentity
            if info.get('node_uuid') and str(LocalNodeIdentity.objects.get(pk=1).node_uuid)!=info['node_uuid']:raise CommandError('NODE_IDENTITY_MISMATCH')
        for error in report['errors']:self.stdout.write(error['code']+': '+str(error['count']))
        if report['errors']:raise CommandError('RESTORED_SYSTEM_REQUIRES_REVIEW')
        self.stdout.write('Verificación correcta; revisa cursores/Cloud antes de completar recuperación.')

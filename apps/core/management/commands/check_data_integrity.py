from django.core.management.base import BaseCommand,CommandError
from apps.core.ops.integrity import integrity
class Command(BaseCommand):
    help='Invariantes de solo lectura, sin reparación automática.'
    def handle(self,*args,**options):
        report=integrity()
        for code,count in report['checks'].items():self.stdout.write(f'{code}: {count}')
        if report['errors']:raise CommandError('INTEGRITY_ERRORS: requiere revisión específica.')

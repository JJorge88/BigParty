from django.core.management.base import BaseCommand,CommandError
from apps.core.ops.repo_safety import scan
class Command(BaseCommand):
    help='Escanea archivos versionados sin imprimir valores de secretos.'
    def handle(self,*args,**options):
        findings=scan()
        for path,code in findings:self.stdout.write(code+': '+path)
        if findings:raise CommandError('REPO_SAFETY_FINDINGS')
        self.stdout.write('Sin secretos/configuración privada detectados en archivos versionados; no es una garantía exhaustiva.')

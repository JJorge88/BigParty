from django.core.management.base import BaseCommand, CommandError
from apps.localnode.diagnostics import inspect_node

class Command(BaseCommand):
    help = 'Diagnóstico de solo lectura; no contacta impresoras ni servicios externos.'
    def handle(self, *args, **options):
        checks, warnings = inspect_node()
        for label, ok in checks:
            self.stdout.write(f'{"OK" if ok else "ERROR"}: {label}')
        for warning in warnings:
            self.stdout.write('AVISO: ' + warning)
        if not all(ok for _,ok in checks):
            raise CommandError('Nodo incompleto. Revisa los controles indicados.')

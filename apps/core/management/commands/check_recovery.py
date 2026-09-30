from django.core.management.base import BaseCommand
from apps.core.ops.recovery import status
class Command(BaseCommand):
    def handle(self,*args,**options):self.stdout.write('Modo recuperación: '+('ACTIVO' if status()['active'] else 'inactivo'))

from django.core.management.base import BaseCommand
from apps.core.ops.recovery import enter
class Command(BaseCommand):
    def handle(self,*args,**options):enter();self.stdout.write('Modo recuperación activo y persistido.')

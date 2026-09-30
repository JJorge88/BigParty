from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from apps.localnode.models import LocalNodeIdentity

class Command(BaseCommand):
    help = 'Inicializa una identidad estable sin reemplazar datos existentes.'
    def add_arguments(self, parser):
        parser.add_argument('--name', default=None)
    def handle(self, *args, **options):
        if settings.DEPLOYMENT_MODE != 'local_node':
            raise CommandError('Requiere modo local_node.')
        name = options['name'] or getattr(settings, 'LOCAL_NODE_NAME', 'BIG PARTY Principal')
        if not name.strip() or len(name) > 120:
            raise CommandError('Nombre de nodo inválido.')
        node, created = LocalNodeIdentity.objects.get_or_create(pk=1, defaults={'name':name})
        self.stdout.write(f'Identidad {"creada" if created else "conservada"}: {node.name} · {str(node.node_uuid)[:8]}')

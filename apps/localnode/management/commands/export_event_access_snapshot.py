import json
from pathlib import Path
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from apps.events.models import Event
from apps.localnode.snapshots import signed_snapshot

class Command(BaseCommand):
    help = 'Exporta el snapshot schema-1 existente con firma HMAC; no sobreescribe archivos.'
    def add_arguments(self, parser):
        parser.add_argument('event', help='ID o slug del evento fuente')
        parser.add_argument('file')
    def handle(self, *args, **options):
        try:
            value = options['event']
            event = Event.objects.get(**({'pk':int(value)} if value.isdecimal() else {'slug':value}))
            payload = signed_snapshot(event)
            with Path(options['file']).open('x', encoding='utf-8') as stream:
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
        except (Event.DoesNotExist, ValidationError, OSError) as exc:
            raise CommandError('No se exportó. Revisa evento, clave y archivo de destino nuevo.') from exc
        self.stdout.write('Snapshot firmado exportado, sin datos del comprador.')

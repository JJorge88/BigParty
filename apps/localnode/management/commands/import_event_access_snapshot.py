import json
from pathlib import Path
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from apps.localnode.snapshots import import_snapshot, MAX_SNAPSHOT_BYTES


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError('Clave duplicada')
        result[key] = value
    return result

class Command(BaseCommand):
    help = 'Importa un snapshot firmado y conserva usos/cancelaciones locales.'
    def add_arguments(self, parser):
        parser.add_argument('file')
    def handle(self, *args, **options):
        from apps.core.ops.recovery import status
        if status()["active"]:raise CommandError("RECOVERY_MODE")
        try:
            with Path(options['file']).open('rb') as stream:
                raw = stream.read(MAX_SNAPSHOT_BYTES+1)
            if len(raw) > MAX_SNAPSHOT_BYTES: raise ValueError('Archivo demasiado grande')
            data = json.loads(raw, object_pairs_hook=no_duplicates)
            snapshot, changed = import_snapshot(data)
        except (OSError, ValueError, TypeError, RecursionError, ValidationError) as exc:
            raise CommandError('Importación rechazada. Revisa modo, identidad, formato, versión, fuente y firma.') from exc
        self.stdout.write(f'Snapshot {"importado" if changed else "ya cargado"}: {snapshot.tickets.count()} entradas.')

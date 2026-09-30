import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from django.conf import settings
from django.core.management.base import CommandError


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.writing-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, sort_keys=True, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name == "posix":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def private_root(value):
    if not value or not Path(value).is_absolute():
        raise CommandError('Configura una carpeta privada absoluta.')
    path = Path(value).resolve()
    forbidden = [Path(settings.BASE_DIR), Path(settings.MEDIA_ROOT), Path(settings.STATIC_ROOT),
                 Path(settings.RESERVATION_PROOF_ROOT), Path(settings.EVENT_PROOF_ROOT)]
    for root in forbidden:
        root = root.resolve()
        if path == root or path.is_relative_to(root) or root.is_relative_to(path):
            raise CommandError('La carpeta operativa debe estar separada del proyecto, static, media y comprobantes.')
    return path


def digest_file(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def disk_free(path):
    path = Path(path)
    while not path.exists():
        path = path.parent
    return shutil.disk_usage(path).free


def require_space(path, required=0):
    if disk_free(path) < required + settings.MIN_FREE_DISK_GB * 1024 ** 3:
        raise CommandError('DISK_SPACE_LOW: espacio libre insuficiente; no se eliminaron backups.')

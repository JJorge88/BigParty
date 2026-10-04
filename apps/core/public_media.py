"""Read-only delivery for explicitly public uploaded media."""
import mimetypes
from pathlib import Path

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.http import FileResponse, Http404
from django.utils._os import safe_join
from django.views.decorators.http import require_GET


@require_GET
def serve(request, path):
    try:
        target = Path(safe_join(settings.MEDIA_ROOT, path))
    except SuspiciousFileOperation as error:
        raise Http404 from error
    if not target.is_file():
        raise Http404
    content_type = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
    response = FileResponse(target.open('rb'), content_type=content_type)
    response['Cache-Control'] = 'public, max-age=86400'
    response['X-Content-Type-Options'] = 'nosniff'
    return response

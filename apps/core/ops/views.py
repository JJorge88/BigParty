import json
from datetime import datetime,timezone
from pathlib import Path
from django.conf import settings
from django.views.decorators.http import require_GET
from apps.operations.management import security
from apps.operations.management.views import page
from .backups import read_manifest
from .files import digest_file
from .recovery import status

@require_GET
@security.required
def backup_status(request):
    security.require(request.user,'core.view_configuration')
    rows=[]
    if settings.BACKUP_ROOT:
        for path in (Path(settings.BACKUP_ROOT)/'manifests').glob('*.json'):
            if path.name.endswith('.verified.json'):continue
            try:
                row=read_manifest(path)
                row['old']=(datetime.now(timezone.utc)-datetime.fromisoformat(row['created_at'])).total_seconds()>settings.BACKUP_MAX_AGE_HOURS*3600
                receipt=path.with_suffix('.verified.json')
                verification=json.loads(receipt.read_text()) if receipt.exists() else {}
                row['verified_at']=verification.get('verified_at') if verification.get('manifest_sha256')==digest_file(path) else None
                rows.append(row)
            except (ValueError,OSError,KeyError):continue
            except Exception:continue  # An unreadable manifest is never shown as a successful verification.
    rows.sort(key=lambda row:row['created_at'],reverse=True)
    latest=[]
    for kind in ('database','media','full'):
        row=next((r for r in rows if r['kind']==kind),{'kind':kind,'status':'Sin backup registrado'})
        try:
            attempt=json.loads((Path(settings.BACKUP_ROOT)/'logs'/('last-'+kind+'.json')).read_text())
            row['last_failed']=attempt.get('status')=='FAILED'
        except (OSError,ValueError,TypeError):pass
        latest.append(row)
    return page(request,'backups',{'backups':latest,'recovery':status(),'configured':bool(settings.BACKUP_ROOT)},section='configuracion')

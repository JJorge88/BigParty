"""Conservative tracked-file scan. Reports locations, never matched secret values."""
import re
import subprocess
from pathlib import Path
from django.conf import settings


def scan():
    result=subprocess.run(['git','ls-files','-z'],cwd=settings.BASE_DIR,check=True,capture_output=True)
    findings=[]
    configured=[getattr(settings,name,'') for name in ('SECRET_KEY','SYNC_SHARED_SECRET','ACCESS_SNAPSHOT_SIGNING_KEY','SYNC_SHARED_SECRET_PREVIOUS')]
    patterns=[re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
              re.compile(rb'(?:AKIA|ASIA)[A-Z0-9]{16}'),re.compile(rb'gh[pousr]_[A-Za-z0-9]{30,}')]
    for name in result.stdout.decode().split('\0'):
        if not name:continue
        path=Path(settings.BASE_DIR)/name
        if not path.is_file():continue
        if (path.name.startswith('.env') and not path.name.endswith('.example')) or path.suffix.lower() in ('.key','.pem','.p12','.pfx','.dump','.backup'):
            findings.append((name,'PRIVATE_FILE_TRACKED'))
        if path.stat().st_size>10*1024*1024:continue
        data=path.read_bytes()
        if any(p.search(data) for p in patterns):findings.append((name,'SECRET_PATTERN'))
        if any(len(value)>=20 and value.encode() in data for value in configured):findings.append((name,'CONFIGURED_SECRET_PRESENT'))
    return findings

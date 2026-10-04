"""Install the application's backup job; no credentials are copied into the plist."""
from pathlib import Path
import os
import plistlib
import subprocess
import sys
import shutil

project = Path(__file__).resolve().parents[2]
base = Path.home() / 'Library/Application Support/BigParty'
base.mkdir(parents=True, exist_ok=True, mode=0o700)
runtime = base / 'runtime'
if not runtime.exists(): shutil.copytree('/tmp/bigparty-venue-deps', runtime)
label = 'com.bigparty.pilot.backup'
plist = Path.home() / 'Library/LaunchAgents' / (label + '.plist')
plist.parent.mkdir(parents=True, exist_ok=True)
config = {'Label': label, 'ProgramArguments': [str(project / '.venv/bin/python'), str(project / 'manage.py'), 'backup_if_due'],
          'WorkingDirectory': str(project), 'RunAtLoad': True, 'StartInterval': 1800,
          'EnvironmentVariables': {'PYTHONPATH': str(runtime), 'PYTHONPYCACHEPREFIX': str(base / 'pycache'), 'DB_NAME': 'bigparty_pilot', 'BIGPARTY_ENV_FILE': str(project / '.env.pilot')},
          'StandardOutPath': str(base / 'backup-scheduler.log'), 'StandardErrorPath': str(base / 'backup-scheduler-error.log')}
plist.write_bytes(plistlib.dumps(config)); plist.chmod(0o600)
subprocess.run(['launchctl', 'bootout', f'gui/{os.getuid()}/{label}'], capture_output=True)
subprocess.run(['launchctl', 'bootstrap', f'gui/{os.getuid()}', str(plist)], check=True)
print('Respaldo automático instalado: revisa cada 30 minutos y respalda cada 4 horas mientras la sesión de macOS esté activa.')

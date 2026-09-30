#!/bin/sh
set -eu
# EnvironmentFile is loaded by systemd, never sourced as shell code here.
PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
cd "$PROJECT_ROOT"
PYTHON_EXE="${BIGPARTY_PYTHON:-$PROJECT_ROOT/.venv/bin/python}"
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.prod}"
export DEPLOYMENT_MODE="${DEPLOYMENT_MODE:-cloud}"
exec "$PYTHON_EXE" manage.py backup_full "$@"

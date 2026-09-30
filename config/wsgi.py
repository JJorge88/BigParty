import os
from pathlib import Path

from django.core.wsgi import get_wsgi_application
from dotenv import load_dotenv

load_dotenv(os.environ.get("BIGPARTY_ENV_FILE", Path(__file__).resolve().parent.parent / ".env"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local_node" if os.environ.get("DEPLOYMENT_MODE") == "local_node" else "config.settings.prod")
application = get_wsgi_application()

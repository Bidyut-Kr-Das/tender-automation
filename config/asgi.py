import os
from pathlib import Path

from django.core.asgi import get_asgi_application
from dotenv import load_dotenv

# Load .env before choosing the settings module so DJANGO_SETTINGS_MODULE there takes effect.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# ponytail: sync HTTP only via ASGI, add ProtocolTypeRouter + channels when websocket needed
application = get_asgi_application()

"""Settings for automation-v2 (DJANGO_SETTINGS_MODULE=config.settings_v2).

v2 never touches the legacy DB: its only database is AUTOMATION_V2_DATABASE_URL,
which holds the webhooks table.
"""
from .settings import *  # noqa: F401,F403
from .settings import INSTALLED_APPS, os, dj_database_url

DATABASES = {
    "default": dj_database_url.parse(os.environ["AUTOMATION_V2_DATABASE_URL"], conn_max_age=600)
}

# v2 is independent of the legacy tender_search app.
INSTALLED_APPS = [app for app in INSTALLED_APPS if app != "tender_search"] + ["automation_v2"]
ROOT_URLCONF = "automation_v2.urls"

V2_TASKS_QUEUE = os.getenv("V2_TASKS_QUEUE", "automation-v2:tasks")
V2_PARSING_QUEUE = os.getenv("V2_PARSING_QUEUE", "automation-v2:parsing")

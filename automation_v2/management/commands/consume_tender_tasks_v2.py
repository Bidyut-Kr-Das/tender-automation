from django.conf import settings
from django.core.management.base import BaseCommand

from automation_v2.consume import serve
from automation_v2.fetch import FETCHERS
from automation_v2.schemas import fetch_adapter


class Command(BaseCommand):
    help = "v2: download tender files to S3 and emit file.fetched_* webhooks (no DB)"

    def handle(self, *args, **options):
        serve(settings.V2_TASKS_QUEUE, "file.fetched", fetch_adapter, FETCHERS)

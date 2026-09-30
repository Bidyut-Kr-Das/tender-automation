from django.conf import settings
from django.core.management.base import BaseCommand

from automation_v2.consume import serve
from automation_v2.parse import PARSERS
from automation_v2.schemas import parse_adapter


class Command(BaseCommand):
    help = "v2: parse tender files from file_link and emit file.parsed_* webhooks (no DB)"

    def handle(self, *args, **options):
        serve(settings.V2_PARSING_QUEUE, "file.parsed", parse_adapter, PARSERS)

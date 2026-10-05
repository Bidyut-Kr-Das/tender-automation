"""Webhook registration API and page. See docs/webhooks-implementation-guide.md §6.

ponytail: no auth, internal network only. Anyone who can reach it can read secrets;
put it behind auth (e.g. IsAdminUser) before exposing it.
"""
import threading
from pathlib import Path

from django.core.validators import URLValidator
from django.http import FileResponse
from rest_framework import serializers, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from .events import WEBHOOK_EVENTS
from .models import Webhook, new_webhook_secret
from .sync_result import parse_sources, run as run_sync

PAGE = Path(__file__).with_name("webhooks.html")


class WebhookSerializer(serializers.ModelSerializer):
    name = serializers.CharField(max_length=100, trim_whitespace=True)
    url = serializers.CharField(validators=[URLValidator(schemes=["http", "https"])])
    events = serializers.ListField(child=serializers.ChoiceField(choices=list(WEBHOOK_EVENTS)), min_length=1)

    class Meta:
        model = Webhook
        fields = ["id", "name", "url", "client_id", "secret", "events", "is_active", "created_at", "updated_at"]
        read_only_fields = ["client_id", "secret", "created_at", "updated_at"]

    def validate_events(self, value):
        return list(dict.fromkeys(value))  # de-duplicate, keep order


class WebhookViewSet(viewsets.ModelViewSet):
    queryset = Webhook.objects.all()
    serializer_class = WebhookSerializer
    http_method_names = ["get", "post", "patch", "delete"]

    @action(detail=True, methods=["post"], url_path="rotate-secret")
    def rotate_secret(self, request, pk=None):
        webhook = self.get_object()
        webhook.secret = new_webhook_secret()
        webhook.save(update_fields=["secret", "updated_at"])
        return Response(self.get_serializer(webhook).data)


@api_view(["POST"])
def sync_result(request):
    """Start a result scrape; rows arrive later as result.synced_* events to the client's webhook."""
    client_id = request.data.get("client_id") or request.data.get("clientId")
    if not client_id:
        return Response({"error": "client_id is required"}, status=400)
    if not Webhook.objects.filter(client_id=client_id).exists():
        return Response({"error": f"No webhook with client_id {client_id!r}"}, status=404)
    raw = next((request.data[k] for k in ("type", "types", "source") if request.data.get(k) is not None), None)
    sources = parse_sources(raw)
    # ponytail: in-process thread, lost if the container restarts mid-scrape; move to a queue job if that matters
    threading.Thread(target=run_sync, args=(client_id, sources), daemon=True).start()
    return Response({"accepted": True, "client_id": client_id, "sources": sources}, status=202)


@api_view(["GET"])
def webhook_events(request):
    return Response([{"name": n, "description": d} for n, d in WEBHOOK_EVENTS.items()])


def webhooks_page(request):
    # Served as a plain file, not a template: the page is static HTML + JS.
    return FileResponse(PAGE.open("rb"), content_type="text/html")

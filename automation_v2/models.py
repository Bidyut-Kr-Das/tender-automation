import secrets

from django.contrib.postgres.fields import ArrayField
from django.db import models


def new_client_id() -> str:
    return f"whk_{secrets.token_hex(8)}"


def new_webhook_secret() -> str:
    return f"whsec_{secrets.token_urlsafe(32)}"


class Webhook(models.Model):
    name = models.CharField(max_length=100)
    url = models.TextField()
    client_id = models.CharField(max_length=40, unique=True, default=new_client_id)  # unique => indexed
    # Plaintext on purpose: HMAC signing needs the raw secret.
    secret = models.CharField(max_length=100, default=new_webhook_secret)
    events = ArrayField(models.TextField(), default=list)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "webhooks"
        ordering = ["-id"]

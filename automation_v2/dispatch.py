"""Worker-level webhook dispatch. See docs/webhooks-implementation-guide.md §8.

Wrap each job in `job_events(base, client_id, **ids)`: however the block exits,
exactly one `<base>_success` / `<base>_failed` event is sent. `emit` never raises.

Delivery: one immediate attempt. If it fails with a network error, timeout, 5xx or 429,
the event goes to DELAY_QUEUE; after RETRY_DELAY_S RabbitMQ dead-letters it into
RETRY_QUEUE, where `consume_webhook_retry_v2` sends it again. After MAX_RETRIES
failed retries it is parked in DEAD_QUEUE for inspection or manual replay.
"""
import hashlib
import hmac
import json
import logging
import time
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from .events import WEBHOOK_EVENTS

logger = logging.getLogger(__name__)

TIMEOUT_S = 10
RETRY_DELAY_S = 300  # 5 min between retries
MAX_RETRIES = 12     # 12 x 5 min = 1 h, then DEAD_QUEUE
DELAY_QUEUE = "automation-v2:webhooks:delay"  # holding pen with a TTL; expired messages move to RETRY_QUEUE
RETRY_QUEUE = "automation-v2:webhooks:retry"
DEAD_QUEUE = "automation-v2:webhooks:dead"


class Outcome:
    def __init__(self, ids: dict):
        self.ids = ids               # identifiers copied into data (type, referenceNo)
        self.ok: bool | None = None  # None = not decided yet
        self.result = None           # may be set early as a partial result
        self.error: str | None = None

    def succeed(self, result=None) -> None:
        self.ok, self.result, self.error = True, result, None

    def fail(self, error: str, result=None) -> None:
        self.ok, self.result, self.error = False, result, error


@contextmanager
def job_events(base: str, client_id: str | None, **ids):
    """Emit <base>_success / <base>_failed to client_id when the block exits. Exceptions are re-raised."""
    outcome = Outcome(ids)
    try:
        yield outcome
    except BaseException as e:
        outcome.fail(f"{type(e).__name__}: {e}", outcome.result)
        raise
    finally:
        if outcome.ok is None:
            outcome.fail("job ended without a result", outcome.result)
        emit(client_id, f"{base}_{'success' if outcome.ok else 'failed'}",
             {**outcome.ids, "result": outcome.result, "error": outcome.error})


def client_id_from(payload: dict) -> str | None:
    return payload.get("client_id") or payload.get("clientId") or None


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def _subscribers(client_id: str, event: str) -> list[tuple[str, str, str]]:
    from django.db import close_old_connections
    from .models import Webhook  # lazy import keeps the module importable before apps are ready

    close_old_connections()  # long jobs can leave the connection stale
    rows = Webhook.objects.filter(client_id=client_id, is_active=True, events__contains=[event])
    return [(w.url, w.client_id, w.secret) for w in rows]


def declare_queues(ch) -> None:
    ch.queue_declare(queue=RETRY_QUEUE, durable=True)
    ch.queue_declare(queue=DEAD_QUEUE, durable=True)
    ch.queue_declare(queue=DELAY_QUEUE, durable=True, arguments={
        "x-message-ttl": RETRY_DELAY_S * 1000,
        "x-dead-letter-exchange": "",
        "x-dead-letter-routing-key": RETRY_QUEUE,
    })


def _publish(queue: str, msg: dict) -> None:
    import pika
    from django.conf import settings

    conn = pika.BlockingConnection(pika.URLParameters(settings.RABBITMQ_URL))
    try:
        ch = conn.channel()
        declare_queues(ch)
        ch.basic_publish("", queue, json.dumps(msg), pika.BasicProperties(delivery_mode=2, content_type="application/json"))
    finally:
        conn.close()


def _post(url: str, headers: dict, body: bytes) -> str | None:
    """One attempt. Returns None when done (delivered, or rejected with a 4xx), else the error to retry on."""
    event = headers["X-Webhook-Event"]
    try:
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            logger.info("Webhook sent event=%s id=%s url=%s status=%s", event, headers["X-Webhook-Id"], url, resp.status)
            return None
    except urllib.error.HTTPError as e:
        if e.code < 500 and e.code != 429:   # receiver rejected it: retrying won't help
            logger.warning("Webhook rejected event=%s url=%s status=%s", event, url, e.code)
            return None
        err = f"HTTP {e.code}"
    except Exception as e:                   # network error / timeout
        err = str(e)
    logger.warning("Webhook delivery failed event=%s id=%s url=%s error=%s", event, headers["X-Webhook-Id"], url, err)
    return err


def _deliver(client_id: str, event: str, event_id: str, body: bytes, attempt: int) -> None:
    """Send to the current subscription (so pause, delete and secret rotation apply to retries too).
    `attempt` 0 is the first send; a failure queues attempt+1, or parks it once MAX_RETRIES is used up."""
    subscribers = _subscribers(client_id, event)
    if not subscribers:
        logger.info("No active subscription client_id=%s event=%s id=%s", client_id, event, event_id)
        return
    for url, cid, secret in subscribers:
        timestamp = str(int(time.time()))
        err = _post(url, {
            "Content-Type": "application/json",
            "User-Agent": "tender-automation-webhooks",
            "X-Webhook-Id": event_id,
            "X-Webhook-Event": event,
            "X-Webhook-Client-Id": cid,
            "X-Webhook-Timestamp": timestamp,
            "X-Webhook-Signature": sign(secret, timestamp, body),
        }, body)
        if err is None:
            continue
        queue = DELAY_QUEUE if attempt < MAX_RETRIES else DEAD_QUEUE
        msg = {"client_id": cid, "event": event, "id": event_id, "body": body.decode(), "attempt": attempt + 1, "error": err}
        try:
            _publish(queue, msg)
            logger.info("Webhook queued to %s event=%s id=%s attempt=%s", queue, event, event_id, attempt + 1)
        except Exception:
            logger.exception("Webhook retry enqueue failed, event dropped event=%s id=%s", event, event_id)


def redeliver(msg: dict) -> None:
    """Retry one queued event (a message from RETRY_QUEUE)."""
    _deliver(msg["client_id"], msg["event"], msg["id"], msg["body"].encode(), msg["attempt"])


def emit(client_id: str | None, event: str, data: dict) -> None:
    """Send one event to the job's webhook if it is active and subscribed. Never raises."""
    try:
        if event not in WEBHOOK_EVENTS:
            raise ValueError(f"unknown webhook event {event!r}")
        if not client_id:
            logger.info("No client_id on job, webhook skipped event=%s", event)
            return
        event_id = f"evt_{uuid.uuid4().hex}"
        body = json.dumps(
            {"id": event_id, "event": event, "created_at": datetime.now(timezone.utc).isoformat(), "data": data},
            default=str,   # datetimes, UUIDs, Decimals -> strings instead of crashing
        ).encode()
        _deliver(client_id, event, event_id, body, attempt=0)
    except Exception:
        logger.exception("Webhook emit failed event=%s", event)

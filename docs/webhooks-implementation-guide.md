# Webhooks: Architecture and Implementation Guide

This guide describes the webhook feature built in **tender-agent** and explains how to build the same feature in another codebase. It is written for an engineer or coding agent working in a **Django** project with its own workers (Celery, RabbitMQ consumers, management commands, and so on).

tender-agent itself uses FastAPI, SQLModel, Alembic and pika workers running LangGraph graphs. The file references below point there. The Django snippets show the same design in Django idioms. Copy the design and the contracts exactly; adapt the code to your framework.

---

## 1. Overview

The feature has two halves.

**Registration.** An operator registers an external endpoint in a small UI. Registration produces:

- a **client ID** (`whk_…`), public, which identifies the receiver
- a **secret** (`whsec_…`), private, which is used to sign every request
- a list of **events** the endpoint wants to receive

**Dispatch.** Each background job is wrapped in a context manager. However the job ends — success, a failure status, an exception anywhere in the pipeline, or an early `return` — **exactly one** event is sent: `<base>_success` or `<base>_failed`. The event goes **only** to the webhook whose client ID came with the job, and only if that webhook is active and subscribed to the event. Each request is signed with HMAC-SHA256.

The feature is outbound only. This application never receives webhooks; it calls other systems.

### Why worker-level and not a pipeline step

The first version sent webhooks from a node at the end of the LangGraph pipeline. That node only runs when the flow reaches it. A crash, a raised exception, or an early exit in the worker skipped it, so the receiver never heard about the failure. Moving dispatch up to the worker, around the whole job, means every exit path sends exactly one event. That is the core idea of this guide.

### Glossary

| Term | Meaning |
|---|---|
| Client | An external system that receives events. It is identified by `client_id`. |
| Webhook | One registered endpoint: URL, client ID, secret, subscribed events and an active flag. |
| Event | An exact string such as `relevance.analyzed_failed`. Receivers match on it, so it must never change. |
| Event base | The event name without its suffix, e.g. `relevance.analyzed`. A worker picks the base; the outcome picks `_success` or `_failed`. |
| Outcome | The object a job fills in: `succeed(result)` or `fail(error, partial_result)`. |

---

## 2. Architecture

```
 REGISTRATION                                   DISPATCH
 ────────────                                   ────────
 Operator                                       Job publisher (another service)
    │                                              │  job payload includes "client_id"
    ▼                                              ▼
 /webhooks page (static HTML + JS)              Queue (RabbitMQ / Celery broker)
    │  fetch()                                     │
    ▼                                              ▼
 REST API  /api/webhooks/*                      Worker handler
    │  validates events against constant           │
    ▼                                              │  with job_events(base, client_id, **ids) as outcome:
 ┌───────────────────────────┐                     │      validate job
 │ webhooks table            │◄────────────────────┤      run pipeline
 │ client_id (unique)        │  SELECT url,        │      outcome.succeed(...) / outcome.fail(...)
 │ secret                    │  client_id, secret  │  (exception / early exit also handled)
 │ events[]                  │  WHERE client_id=?  │
 │ is_active                 │  AND is_active      ▼
 └───────────────────────────┘  AND ? = ANY(events)  emit(client_id, "<base>_<success|failed>", data)
                                                   │  never raises
                                                   ▼
                                                POST JSON, HMAC-signed headers
                                                3 attempts, 10 s timeout
                                                   │
                                                   ▼
                                                Receiver endpoint (verifies signature)
```

Only three things tie the two halves together:

1. the `webhooks` table
2. the event constant
3. the `client_id` that the job publisher puts in each job payload

---

## 3. Reference implementation map (tender-agent)

| File | Role |
|---|---|
| `core/webhook_events.py` | **Single source of truth** for event names and descriptions (`WEBHOOK_EVENTS` dict). |
| `core/webhook_dispatch.py` | Dispatch core: `Outcome`, `job_events`, `emit`, `sign`, `_post`, `_subscribers`, `client_id_from`. |
| `database/models.py` | `Webhook` table model, plus `new_client_id()` and `new_webhook_secret()`. |
| `alembic/versions/7b1e9c2a4f60_add_webhooks.py` | Migration that creates the `webhooks` table and the unique index on `client_id`. |
| `api/main.py` (bottom section, "Webhook registration") | REST endpoints and the route serving the page. |
| `api/static/webhooks.html` | Complete registration UI in one file: vanilla JS, no build step. |
| `worker/ingestion_worker.py` | `document.ingested`: one event per job, forwards `client_id` to the intelligence job. |
| `worker/intelligence_worker.py` | `intelligence.completed`: a partial report counts as success. |
| `worker/relevance_worker.py` | `relevance.analyzed` and `relevance.feedback`: the base is chosen from `payload_type`; `client_id` is stripped from `extra`. |
| `intelligence/graph.py`, `relevance/graph.py` | The old webhook nodes, commented out and kept for rollback. |
| `intelligence/nodes/send_webhook.py`, `relevance/nodes/webhook.py` | The old node implementations, unused and kept for reference. |
| `tests/test_webhook_dispatch.py` | Dispatcher self-check. Needs no DB; uses a local HTTP receiver. |
| `tests/test_webhooks.py` | Registration API self-check. Needs a DB. |

---

## 4. Event catalogue

### Naming rule

```
<domain>.<action>_success
<domain>.<action>_failed
```

Every job type has exactly two events, which share a base. The suffix is literally `_success` or `_failed`.

### Source of truth

`core/webhook_events.py`:

```python
"""Events a registered webhook can subscribe to.

Receivers match on these exact names, so never rename one. Add new events here;
the API validation and the /webhooks UI both read from this dict.
"""

WEBHOOK_EVENTS: dict[str, str] = {
    "document.ingested_success": "Document parsed and stored",
    "document.ingested_failed": "Document could not be parsed",
    "intelligence.completed_success": "Tender report generated",
    "intelligence.completed_failed": "Tender report could not be generated",
    "relevance.analyzed_success": "Relevance verdict produced",
    "relevance.analyzed_failed": "Relevance analysis failed",
    "relevance.feedback_success": "Feedback recorded",
    "relevance.feedback_failed": "Feedback could not be recorded",
}
```

Three things read this dict:

- the API validation, which rejects unknown events with 422
- the `GET /api/webhooks/events` endpoint, which the UI uses to build its event table
- `emit()`, which refuses an unknown event and logs it

The UI has **no hardcoded events**.

### Adding an event

1. Add both `<base>_success` and `<base>_failed` to the constant, each with a short description.
2. Wrap the job's worker in `job_events("<base>", client_id, ...)`. See section 11.
3. Nothing else is needed. The UI and the validation pick up the new events automatically.

Never rename or remove an event that receivers already use. Add a new one and retire the old one gradually.

---

## 5. Data model

### Fields

| Field | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `name` | varchar(100) | Human label, e.g. "CRM sync". |
| `url` | text | Target endpoint, http or https. |
| `client_id` | varchar(40), **unique, indexed** | `"whk_" + secrets.token_hex(8)`. Public identifier; sent in `X-Webhook-Client-Id`. |
| `secret` | varchar(100) | `"whsec_" + secrets.token_urlsafe(32)`. **Stored in plaintext on purpose:** HMAC signing needs the raw secret, so hashing it like a password would not work. |
| `events` | `text[]` (Postgres array) | Subscribed event names. An array allows the `? = ANY(events)` lookup. |
| `is_active` | bool, default true | A paused webhook receives nothing. |
| `created_at`, `updated_at` | timestamp | Server defaults; `updated_at` changes on update. |

tender-agent version (`database/models.py`):

```python
def new_client_id() -> str:
    return f"whk_{secrets.token_hex(8)}"


def new_webhook_secret() -> str:
    return f"whsec_{secrets.token_urlsafe(32)}"


class Webhook(SQLModel, table=True):
    __tablename__ = "webhooks"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=100)
    url: str = Field(sa_type=Text)
    client_id: str = Field(default_factory=new_client_id, unique=True, index=True, max_length=40)
    # Plaintext on purpose: the dispatcher needs it to sign payloads (HMAC).
    secret: str = Field(default_factory=new_webhook_secret, max_length=100)
    events: list[str] = Field(default_factory=list, sa_column=Column(ARRAY(Text), nullable=False))
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column_kwargs={"server_default": func.now()})
    updated_at: datetime = Field(default_factory=datetime.utcnow,
                                 sa_column_kwargs={"server_default": func.now(), "onupdate": func.now()})
```

### Django equivalent

```python
# webhooks/models.py
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
```

Run `python manage.py makemigrations webhooks && python manage.py migrate`.

If the database is **not Postgres**, use `events = models.JSONField(default=list)`. The subscriber query in section 8 then needs a fallback: filter by `client_id` and `is_active` in SQL, then check `event in w.events` in Python. That is cheap, because there is at most one row per client ID.

---

## 6. Registration API

| Method | Path | Body | Response |
|---|---|---|---|
| `GET` | `/webhooks` | – | The HTML page. |
| `GET` | `/api/webhooks/events` | – | `[{"name": "...", "description": "..."}]`, in constant order. |
| `GET` | `/api/webhooks` | – | List of webhooks, newest first, **including the secret**. |
| `POST` | `/api/webhooks` | `{name, url, events[]}` | `201` with the created webhook, including `client_id` and `secret`. |
| `PATCH` | `/api/webhooks/{id}` | Any of `{name, url, events[], is_active}` | The updated webhook. |
| `POST` | `/api/webhooks/{id}/rotate-secret` | – | The webhook with a new secret; the client ID is unchanged. |
| `DELETE` | `/api/webhooks/{id}` | – | `204`. |

Webhook response shape:

```json
{
  "id": 3, "name": "CRM sync", "url": "https://crm.example.com/hooks/tender",
  "client_id": "whk_3f9a21c0b7e4d5a6", "secret": "whsec_…",
  "events": ["relevance.analyzed_success", "relevance.analyzed_failed"],
  "is_active": true, "created_at": "…", "updated_at": "…"
}
```

### Validation rules

- `name`: 1–100 characters, trimmed.
- `url`: an absolute http or https URL.
- `events`: at least one entry, every entry a key of `WEBHOOK_EVENTS`, duplicates removed with the order kept.
- An unknown `id` returns `404`. Invalid input returns `422` (or `400` in Django) with a per-field error. The UI shows it under the matching field.

tender-agent uses Pydantic (`api/main.py`): `events: list[Literal[tuple(WEBHOOK_EVENTS)]] = Field(..., min_length=1)`, `url: HttpUrl`.

### Django version (DRF)

```python
# webhooks/serializers.py
from rest_framework import serializers
from .events import WEBHOOK_EVENTS
from .models import Webhook


class WebhookSerializer(serializers.ModelSerializer):
    url = serializers.URLField()
    events = serializers.ListField(
        child=serializers.ChoiceField(choices=list(WEBHOOK_EVENTS)), min_length=1
    )

    class Meta:
        model = Webhook
        fields = ["id", "name", "url", "client_id", "secret", "events", "is_active", "created_at", "updated_at"]
        read_only_fields = ["client_id", "secret", "created_at", "updated_at"]

    def validate_events(self, value):
        return list(dict.fromkeys(value))  # de-duplicate, keep order

    def validate_name(self, value):
        return value.strip()
```

```python
# webhooks/views.py
from django.shortcuts import render
from rest_framework import viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from .events import WEBHOOK_EVENTS
from .models import Webhook, new_webhook_secret
from .serializers import WebhookSerializer


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


@api_view(["GET"])
def webhook_events(request):
    return Response([{"name": n, "description": d} for n, d in WEBHOOK_EVENTS.items()])


def webhooks_page(request):
    return render(request, "webhooks/webhooks.html")
```

```python
# webhooks/urls.py
from django.urls import path
from rest_framework.routers import SimpleRouter
from . import views

router = SimpleRouter(trailing_slash=False)
router.register("api/webhooks", views.WebhookViewSet)

urlpatterns = [
    path("api/webhooks/events", views.webhook_events),  # must come before the router's detail route
    path("webhooks", views.webhooks_page),
    *router.urls,
]
```

The UI sends JSON with `fetch` and reads `detail` from error responses. If you use DRF, either return errors as `{"detail": [{"loc": ["body", "<field>"], "msg": "..."}]}`, which is what the page's inline field errors expect, or change the small `api()` and submit handlers in the page to read DRF's `{"field": ["msg"]}` shape.

For CSRF, either exempt these API views (internal network only) or send the CSRF token from the page. See section 14 on auth.

---

## 7. Registration UI (UX spec)

The reference is `api/static/webhooks.html`: one file with inline CSS and JS and no build step. It talks to the API only through the endpoints in section 6, so it can be copied into a Django template almost as-is. Keep the endpoint paths or edit the `API` constant at the top of the script.

### Main page

- Header with the title "Webhooks", a one-line description, and a primary **Register webhook** button.
- A single table with these columns:
  - **Name and endpoint**: the name in bold with the URL in monospace below it, truncated with a tooltip.
  - **Client ID**: in monospace, with a copy icon button.
  - **Events**: the exact event names as small monospace tags. The first two are shown, then "+N more", which lists the rest on hover.
  - **Active**: a switch. The row updates at once, reverts and shows a toast if the request fails, and fades when paused.
  - **⋯ row menu**, built on the native `popover` attribute, with arrow-key navigation: **Edit**, **Show credentials**, **Rotate secret**, **Delete**.
- Page states:
  - **Loading**: skeleton rows.
  - **Error**: a message with a **Try again** button.
  - **Empty**: "No webhooks yet. Register an endpoint to get notified when agents finish." with the primary button.
- Under 640 px, table rows stack into cards.

### Register / edit dialog (native `<dialog>`)

- **Name** and **Endpoint URL** fields (URL in monospace). Validation is inline under each field.
- **Events**: a single-column **table** that scrolls inside the dialog (max-height about 320 px) with a sticky header. Columns are **Event** (the exact name, monospace), **Description** (short) and **On** (a switch).
  - Switches are **red when off and green when on**, and every event starts **off** for a new webhook.
  - Clicking anywhere on a row toggles its switch.
  - Above the table: an "N of M on" counter and a **Turn all on / Turn all off** button.
  - With nothing on, submitting shows "Turn on at least one event."
  - On mobile, the description moves under the name and the header row is hidden.
- The submit button reads "Register webhook" or "Save changes", and shows "Registering…" or "Saving…" while disabled.
- The edit dialog subtitle says the client ID and secret stay the same.

### Credentials dialog

- Opens after a successful register, from **Show credentials**, and after **Rotate secret**.
- Shows the client ID with **Copy**, and the secret masked (`whsec_••••`) with **Show/Hide** and **Copy**.
- Copy buttons change to "Copied" for 1.5 s.
- A short note says to keep the secret private and rotate it if it leaks.

### Confirm dialogs

- **Rotate secret**: "Services using the old secret will stop verifying requests until they switch."
- **Delete**: "Stops receiving events and its credentials stop working. This can't be undone."

### Visual tokens

| Token | Value | Use |
|---|---|---|
| fog | `#F4F6F8` | page background |
| paper | `#FFFFFF` | surfaces |
| ink | `#17212B` | text |
| slate | `#56677A` | secondary text (AA contrast on fog) |
| line | `#DCE2E8` | borders |
| laser red | `#D7263D` | primary button, focus ring, event switch off |
| ok green | `#1E8A5A` | switch on |

Fonts are Schibsted Grotesk for the UI and JetBrains Mono for machine strings (client ID, secret, URLs, event names), both from Google Fonts. Every control has a label, keyboard focus is visible, and `prefers-reduced-motion` is respected.

---

## 8. Dispatch core

The whole feature is one module with no dependencies beyond the standard library and your ORM. The full reference is `core/webhook_dispatch.py`.

### Contract: exactly one event per job

| How the `with` block ends | Event sent | `data.error` | `data.result` |
|---|---|---|---|
| `outcome.succeed(result)` then normal exit | `<base>_success` | `null` | `result` |
| `outcome.fail(error, partial)` then exit (including `return`) | `<base>_failed` | `error` | `partial` or `null` |
| An exception raised anywhere inside | `<base>_failed` | `"<ExceptionType>: <message>"` | whatever was stored in `outcome.result` |
| Exit with no outcome set (a forgotten call or early return) | `<base>_failed` | `"job ended without a result"` | whatever was stored in `outcome.result` |

The exception is **re-raised** after the event is sent, so the worker's existing error handling (nack, Celery retry, logging) is unchanged. `emit()` **never raises**, so a webhook problem can never fail, requeue or retry a job.

### Code

```python
import hashlib, hmac, json, logging, time, urllib.error, urllib.request, uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from .events import WEBHOOK_EVENTS

logger = logging.getLogger(__name__)

TIMEOUT_S = 10
BACKOFF_S = (2, 5)  # waits between the 3 attempts


class Outcome:
    def __init__(self, ids: dict):
        self.ids = ids               # identifiers copied into data (reference_no, job_id, ...)
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


def _post(url: str, headers: dict, body: bytes) -> None:
    for attempt in range(len(BACKOFF_S) + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                logger.info("Webhook sent event=%s url=%s status=%s", headers["X-Webhook-Event"], url, resp.status)
                return
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429:   # receiver rejected it: retrying won't help
                logger.warning("Webhook rejected event=%s url=%s status=%s", headers["X-Webhook-Event"], url, e.code)
                return
            err = f"HTTP {e.code}"
        except Exception as e:                   # network error / timeout
            err = str(e)
        logger.warning("Webhook attempt %s failed event=%s url=%s error=%s",
                       attempt + 1, headers["X-Webhook-Event"], url, err)
        if attempt < len(BACKOFF_S):
            time.sleep(BACKOFF_S[attempt])


def emit(client_id: str | None, event: str, data: dict) -> None:
    """Send one event to the job's webhook if it is active and subscribed. Never raises."""
    try:
        if event not in WEBHOOK_EVENTS:
            raise ValueError(f"unknown webhook event {event!r}")
        if not client_id:
            logger.info("No client_id on job, webhook skipped event=%s", event)
            return
        subscribers = _subscribers(client_id, event)
        if not subscribers:
            logger.info("No active subscription client_id=%s event=%s", client_id, event)
            return
        event_id = f"evt_{uuid.uuid4().hex}"
        body = json.dumps(
            {"id": event_id, "event": event, "created_at": datetime.now(timezone.utc).isoformat(), "data": data},
            default=str,   # datetimes, UUIDs, Decimals -> strings instead of crashing
        ).encode()
        for url, cid, secret in subscribers:
            timestamp = str(int(time.time()))
            _post(url, {
                "Content-Type": "application/json",
                "User-Agent": "tender-agent-webhooks",
                "X-Webhook-Id": event_id,
                "X-Webhook-Event": event,
                "X-Webhook-Client-Id": cid,
                "X-Webhook-Timestamp": timestamp,
                "X-Webhook-Signature": sign(secret, timestamp, body),
            }, body)
    except Exception:
        logger.exception("Webhook emit failed event=%s", event)
```

### Subscriber lookup

tender-agent (SQLModel/SQLAlchemy):

```python
select(Webhook).where(Webhook.client_id == client_id, Webhook.is_active, Webhook.events.any(event))
```

Django:

```python
def _subscribers(client_id: str, event: str) -> list[tuple[str, str, str]]:
    from .models import Webhook  # lazy import keeps the module importable before apps are ready
    rows = Webhook.objects.filter(client_id=client_id, is_active=True, events__contains=[event])
    return [(w.url, w.client_id, w.secret) for w in rows]
```

Notes for Django workers:

- **Long-running workers** (a consumer loop or management command) should call `django.db.close_old_connections()` before the lookup, because the connection may have gone stale during a long job. Celery tasks usually handle this already through the Django integration.
- Keep `emit` synchronous inside the task unless you need otherwise. See section 14 for when to move it onto its own queue.
- If you use `requests`/`httpx` instead of `urllib`, keep the same semantics: 10 s timeout, retry only on network errors, 5xx and 429, and never raise.

---

## 9. Payload and signature spec (what receivers get)

### Request

`POST <webhook.url>`

Headers:

| Header | Example | Meaning |
|---|---|---|
| `Content-Type` | `application/json` | |
| `User-Agent` | `tender-agent-webhooks` | Use your own product name. |
| `X-Webhook-Id` | `evt_2c9f…` | Unique per event. Receivers should de-duplicate on it. |
| `X-Webhook-Event` | `relevance.analyzed_failed` | Same as `body.event`. |
| `X-Webhook-Client-Id` | `whk_3f9a21c0b7e4d5a6` | Tells the receiver which secret to use. |
| `X-Webhook-Timestamp` | `1790757600` | Unix seconds at send time. |
| `X-Webhook-Signature` | `sha256=5d1c…` | `hex(HMAC_SHA256(secret, "{timestamp}.{raw_body}"))`. |

Body (the same envelope for every event):

```json
{
  "id": "evt_2c9f0d4e8b1a4f7c9e3d2b1a0f9e8d7c",
  "event": "relevance.analyzed_failed",
  "created_at": "2026-09-30T10:00:00.123456+00:00",
  "data": {
    "reference_no": "TND-123",
    "company": "laser",
    "result": null,
    "error": "RuntimeError: qdrant timeout"
  }
}
```

- `data` holds the job identifiers passed to `job_events(...)` or added through `outcome.ids.update(...)`, plus `result` and `error`.
- On success, `error` is `null`. On failure, `result` holds the partial result, or `null`.

### Receiver verification (Python / Django view)

```python
import hashlib, hmac, json, time
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

SECRETS = {"whk_3f9a21c0b7e4d5a6": "whsec_…"}  # stored from the credentials dialog
MAX_SKEW_S = 300
seen_ids: set[str] = set()                     # use a DB/Redis table in production


@csrf_exempt
def tender_agent_webhook(request):
    client_id = request.headers.get("X-Webhook-Client-Id", "")
    timestamp = request.headers.get("X-Webhook-Timestamp", "")
    signature = request.headers.get("X-Webhook-Signature", "")
    secret = SECRETS.get(client_id)
    if not secret or not timestamp.isdigit() or abs(time.time() - int(timestamp)) > MAX_SKEW_S:
        return HttpResponse(status=401)

    raw = request.body  # verify the RAW bytes, never re-serialized JSON
    expected = "sha256=" + hmac.new(secret.encode(), f"{timestamp}.".encode() + raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return HttpResponse(status=401)

    event = json.loads(raw)
    if event["id"] in seen_ids:          # retries can deliver the same event twice
        return JsonResponse({"ok": True})
    seen_ids.add(event["id"])

    if event["event"] == "relevance.analyzed_success":
        ...  # event["data"]["result"] == {"valid": ..., "reason": ...}
    elif event["event"].endswith("_failed"):
        ...  # event["data"]["error"]
    return JsonResponse({"ok": True})
```

### Delivery semantics

- **At-least-once.** A timeout after the receiver has already processed the request causes a retry, so receivers must de-duplicate on `X-Webhook-Id`.
- **Attempts:** up to 3, with waits of 2 s and then 5 s between them. Each attempt has a 10 s timeout.
- **Retried** on network errors, timeouts, `5xx` and `429`. **Not retried** on any other `4xx`, which means the receiver rejected the request.
- Any `2xx` counts as delivered.
- There is **no persistent redelivery**. After the third failure the event is logged and dropped (see section 14).

---

## 10. Routing by `client_id`

- Every job payload must carry the receiver's `client_id`, as `client_id` or `clientId`.
- `emit` sends only when all of these hold:
  - the job has a `client_id`
  - a webhook with that client ID exists
  - that webhook is active
  - its `events` contains this exact event
- **No `client_id` means no webhook is sent.** This is logged as `No client_id on job, webhook skipped`.
- **Chained jobs must forward it.** In tender-agent, the ingestion worker publishes the follow-up intelligence job with the same `client_id` (`_publish_intelligence(..., client_id)`), so the same client also receives `intelligence.completed_*`. Apply the same rule to any job that enqueues another job.
- **Keep `client_id` out of business logic.** The relevance worker passes every unknown payload key to the pipeline as `extra`, and the feedback step embeds *all* of `extra` into the vector store. The worker therefore strips `client_id`/`clientId` from `extra` before invoking the graph. Check your own code for any place that serialises "all extra fields" of a job: it must not leak the routing key.

---

## 11. Wiring a worker

### Rules

1. Read the identifiers from the **raw** payload first (`payload.get("reference_no") or payload.get("referenceNo")`). If validation fails, the failed event still carries them.
2. **Validate inside the `with` block.** A malformed job then also sends `_failed` with the validation error.
3. After validation, overwrite the ids with the clean values: `outcome.ids.update(...)`.
4. If the job has several steps, store a **partial result early** (`outcome.result = {...}`). A crash halfway through then still reports what finished.
5. Map the pipeline's status to `succeed` or `fail` explicitly. Never assume "no exception" means success.
6. Keep ack/nack, retry and requeue logic **unchanged and separate**. `job_events` only observes the job.
7. Only JSON decoding sits outside the block. With no payload there are no ids and no client, so nothing can be sent.

### Generic template

```python
def handle(payload: dict):
    with job_events(
        "<domain>.<action>",
        client_id_from(payload),
        reference_no=payload.get("reference_no") or payload.get("referenceNo"),
    ) as outcome:
        job = MyJob.model_validate(payload)              # or a Django form / DRF serializer
        outcome.ids.update(reference_no=job.reference_no)
        result = run_pipeline(job)                       # graph.invoke / service call
        if result["status"] == "done":
            outcome.succeed(result["output"])
        else:
            outcome.fail(result.get("error") or f"status {result['status']!r}", result.get("output"))
```

### Celery version

```python
from celery import shared_task
from webhooks.dispatch import client_id_from, job_events


@shared_task(bind=True, acks_late=True)
def analyze_relevance(self, payload: dict):
    with job_events(
        "relevance.analyzed",
        client_id_from(payload),
        reference_no=payload.get("reference_no"),
        company=payload.get("company"),
    ) as outcome:
        job = RelevanceJob.model_validate(payload)
        extra = {k: v for k, v in (job.model_extra or {}).items() if k not in ("client_id", "clientId")}
        result = run_relevance(job, extra)
        if result["status"] == "analyzed":
            outcome.succeed(result["verdict"])
        else:
            outcome.fail(result.get("error") or "analysis failed", result.get("verdict"))
```

**Celery retries:** if the task uses `self.retry(...)` or `autoretry_for`, every attempt that raises sends a `_failed` event, because each attempt runs the `with` block. If the receiver should hear only about the final outcome, send `_failed` only when `self.request.retries >= self.max_retries`. To do that, wrap `job_events` in your own helper that suppresses the emit while retries remain.

### tender-agent mappings (worked examples)

| Worker | Event base | Success when | `result` | Ids in `data` |
|---|---|---|---|---|
| `worker/ingestion_worker.py` | `document.ingested` | Every file's status is not `"failed"`. **One event per job**, not per file. | `{"files": [{document_id, external_document_id, file_url, status, chunk_count, total_pages, error}]}`, including files finished before a failure | `job_id`, `reference_no`, `tender_type` |
| `worker/intelligence_worker.py` | `intelligence.completed` | `final_response["sections"]` is non-empty. A partial report is a **success**, with its `failed`/`degraded` lists inside the result. | `final_response` as an object, not a JSON string | `reference_no`, `tender_type` |
| `worker/relevance_worker.py` (`payload_type == "analysis"`) | `relevance.analyzed` | `status == "analyzed"` | `verdict` = `{valid, reason}` | `reference_no`, `company` |
| `worker/relevance_worker.py` (`payload_type == "feedback"`) | `relevance.feedback` | `status == "indexed"` | `{"vector_ids": [...]}` | `reference_no`, `company` |

Details worth copying:

- **Ingestion, multi-step partial result:**
  ```python
  files = []
  outcome.result = {"files": files}      # same list object, so it fills in as files complete
  for state in job.to_file_states():
      result = graph.invoke(state)
      files.append({...})
      if result.get("status") == "failed":
          outcome.fail(f"{state['file_url']}: {result.get('error') or 'ingestion failed'}", {"files": files})
          nack(); return                  # the early return is fine: the outcome is already set
  outcome.succeed({"files": files})
  ```
- **Intelligence, deciding success from the result:** the graph never raises on a soft failure, so the worker checks the result:
  ```python
  final = result.get("final_response") or {}
  if final.get("sections"):
      outcome.succeed(final)
  else:
      outcome.fail("; ".join(map(str, result.get("errors") or [])) or "no sections produced", final or None)
  ```
- **Relevance, choosing the base at runtime:** the event base depends on the payload's `payload_type`. It is read from the raw payload before validation. If the type is unknown, the job runs without `job_events` (there is no matching event), and validation then rejects it and nacks:
  ```python
  EVENT_BASE = {"analysis": "relevance.analyzed", "feedback": "relevance.feedback"}
  base = EVENT_BASE.get(payload.get("payload_type") or payload.get("payloadType") or payload.get("type"))
  if base is None:
      _run(ch, method, payload); return
  with job_events(base, client_id_from(payload), reference_no=..., company=...) as outcome:
      _run(ch, method, payload, outcome)
  ```

A worker with no matching event (in tender-agent, the knowledgebase worker) is left untouched.

---

## 12. Migrating from pipeline-node webhooks

If the target codebase already sends webhooks from inside a pipeline, whether a final graph node, a signal handler or a step at the end of a service:

1. Build the dispatch core and wire the workers as above.
2. **Comment out** the old call sites; do not delete them. In tender-agent:
   ```python
   # intelligence/graph.py
   # Replaced by worker-level dispatch (core/webhook_dispatch.py). Uncomment to roll back.
   # from intelligence.nodes.send_webhook import send_webhook
   ...
   # graph.add_node("send_webhook", send_webhook)
   ...
   # Rollback: restore these two edges and delete the direct edge below.
   # graph.add_edge("synthesize_final_result", "send_webhook")
   # graph.add_edge("send_webhook", END)
   graph.add_edge("synthesize_final_result", END)
   ```
   `relevance/graph.py` follows the same pattern: `analysis → END` replaces `analysis → webhook → END`.
3. Keep the old node files unchanged for reference.
4. **Rollback:** uncomment the import, the node and its edges, then delete the direct `→ END` edge.
5. Tell receivers about the format change. The old nodes sent ad-hoc bodies: the TED `PATCH` had `agentReport` as a JSON *string*, and the relevance `POST` had `{referenceNo, company, valid, reason}` to a fixed per-company URL. The new envelope is section 9's format, signed, and routed by `client_id`.

---

## 13. Testing

### Dispatcher self-check (no DB, no network)

tender-agent: `tests/test_webhook_dispatch.py`, run with `uv run python -m tests.test_webhook_dispatch`.

Approach:

- Start a local `http.server.HTTPServer(("127.0.0.1", 0), Handler)` in a daemon thread. The handler records the headers and raw body, and answers with statuses taken from a queue (default 200).
- Stub the subscriber lookup: `dispatch._subscribers = lambda client_id, event: [(URL, client_id, SECRET)] if (client_id, event) in SUBS else []`.
- Set `dispatch.BACKOFF_S = (0, 0)` so retries don't sleep.

Cases to cover:

1. `succeed()` sends `<base>_success` with `data == {**ids, "result": ..., "error": None}`.
2. The signature matches `sign(SECRET, headers["X-Webhook-Timestamp"], raw_body)`.
3. `fail()` sends `_failed` with the error and the partial result.
4. An exception inside the block sends `_failed` with `"RuntimeError: ..."` **and is re-raised**.
5. Exiting with no outcome sends `_failed` with "job ended without a result".
6. Routing sends nothing for another client's ID, a `None` client ID, or an event the client is not subscribed to.
7. A `500` then `200` sends 2 requests; a `400` sends 1.
8. An unreachable URL does not raise.
9. An unknown event name does not raise.

### Worker smoke test (no broker)

Call the real `handle_message` with:

- a fake channel object that records `basic_ack` and `basic_nack`
- a stub graph whose `invoke` returns a canned state or raises
- `dispatch.emit` monkeypatched to append to a list

In a Celery project, call the task function directly (`task.run(payload)` or `task.apply(args=[payload])`) with `emit` patched the same way.

For each worker, check:

- success
- a failed status
- an exception
- an invalid payload
- a missing `client_id`

Each should produce the right event and leave ack/nack unchanged.

### Registration API

tender-agent: `tests/test_webhooks.py` (needs a DB). It covers:

- the events endpoint matches the constant
- an unknown event, an empty event list and a bad URL each return 422
- create returns the `whk_`/`whsec_` prefixes and de-duplicates events
- patch works
- rotate changes the secret but not the client ID
- delete returns 204, and a later patch of the same ID returns 404

### End to end

1. Register a webhook pointing at a request bin (e.g. https://webhook.site) and turn on the events you are testing.
2. Publish one good job and one broken job, both with that `client_id`.
3. Confirm `_success` and `_failed` both arrive, and verify the signature with the secret.

---

## 14. Operational notes and known limits

| Topic | Current behaviour | When to change |
|---|---|---|
| Delivery runs synchronously on the worker thread | The worst case adds about 37 s per subscriber (3 × 10 s timeout plus 7 s of waits). tender-agent's RabbitMQ heartbeat is 600 s, which covers it. | Move `emit` onto its own queue or Celery task once there are many subscribers or slow receivers. |
| No delivery log or redelivery | Failed deliveries are only logged. | Add a `webhook_deliveries` table (event id, webhook, status, attempts, last error) plus a "resend" action when someone needs to audit or replay events. |
| No auth on the registration API or page | Acceptable only on an internal network. Anyone who can reach it can read secrets. | Before exposing it, put it behind the host's auth (Django `login_required` / staff-only, or DRF `IsAdminUser`). |
| Secrets stored in plaintext | Required for HMAC. | Encrypt at rest (e.g. Fernet with a key from settings) if the DB is shared. |
| Intelligence soft failure | Sends `_failed` but still **acks** the message, as before. | Only change this if the queue should also treat it as a failure. |
| `BaseException` is caught | Ctrl-C or a worker shutdown during a job sends `_failed`, then re-raises. This is deliberate: the job did not finish. | Catch `Exception` instead if shutdowns should stay silent. |
| One webhook per `client_id` | `client_id` is unique, so each job notifies at most one endpoint. | To fan out to several endpoints per client, make the job carry a list of client IDs, or add a client → webhooks relation. |

---

## 15. Implementation checklist (target codebase)

1. [ ] Create `webhooks/events.py` with a `WEBHOOK_EVENTS` dict. Give every job type both `_success` and `_failed` entries, each with a short description.
2. [ ] Add the `Webhook` model (section 5). Generate and apply the migration.
3. [ ] Add the REST endpoints and page route (section 6). Validate events against the constant, de-duplicate them, and return per-field errors.
4. [ ] Copy `api/static/webhooks.html` into a template. Check the API paths and error shape. Test register, edit, pause, rotate and delete, the empty/loading/error states, and mobile width.
5. [ ] Add the dispatch module (section 8), with the Django `_subscribers` and a lazy model import.
6. [ ] For each job type:
   - wrap the handler in `job_events(base, client_id_from(payload), **raw_ids)`
   - validate inside the block
   - call `outcome.ids.update(...)`
   - store the partial result early
   - map the status explicitly to `succeed` or `fail`
7. [ ] Forward `client_id` on every job that enqueues another job.
8. [ ] Strip `client_id`/`clientId` from any "extra fields" passed into business logic.
9. [ ] Decide Celery retry semantics (section 11): an event per attempt, or only the final one.
10. [ ] Comment out the old webhook call sites and leave rollback notes (section 12).
11. [ ] Write the dispatcher self-check and the worker smoke tests (section 13).
12. [ ] Give receivers the payload and signature spec (section 9), including the verification snippet and the idempotency rule.
13. [ ] Make sure every job publisher includes `client_id` in the payload. Without it, no webhook is sent.

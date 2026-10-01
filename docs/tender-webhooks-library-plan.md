# Plan: `tender-webhooks` verification library (Python + Node)

## Context

`automation_v2/dispatch.py` signs outbound webhooks. Today, receiving codebases copy the `verify()` snippet from
`docs/automation-v2-webhook-events.md` §7. We want one installable package per language that other codebases add as a
dependency. The signing spec then lives in one place, and every receiver verifies the same way.

Spec (from `automation_v2/dispatch.py` `sign()` and the delivery headers):

- `X-Webhook-Signature = "sha256=" + hex(HMAC_SHA256(secret, f"{timestamp}." + raw_body))`
- `X-Webhook-Timestamp` = unix seconds. Reject if `|now - ts| > 300` seconds.
- Other headers: `X-Webhook-Id`, `X-Webhook-Event`, `X-Webhook-Client-Id`.
- Body: JSON envelope `{"id", "event", "created_at", "data"}`.

Decisions:

- Languages: Python and Node.
- Distribution: install by Git URL, pinned to a tag.
- Scope: core verification only, no framework adapters.

## Repository layout

A new, separate Git repo named `tender-webhooks`. npm cannot install from a Git subdirectory, so `package.json` sits at
the repo root. uv and pip can install from a subdirectory, so the Python package goes in `python/`.

```
tender-webhooks/
  package.json          # name "tender-webhooks", main index.js, types index.d.ts, no dependencies
  index.js              # Node implementation (node:crypto only)
  index.d.ts            # hand-written types (~10 lines)
  test.js               # node:test + node:assert, reads fixtures.json
  fixtures.json         # shared test vectors: secret, timestamp, body, expected signature
  python/
    pyproject.toml      # uv_build backend, requires-python >=3.10, no dependencies
    src/tender_webhooks/__init__.py   # Python implementation (stdlib only)
    src/tender_webhooks/py.typed
    tests/test_verify.py              # plain asserts, runnable with `python -m`
  README.md             # install lines + short usage examples for Django, FastAPI, Express
```

## API (identical in both languages)

- `sign(secret, timestamp, body) -> str`
  - Same formula as `dispatch.sign`. Lets receivers write their own tests.
- `verify(body, headers, secret, tolerance=300, now=None) -> dict`
  - Returns the parsed payload.
  - Raises (Python) or throws (Node) `WebhookVerificationError` with one of these reasons:
    `missing header`, `bad timestamp`, `timestamp outside tolerance`, `bad signature`.
  - `body`: raw bytes / `Buffer` (a `str` is also accepted). It must be the raw request body, never re-serialized JSON.
    State this in the docstring and the README.
  - `headers`: any mapping. Header lookup is case-insensitive, so Django `request.headers`, Starlette headers, a plain
    dict and Node's lowercased `req.headers` all work.
  - Signature compare is constant-time: `hmac.compare_digest` in Python, `crypto.timingSafeEqual` (after a length check)
    in Node.
  - `now` exists only so tests can check stale timestamps. It defaults to the current time.
- De-duplication on `X-Webhook-Id` is left to the consumer, because it needs the consumer's own storage. The README
  shows how.

Python sketch:

```python
import hashlib, hmac, json, time


class WebhookVerificationError(Exception):
    pass


def sign(secret: str, timestamp: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def verify(body, headers, secret, tolerance=300, now=None):
    h = {k.lower(): v for k, v in headers.items()}
    ts, sig = h.get("x-webhook-timestamp"), h.get("x-webhook-signature")
    if not ts or not sig:
        raise WebhookVerificationError("missing header")
    if not ts.isdigit():
        raise WebhookVerificationError("bad timestamp")
    if abs((now or time.time()) - int(ts)) > tolerance:
        raise WebhookVerificationError("timestamp outside tolerance")
    raw = body.encode() if isinstance(body, str) else body
    if not hmac.compare_digest(sign(secret, ts, raw), sig):
        raise WebhookVerificationError("bad signature")
    return json.loads(raw)
```

## Shared fixtures

`fixtures.json` holds one valid vector, generated once with the server's real `dispatch.sign()`. It also holds failure
cases: tampered body, wrong secret, stale timestamp and missing header. Both test suites load the file and pass a fixed
`now`. This proves that Python, Node and the server agree byte-for-byte.

## Install (README)

- Python (uv): `uv add "tender-webhooks @ git+https://github.com/<org>/tender-webhooks@v0.1.0#subdirectory=python"`
- Python (pip): `pip install "git+https://github.com/<org>/tender-webhooks@v0.1.0#subdirectory=python"`
- Node: `npm install github:<org>/tender-webhooks#v0.1.0`
- Always pin to a Git tag. Create a new tag for every change.

## Scope

Separate codebase only. Nothing in `tender-automation` changes.

## Not included (add later if needed)

- Framework adapters (Django decorator, FastAPI dependency): add when two or more consumers write the same wrapper.
- Multiple secrets during rotation: the server re-signs retries with the current secret, so this is not needed now. Add
  it if consumers hit failures during a rotation.
- Publishing to PyPI or npm, and a CI release workflow: add when a consumer cannot install from Git.

## Verification

1. `cd python && uv run python -m tests.test_verify`: all asserts pass.
2. `node --test` at the repo root: all tests pass.
3. Cross-check once by hand: the valid vector in `fixtures.json` matches a signature produced by the server's
   `dispatch.sign()`. Change one body byte and confirm both languages raise `bad signature`.
4. Install check:
   - In a fresh venv, run `uv pip install "git+file:///path/to/tender-webhooks#subdirectory=python"` and confirm
     `import tender_webhooks` works.
   - In a scratch directory, run `npm install /path/to/tender-webhooks` and confirm `require("tender-webhooks")` works.

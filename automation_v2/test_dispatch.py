"""Dispatcher self-check. No DB, no network: a local HTTP receiver and a stubbed subscriber lookup.

Run: uv run python -m automation_v2.test_dispatch
"""
import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from automation_v2 import dispatch

SECRET = "whsec_test"
CLIENT = "whk_test"
received: list[tuple[dict, bytes]] = []
statuses: "queue.Queue[int]" = queue.Queue()


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        received.append((dict(self.headers), body))
        self.send_response(statuses.get_nowait() if not statuses.empty() else 200)
        self.end_headers()

    def log_message(self, *args):
        pass


server = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{server.server_port}/hook"
SUBS = {(CLIENT, e) for e in ("file.fetched_success", "file.fetched_failed", "file.parsed_failed")}
dispatch._subscribers = lambda cid, event: [(URL, cid, SECRET)] if (cid, event) in SUBS else []
published: list[tuple[str, dict]] = []  # (queue, message) instead of RabbitMQ
dispatch._publish = lambda q, msg: published.append((q, msg))


def last() -> tuple[dict, dict, bytes]:
    headers, raw = received[-1]
    return headers, json.loads(raw), raw


def main():
    global SECRET
    ids = {"type": "GEM_DOWNLOAD", "referenceNo": "GEM/2026/B/1"}

    # 1-2. success event, data shape, signature
    with dispatch.job_events("file.fetched", CLIENT, **ids) as o:
        o.succeed({"files": [{"url": "u"}]})
    h, body, raw = last()
    assert body["event"] == "file.fetched_success" and h["X-Webhook-Event"] == "file.fetched_success"
    assert body["data"] == {**ids, "result": {"files": [{"url": "u"}]}, "error": None}
    assert h["X-Webhook-Signature"] == dispatch.sign(SECRET, h["X-Webhook-Timestamp"], raw)
    assert h["X-Webhook-Client-Id"] == CLIENT and h["X-Webhook-Id"] == body["id"]

    # 3. explicit fail with partial result
    with dispatch.job_events("file.fetched", CLIENT, **ids) as o:
        o.fail("boom", {"files": []})
    _, body, _ = last()
    assert body["event"] == "file.fetched_failed" and body["data"]["error"] == "boom" and body["data"]["result"] == {"files": []}

    # 4. exception -> _failed, and re-raised
    try:
        with dispatch.job_events("file.fetched", CLIENT, **ids):
            raise RuntimeError("scrape died")
        raise AssertionError("exception was swallowed")
    except RuntimeError:
        pass
    assert last()[1]["data"]["error"] == "RuntimeError: scrape died"

    # 5. no outcome set
    with dispatch.job_events("file.fetched", CLIENT, **ids):
        pass
    assert last()[1]["data"]["error"] == "job ended without a result"

    # 6. routing: other client, no client, unsubscribed event -> nothing sent
    n = len(received)
    with dispatch.job_events("file.fetched", "whk_other", **ids) as o:
        o.succeed()
    with dispatch.job_events("file.fetched", None, **ids) as o:
        o.succeed()
    with dispatch.job_events("file.parsed", CLIENT, **ids) as o:
        o.succeed()  # CLIENT is subscribed to file.parsed_failed only
    assert len(received) == n

    # 7. one immediate attempt: 500 -> 1 request + queued for retry; 400 -> 1 request, not queued
    assert not published, published  # nothing above failed
    n = len(received)
    statuses.put(500)
    dispatch.emit(CLIENT, "file.fetched_success", {"x": 1})
    assert len(received) == n + 1
    (q, msg), = published
    first_body = received[-1][1]
    assert q == dispatch.DELAY_QUEUE and msg["attempt"] == 1 and msg["error"] == "HTTP 500"
    assert msg["client_id"] == CLIENT and msg["event"] == "file.fetched_success" and msg["body"].encode() == first_body
    statuses.put(400)
    dispatch.emit(CLIENT, "file.fetched_success", {})
    assert len(received) == n + 2 and len(published) == 1

    # 8. retry: same body and X-Webhook-Id, re-signed with the *current* secret
    SECRET = "whsec_rotated"
    dispatch.redeliver(msg)
    h, body, raw = last()
    assert raw == first_body and h["X-Webhook-Id"] == msg["id"] == body["id"]
    assert h["X-Webhook-Signature"] == dispatch.sign("whsec_rotated", h["X-Webhook-Timestamp"], raw)
    assert len(published) == 1  # delivered, nothing re-queued

    # 9. retry fails again -> next attempt; last allowed retry fails -> dead queue
    statuses.put(503)
    dispatch.redeliver(msg)
    assert published[-1][0] == dispatch.DELAY_QUEUE and published[-1][1]["attempt"] == 2
    statuses.put(503)
    dispatch.redeliver({**msg, "attempt": dispatch.MAX_RETRIES})
    assert published[-1][0] == dispatch.DEAD_QUEUE and published[-1][1]["attempt"] == dispatch.MAX_RETRIES + 1

    # 10. retry for a webhook that was paused/deleted meanwhile -> nothing sent, nothing queued
    n, p = len(received), len(published)
    dispatch.redeliver({**msg, "client_id": "whk_gone"})
    assert len(received) == n and len(published) == p

    # 11. unreachable URL does not raise and is queued
    real = dispatch._subscribers
    dispatch._subscribers = lambda cid, event: [("http://127.0.0.1:1/x", cid, SECRET)]
    dispatch.emit(CLIENT, "file.fetched_success", {})
    dispatch._subscribers = real
    assert published[-1][0] == dispatch.DELAY_QUEUE

    # 12. queue publish failing (RabbitMQ down) does not raise
    dispatch._publish = lambda q, m: (_ for _ in ()).throw(ConnectionError("rabbit down"))
    statuses.put(500)
    dispatch.emit(CLIENT, "file.fetched_success", {})
    dispatch._publish = lambda q, m: published.append((q, m))

    # 13. unknown event does not raise and sends nothing
    n = len(received)
    dispatch.emit(CLIENT, "file.bogus_success", {})
    assert len(received) == n

    # 14. retry worker: bad message -> dead queue; redelivery error -> back to delay queue; always ack
    from automation_v2.management.commands.consume_webhook_retry_v2 import on_message

    class Ch:
        def __init__(self):
            self.calls = []
        def basic_publish(self, exchange, queue, body, props):
            self.calls.append(queue)
        def basic_ack(self, delivery_tag):
            self.calls.append("ack")

    class M:
        delivery_tag = 1

    ch = Ch(); on_message(ch, M, None, b"not json")
    assert ch.calls == [dispatch.DEAD_QUEUE, "ack"]
    dispatch._subscribers = lambda cid, event: (_ for _ in ()).throw(RuntimeError("db down"))
    ch = Ch(); on_message(ch, M, None, json.dumps(msg).encode())
    assert ch.calls == [dispatch.DELAY_QUEUE, "ack"]
    dispatch._subscribers = real

    print("dispatch self-check OK")


if __name__ == "__main__":
    main()

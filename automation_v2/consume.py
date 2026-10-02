"""Shared RabbitMQ consumer loop for the v2 workers.

One message = one job = exactly one webhook event. A handler returns the result
(success) or raises (failure). No job publishes to another queue.
"""
import json
import logging
import os

import pika
from django.conf import settings

from .dispatch import client_id_from, job_events

logger = logging.getLogger(__name__)


def get_channel(queue: str):
    channel = pika.BlockingConnection(pika.URLParameters(settings.MQ_URL)).channel()
    channel.queue_declare(queue=queue, durable=True)
    return channel


def handle(ch, method, body: bytes, base: str, adapter, handlers: dict) -> None:
    try:
        raw = json.loads(body)
        if not isinstance(raw, dict):
            raise ValueError("payload is not a JSON object")
    except Exception:
        # No payload means no ids and no client_id, so there is nobody to notify.
        logger.exception("Undecodable message dropped: %r", body[:200])
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return
    try:
        with job_events(base, client_id_from(raw), type=raw.get("type"), referenceNo=raw.get("referenceNo")) as outcome:
            job = adapter.validate_python(raw)
            logger.info("Job start type=%s referenceNo=%s", job.type, job.referenceNo)
            outcome.succeed(handlers[job.type](job))
        logger.info("Job done type=%s referenceNo=%s", job.type, job.referenceNo)
        ch.basic_ack(delivery_tag=method.delivery_tag)
    except Exception:
        # ponytail: nack without requeue or DLX drops the message, same as legacy; add a DLX if replay matters
        logger.exception("Job failed payload=%s", raw)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def serve(queue: str, base: str, adapter, handlers: dict) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    os.makedirs(settings.TENDER_PARSING_TEMP_DIR, exist_ok=True)
    channel = get_channel(queue)
    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=queue, on_message_callback=lambda ch, m, _p, body: handle(ch, m, body, base, adapter, handlers))
    logger.info("Listening on %s (event %s_*)", queue, base)
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        channel.stop_consuming()
        channel.connection.close()

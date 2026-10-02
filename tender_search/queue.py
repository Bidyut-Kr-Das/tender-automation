import json
import logging

import pika

from django.conf import settings

logger = logging.getLogger(__name__)


def get_connection():
    url = settings.MQ_URL
    if not url:
        raise ValueError(
            "MQ_URL is not configured. Set the MQ_URL environment variable."
        )
    params = pika.URLParameters(url)
    return pika.BlockingConnection(params)


def get_channel(queue):
    conn = get_connection()
    channel = conn.channel()
    channel.queue_declare(queue=queue, durable=True)
    return channel


def publish(ch, queue: str, payload: dict):
    # ponytail: single persistent publish, json + delivery_mode=2
    body = json.dumps(payload)
    print(f"[Publish] queue={queue} payload={body}")
    logger.info("[Publish] queue=%s payload=%s", queue, body)
    ch.basic_publish(
        exchange="",
        routing_key=queue,
        body=body,
        properties=pika.BasicProperties(delivery_mode=2),
    )
    logger.info("Published to %s: %s", queue, body)
    print(f"[Publish] done queue={queue}")

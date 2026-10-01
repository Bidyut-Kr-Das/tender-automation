import json
import logging

import pika
from django.conf import settings
from django.core.management.base import BaseCommand

from automation_v2.dispatch import DEAD_QUEUE, DELAY_QUEUE, RETRY_DELAY_S, RETRY_QUEUE, declare_queues, redeliver

logger = logging.getLogger(__name__)


def on_message(ch, method, _properties, body: bytes) -> None:
    try:
        redeliver(json.loads(body))
    except (ValueError, KeyError):
        logger.exception("Malformed retry message, parked in %s", DEAD_QUEUE)
        ch.basic_publish("", DEAD_QUEUE, body, pika.BasicProperties(delivery_mode=2))
    except Exception:
        # e.g. the webhooks DB is down: try the same attempt again after the delay
        logger.exception("Webhook redelivery errored, retrying in %ss", RETRY_DELAY_S)
        ch.basic_publish("", DELAY_QUEUE, body, pika.BasicProperties(delivery_mode=2))
    ch.basic_ack(delivery_tag=method.delivery_tag)


class Command(BaseCommand):
    help = "v2: retry failed webhook deliveries from the webhook retry queue"

    def handle(self, *args, **options):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        channel = pika.BlockingConnection(pika.URLParameters(settings.RABBITMQ_URL)).channel()
        declare_queues(channel)
        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(queue=RETRY_QUEUE, on_message_callback=on_message)
        logger.info("Listening on %s", RETRY_QUEUE)
        try:
            channel.start_consuming()
        except KeyboardInterrupt:
            channel.stop_consuming()
            channel.connection.close()

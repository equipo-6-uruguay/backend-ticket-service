"""
Consumer de RabbitMQ para el servicio de tickets.
Escucha eventos de otros servicios, como assignment.deleted.
"""
import os
import sys
import django
import logging
import time

# Agregar directorio base al path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ticket_service.settings")
django.setup()

import pika
import json
from typing import Any

from tickets.messaging.handlers import handle_assignment_event

logger = logging.getLogger(__name__)

RABBIT_HOST = os.environ.get('RABBITMQ_HOST', 'rabbitmq')
RABBIT_USER = os.environ.get('RABBITMQ_USER', 'guest')
RABBIT_PASS = os.environ.get('RABBITMQ_PASSWORD', 'guest')
EXCHANGE_NAME = os.environ.get('RABBITMQ_EXCHANGE_NAME', 'tickets')
QUEUE_NAME = os.environ.get('RABBITMQ_QUEUE_TICKETS', 'tickets_queue')

INITIAL_RETRY_DELAY = 1
MAX_RETRY_DELAY = 60
RETRY_BACKOFF_FACTOR = 2


def callback(ch, method, properties, body):
    """
    Callback cuando llega un mensaje desde RabbitMQ.
    """
    try:
        event_data = json.loads(body)
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON in message body: %s", exc)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    try:
        handle_assignment_event(event_data)
        logger.info("Event processed successfully: %s", event_data.get('event_type', 'unknown'))
        ch.basic_ack(delivery_tag=method.delivery_tag)
    except Exception as exc:
        logger.exception("Error processing event: %s", exc)
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def start_consuming():
    """Inicia el consumidor de RabbitMQ para el servicio de tickets."""
    connection = None
    attempt = 0

    while True:
        try:
            logger.info("Connecting to RabbitMQ at %s...", RABBIT_HOST)
            credentials = pika.PlainCredentials(RABBIT_USER, RABBIT_PASS)
            connection = pika.BlockingConnection(
                pika.ConnectionParameters(host=RABBIT_HOST, credentials=credentials)
            )
            channel = connection.channel()

            channel.exchange_declare(
                exchange=EXCHANGE_NAME, exchange_type='fanout', durable=True,
            )

            channel.queue_declare(queue=QUEUE_NAME, durable=True)
            channel.queue_bind(exchange=EXCHANGE_NAME, queue=QUEUE_NAME)

            channel.basic_consume(
                queue=QUEUE_NAME, on_message_callback=callback
            )

            if attempt > 0:
                logger.info("Successfully reconnected to RabbitMQ after %d attempt(s).", attempt)
            
            logger.info("Consumer started, waiting for messages on queue '%s'...", QUEUE_NAME)
            attempt = 0
            channel.start_consuming()

        except (pika.exceptions.AMQPConnectionError, pika.exceptions.StreamLostError, pika.exceptions.ConnectionClosedByBroker, ConnectionResetError) as exc:
            attempt += 1
            delay = min(INITIAL_RETRY_DELAY * (RETRY_BACKOFF_FACTOR ** attempt), MAX_RETRY_DELAY)
            logger.warning("Connection lost (%s). Reconnection attempt %d in %.1fs...", exc, attempt, delay)
            if connection and connection.is_open:
                connection.close()
            time.sleep(delay)

        except KeyboardInterrupt:
            logger.info("Consumer stopped by user.")
            if connection and connection.is_open:
                connection.close()
            break

        except Exception as exc:
            attempt += 1
            delay = min(INITIAL_RETRY_DELAY * (RETRY_BACKOFF_FACTOR ** attempt), MAX_RETRY_DELAY)
            logger.error("Unexpected error (%s). Reconnection attempt %d in %.1fs...", exc, attempt, delay)
            if connection and connection.is_open:
                connection.close()
            time.sleep(delay)


if __name__ == "__main__":
    start_consuming()

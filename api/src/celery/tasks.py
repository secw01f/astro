import logging

from src.celery import celery

logger = logging.getLogger(__name__)

@celery.task(name="src.tasks.heartbeat")
def heartbeat():
    logger.info("Heartbeat task executed")
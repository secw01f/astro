from celery import Celery
from settings import settings

celery = Celery(
    "worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["src.celery.tasks"]
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

celery.conf.beat_schedule = {
    "heartbeat": {
        "task": "src.celery.tasks.heartbeat",
        "schedule": 120.0,
    },
    "process-due-stack-schedules": {
        "task": "src.celery.tasks.process_due_stack_schedules",
        "schedule": 60.0,
    },
}
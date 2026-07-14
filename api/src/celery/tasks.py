import logging

from lib.stack.runner import (
    execute_interactive_stack,
    execute_scheduled_stack,
    process_due_stack_schedules,
)
from src.celery import celery
from src.db.db import run_celery_async

logger = logging.getLogger(__name__)


@celery.task(name="src.celery.tasks.heartbeat")
def heartbeat():
    logger.info("Heartbeat task executed")


@celery.task(name="src.celery.tasks.process_due_stack_schedules")
def process_due_stack_schedules_task():
    dispatches = run_celery_async(process_due_stack_schedules())
    for schedule_id, schedule_time_id in dispatches:
        run_scheduled_stack_task.delay(schedule_id, schedule_time_id)
    return {"dispatched": len(dispatches)}


@celery.task(name="src.celery.tasks.run_scheduled_stack")
def run_scheduled_stack_task(schedule_id: int, schedule_time_id: int | None = None):
    run_celery_async(execute_scheduled_stack(schedule_id, schedule_time_id))
    return {"schedule_id": schedule_id, "schedule_time_id": schedule_time_id}


@celery.task(name="src.celery.tasks.run_interactive_stack")
def run_interactive_stack_task(
    stack_id: int,
    user_id: int,
    message: str,
    run_id: str,
    user_message_id: int,
    verbose: bool = False,
):
    run_celery_async(
        execute_interactive_stack(
            stack_id,
            user_id,
            message,
            run_id,
            user_message_id,
            verbose,
        )
    )
    return {"run_id": run_id}

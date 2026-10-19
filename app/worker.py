from celery import Celery

from app.config import get_settings
from app.database import SessionLocal
from app.jobs import run_job

settings = get_settings()
celery_app = Celery("bid_review", broker=settings.redis_url)
celery_app.conf.update(task_serializer="json", accept_content=["json"],
                       task_ignore_result=True, task_acks_late=True,
                       worker_prefetch_multiplier=1, broker_connection_retry_on_startup=True,
                       broker_transport_options={"visibility_timeout": 600, "socket_timeout": 5},
                       task_soft_time_limit=480, task_time_limit=540)


@celery_app.task(name="bid_review.execute_job")
def execute_job(job_id: str):
    return run_job(SessionLocal, job_id, settings)

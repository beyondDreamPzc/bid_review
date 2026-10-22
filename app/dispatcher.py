import logging
import time

from app.config import get_settings
from app.database import SessionLocal
from app.jobs import dispatch_once, recover_jobs
from app.worker import execute_job
from app.models import Job

logger = logging.getLogger(__name__)


def send_job(job_id):
    with SessionLocal() as db:
        job=db.get(Job,job_id)
        queue={"MATERIAL_INDEX":"retrieve","REQUIREMENT_EXTRACTION":"extract","ASSISTANT_REVIEW":"extract","DOCX_CONVERT":"convert"}.get(job.kind if job else "","parse")
    execute_job.apply_async(args=[job_id],queue=queue,retry=False)


def main():
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    while True:
        try:
            recover_jobs(SessionLocal, settings)
            for _ in range(20):
                if not dispatch_once(SessionLocal, send_job, settings):
                    break
        except Exception as error:
            logger.error("Dispatch cycle failed: %s", type(error).__name__)
        time.sleep(3)


if __name__ == "__main__":
    main()

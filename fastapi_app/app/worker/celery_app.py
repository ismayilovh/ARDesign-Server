import logging
import subprocess

from celery import Celery
from celery.signals import worker_process_init

from app.core.config import settings

logger = logging.getLogger(__name__)

# Docker image used for ephemeral converter containers. The task and orphan
# sweeper share this setting so a tag change cannot desync them.
CONVERTER_IMAGE = settings.converter_image

celery_app = Celery(
    "ardesign_worker",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Prevent tasks from being silently lost if the worker crashes mid-task
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Recycle the worker process every 50 tasks. Bounds memory/fd leaks that
    # accumulate from subprocess.run() and the docker CLI shellouts in tasks.py.
    worker_max_tasks_per_child=50,
)

# Route GPU-bound generation to its own queue. The `generator` service
# listens on this queue with --concurrency=1, serializing access to the
# single Hunyuan3D instance (one GPU, can't run two generations in parallel).
# Everything else stays on the default "celery" queue.
celery_app.conf.task_routes = {
    "generate_from_image": {"queue": "generate"},
}


@worker_process_init.connect
def _prune_orphan_converters(**_kwargs):
    """Sweep converter containers left over from a previous worker crash.

    If the worker is SIGKILLed mid-task (e.g. docker compose down beyond
    stop_grace_period), tasks.py's finally block can't run docker rm -f and
    the spawned converter container is orphaned. This handler runs
    at every worker process start (boot + max_tasks_per_child recycles) and
    prunes them. Safe with --concurrency=1: no other task is running on this
    container at the moment the signal fires.
    """
    try:
        result = subprocess.run(
            ["docker", "ps", "-aq",
             "--filter", f"ancestor={CONVERTER_IMAGE}"],
            capture_output=True, text=True, check=True, timeout=10,
        )
        ids = [s for s in result.stdout.splitlines() if s.strip()]
        if not ids:
            return
        logger.info("Pruning %d orphan converter container(s): %s",
                    len(ids), ids)
        subprocess.run(
            ["docker", "rm", "-f", *ids],
            capture_output=True, check=False, timeout=30,
        )
    except (subprocess.SubprocessError, FileNotFoundError) as e:
        # Non-fatal: don't block worker startup if docker CLI / socket-proxy
        # is unavailable. Worst case is one more session of accumulation.
        logger.warning("Orphan converter cleanup failed: %s", e)

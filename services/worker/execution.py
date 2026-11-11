"""Lease renewal during slow native extraction; cooperative job deadlines."""
import logging
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar

from services.api.database import get_db
from services.worker.lifecycle import PermanentJobError

deadline: ContextVar[float | None] = ContextVar("job_deadline", default=None)


def check_deadline() -> None:
    until = deadline.get()
    if until is not None and time.monotonic() >= until:
        raise PermanentJobError("JOB_TIMEOUT", "مهلت پردازش کار پایان یافت؛ فایل برای بازبینی حفظ شد.")


def remaining_seconds(default: float) -> float:
    check_deadline()
    until = deadline.get()
    return max(0.1, min(default, until - time.monotonic())) if until else default


@contextmanager
def execution_lease(job_id: str, worker_id: str, lease_seconds: int, timeout_seconds: int):
    stopped = threading.Event()
    token = deadline.set(time.monotonic() + max(1, timeout_seconds))

    def renew():
        while not stopped.wait(max(1, lease_seconds / 3)):
            try:
                with get_db() as conn:
                    changed = conn.execute(
                        """UPDATE jobs SET lease_expires_at = datetime('now', '+' || ? || ' seconds')
                           WHERE id = ? AND worker_id = ? AND state = 'RUNNING'""",
                        (max(5, lease_seconds), job_id, worker_id),
                    ).rowcount
                if not changed:
                    return
            except Exception:
                logging.getLogger(__name__).warning("Could not renew lease for job %s", job_id)

    thread = threading.Thread(target=renew, daemon=True, name="saher-lease")
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=1)
        deadline.reset(token)

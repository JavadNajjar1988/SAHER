import os
import time
import uuid
import signal
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Optional, Dict
from services.api.config import settings
from services.api.database import init_db
from services.api.schemas import JobItemDTO
from services.worker.lifecycle import (
    ResourceProfile,
    get_resource_profile,
)
from services.worker.queue import JobQueueRepository
from services.worker.handlers import execute_job_pipeline

logger = logging.getLogger("saher.worker.runner")


class WorkerRunner:
    """
    Independent background worker supervisor for SAHER's durable processing queue.
    Supports:
    - Configurable resource modes (Eco, Balanced, Performance) and concurrency
    - Atomic SQLite job claiming with leases
    - Periodic expired-lease crash recovery
    - Per-job execution timeout enforcement
    - Event-driven immediate wakeup + durable polling fallback
    - Graceful shutdown
    """

    def __init__(
        self,
        worker_id: Optional[str] = None,
        resource_mode: Optional[str] = None,
        concurrency: Optional[int] = None,
    ):
        self.worker_id = worker_id or f"worker-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        mode = resource_mode or settings.resource_mode
        custom_conc = concurrency if concurrency is not None else settings.worker_concurrency
        self._profile: ResourceProfile = get_resource_profile(mode, custom_conc)

        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._lock = threading.Lock()
        self._supervisor_thread: Optional[threading.Thread] = None
        self._executor: Optional[ThreadPoolExecutor] = None
        self._active_futures: Dict[str, Future] = {}
        self._running = False

    @property
    def profile(self) -> ResourceProfile:
        with self._lock:
            return self._profile

    @property
    def is_running(self) -> bool:
        return self._running and not self._stop_event.is_set()

    @property
    def active_job_count(self) -> int:
        with self._lock:
            return sum(1 for f in self._active_futures.values() if not f.done())

    def configure_resources(self, resource_mode: str, concurrency: Optional[int] = None) -> ResourceProfile:
        with self._lock:
            new_profile = get_resource_profile(resource_mode, concurrency)
            self._profile = new_profile
            settings.resource_mode = new_profile.mode
            settings.worker_concurrency = new_profile.concurrency

        try:
            JobQueueRepository.upsert_worker_heartbeat(
                worker_id=self.worker_id,
                resource_mode=new_profile.mode,
                concurrency=new_profile.concurrency,
                active_jobs=self.active_job_count,
                status="ONLINE" if self.is_running else "IDLE",
            )
        except Exception:
            pass
        self.notify()
        return new_profile

    def notify(self) -> None:
        """Signals the worker loop to immediately inspect the queue without waiting for the next poll interval."""
        self._wake_event.set()

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._stop_event.clear()
            self._wake_event.clear()
            self._executor = ThreadPoolExecutor(
                max_workers=max(4, self._profile.concurrency),
                thread_name_prefix=f"saher-{self.worker_id}",
            )
            self._running = True
            self._supervisor_thread = threading.Thread(
                target=self._run_loop,
                name=f"saher-supervisor-{self.worker_id}",
                daemon=True,
            )
            self._supervisor_thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        with self._lock:
            if not self._running:
                return
            self._stop_event.set()
            self._wake_event.set()
            self._running = False

        if self._supervisor_thread and self._supervisor_thread.is_alive():
            self._supervisor_thread.join(timeout=timeout)

        if self._executor:
            self._executor.shutdown(wait=False, cancel_futures=False)
            self._executor = None

        try:
            JobQueueRepository.upsert_worker_heartbeat(
                worker_id=self.worker_id,
                resource_mode=self._profile.mode,
                concurrency=self._profile.concurrency,
                active_jobs=0,
                status="OFFLINE",
            )
        except Exception:
            pass

    def process_one(self, specific_job_id: Optional[str] = None) -> Optional[JobItemDTO]:
        """
        Claims and executes a single eligible job synchronously on the calling thread.
        Used by deterministic worker tests and backward-compatible synchronous callers.
        """
        prof = self.profile
        claimed = JobQueueRepository.claim_next_job(
            worker_id=self.worker_id,
            lease_seconds=prof.lease_seconds,
            specific_job_id=specific_job_id,
        )
        if not claimed:
            return None

        return execute_job_pipeline(
            job=claimed,
            worker_id=self.worker_id,
            stage_throttle_seconds=prof.stage_throttle_seconds,
            lease_seconds=prof.lease_seconds,
        )

    def _execute_claimed_job(self, claimed: JobItemDTO, prof: ResourceProfile) -> Optional[JobItemDTO]:
        return execute_job_pipeline(
            job=claimed,
            worker_id=self.worker_id,
            stage_throttle_seconds=prof.stage_throttle_seconds,
            lease_seconds=prof.lease_seconds,
        )

    def _run_loop(self) -> None:
        # Initial recovery of any expired leases left over from previous crashed processes
        try:
            JobQueueRepository.recover_expired_leases()
        except Exception as exc:
            logger.debug("Initial lease recovery skipped: %s", exc)

        last_recovery_check = time.monotonic()

        while not self._stop_event.is_set():
            prof = self.profile
            try:
                # Reap completed futures
                with self._lock:
                    done_ids = [jid for jid, fut in self._active_futures.items() if fut.done()]
                    for jid in done_ids:
                        self._active_futures.pop(jid, None)
                    current_active = len(self._active_futures)

                # Periodic lease recovery and worker heartbeat
                now = time.monotonic()
                if now - last_recovery_check >= 2.0:
                    last_recovery_check = now
                    try:
                        JobQueueRepository.recover_expired_leases()
                        JobQueueRepository.upsert_worker_heartbeat(
                            worker_id=self.worker_id,
                            resource_mode=prof.mode,
                            concurrency=prof.concurrency,
                            active_jobs=current_active,
                            status="ONLINE",
                        )
                    except Exception:
                        pass

                # Claim jobs up to concurrency limit
                claimed_any = False
                while current_active < prof.concurrency and not self._stop_event.is_set():
                    claimed = JobQueueRepository.claim_next_job(
                        worker_id=self.worker_id,
                        lease_seconds=prof.lease_seconds,
                    )
                    if not claimed:
                        break
                    claimed_any = True
                    if self._executor:
                        fut = self._executor.submit(self._execute_claimed_job, claimed, prof)
                        with self._lock:
                            self._active_futures[claimed.id] = fut
                            current_active = len(self._active_futures)

                if claimed_any:
                    continue

            except Exception as loop_err:
                logger.debug("Worker loop iteration warning: %s", loop_err)

            self._wake_event.wait(timeout=prof.poll_interval_seconds)
            self._wake_event.clear()


# Singleton worker manager used when embedded or triggered
default_worker = WorkerRunner()


def run_standalone_worker() -> None:
    """Entry point for running an independent Python worker process (`python -m services.worker.runner`)."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    settings.ensure_dirs()
    init_db()
    runner = WorkerRunner()
    logger.info(
        "Starting SAHER Standalone Durable Worker [%s] (mode=%s, concurrency=%d)",
        runner.worker_id,
        runner.profile.mode,
        runner.profile.concurrency,
    )
    runner.start()

    stop_sig = threading.Event()

    def _handle_sig(signum, frame):
        logger.info("Received signal %s, shutting down SAHER worker gracefully...", signum)
        stop_sig.set()

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    try:
        while not stop_sig.is_set():
            time.sleep(0.5)
    finally:
        runner.stop()


if __name__ == "__main__":
    run_standalone_worker()

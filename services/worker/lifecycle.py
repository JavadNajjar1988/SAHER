from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Set


class JobState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ProcessingStage(str, Enum):
    DISCOVERY = "DISCOVERY"
    VALIDATION = "VALIDATION"
    EXTRACTION = "EXTRACTION"
    OCR_PENDING = "OCR_PENDING"
    ANALYSIS_PENDING = "ANALYSIS_PENDING"
    INDEXING = "INDEXING"
    FINALIZATION = "FINALIZATION"


class JobType(str, Enum):
    FILE_INGESTION = "FILE_INGESTION"
    REANALYZE = "REANALYZE"
    STAGE_REPROCESS = "STAGE_REPROCESS"


class ResourceMode(str, Enum):
    ECO = "Eco"
    BALANCED = "Balanced"
    PERFORMANCE = "Performance"


@dataclass(frozen=True)
class ResourceProfile:
    mode: str
    concurrency: int
    poll_interval_seconds: float
    stage_throttle_seconds: float
    lease_seconds: int
    job_timeout_seconds: int
    max_memory_mb: int
    allow_gpu_acceleration: bool


RESOURCE_PROFILES: Dict[str, ResourceProfile] = {
    ResourceMode.ECO.value: ResourceProfile(
        mode=ResourceMode.ECO.value,
        concurrency=1,
        poll_interval_seconds=0.8,
        stage_throttle_seconds=0.04,
        lease_seconds=45,
        job_timeout_seconds=90,
        max_memory_mb=512,
        allow_gpu_acceleration=False,
    ),
    ResourceMode.BALANCED.value: ResourceProfile(
        mode=ResourceMode.BALANCED.value,
        concurrency=2,
        poll_interval_seconds=0.35,
        stage_throttle_seconds=0.01,
        lease_seconds=30,
        job_timeout_seconds=60,
        max_memory_mb=1536,
        allow_gpu_acceleration=True,
    ),
    ResourceMode.PERFORMANCE.value: ResourceProfile(
        mode=ResourceMode.PERFORMANCE.value,
        concurrency=4,
        poll_interval_seconds=0.15,
        stage_throttle_seconds=0.0,
        lease_seconds=30,
        job_timeout_seconds=60,
        max_memory_mb=4096,
        allow_gpu_acceleration=True,
    ),
}


def get_resource_profile(mode: str, custom_concurrency: Optional[int] = None) -> ResourceProfile:
    base = RESOURCE_PROFILES.get(mode, RESOURCE_PROFILES[ResourceMode.BALANCED.value])
    if custom_concurrency is not None and custom_concurrency >= 1:
        return ResourceProfile(
            mode=base.mode,
            concurrency=min(8, max(1, custom_concurrency)),
            poll_interval_seconds=base.poll_interval_seconds,
            stage_throttle_seconds=base.stage_throttle_seconds,
            lease_seconds=base.lease_seconds,
            job_timeout_seconds=base.job_timeout_seconds,
            max_memory_mb=base.max_memory_mb,
            allow_gpu_acceleration=base.allow_gpu_acceleration,
        )
    return base


VALID_STATE_TRANSITIONS: Dict[str, Set[str]] = {
    JobState.QUEUED.value: {
        JobState.RUNNING.value,
        JobState.PAUSED.value,
        JobState.CANCELLED.value,
    },
    JobState.RUNNING.value: {
        JobState.COMPLETED.value,
        JobState.FAILED.value,
        JobState.QUEUED.value,  # Retry backoff or crash lease recovery
        JobState.PAUSED.value,
        JobState.CANCELLED.value,
    },
    JobState.PAUSED.value: {
        JobState.QUEUED.value,
        JobState.CANCELLED.value,
    },
    JobState.FAILED.value: {
        JobState.QUEUED.value,
        JobState.CANCELLED.value,
    },
    JobState.CANCELLED.value: {
        JobState.QUEUED.value,
    },
    JobState.COMPLETED.value: {
        JobState.QUEUED.value,
    },
}


def can_transition_job_state(from_state: str, to_state: str) -> bool:
    if from_state == to_state:
        return True
    allowed = VALID_STATE_TRANSITIONS.get(from_state, set())
    return to_state in allowed


def compute_retry_backoff_seconds(
    attempt_count: int,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
) -> float:
    """
    Computes deterministic exponential backoff in seconds:
    attempt 1 -> 1.0s, attempt 2 -> 2.0s, attempt 3 -> 4.0s, capped at max_delay.
    """
    exponent = max(0, attempt_count - 1)
    delay = base_delay * (2 ** exponent)
    return float(min(max_delay, delay))


class RetryableJobError(Exception):
    """Raised when a job encounters a transient error (e.g., temporary I/O or lock contention) that can be safely retried."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = True


class PermanentJobError(Exception):
    """Raised when a job fails due to permanent validation, corrupted format, or unsupported document structure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = False


class JobInterruptedException(Exception):
    """Raised internally when a running job is paused, cancelled, or loses its worker lease mid-execution."""

    def __init__(self, new_state: str, message: str = "اجرای کار متوقف یا لغو شد."):
        super().__init__(message)
        self.new_state = new_state
        self.message = message

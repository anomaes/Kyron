from enum import StrEnum


class RunStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    AWAITING_FEEDBACK = "AWAITING_FEEDBACK"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
    RESUMING = "RESUMING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


ACTIVE_RUN_STATUSES = {
    RunStatus.QUEUED,
    RunStatus.RUNNING,
    RunStatus.AWAITING_FEEDBACK,
    RunStatus.RESUMING,
}
TERMINAL_RUN_STATUSES = {RunStatus.COMPLETED, RunStatus.CANCELLED}
RESUMABLE_RUN_STATUSES = {RunStatus.FAILED, RunStatus.INTERRUPTED, RunStatus.CANCELLED}
DELETABLE_RUN_STATUSES = {
    RunStatus.COMPLETED,
    RunStatus.FAILED,
    RunStatus.INTERRUPTED,
    RunStatus.CANCELLED,
}


class InvocationStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class WaveStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"
    ROLLED_BACK = "ROLLED_BACK"
    CANCELLED = "CANCELLED"


class NodeStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    AWAITING_FEEDBACK = "AWAITING_FEEDBACK"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"


class AttemptStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"


VALID_RUN_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.QUEUED: {RunStatus.RUNNING, RunStatus.CANCELLED},
    RunStatus.RUNNING: {
        RunStatus.COMPLETED,
        RunStatus.AWAITING_FEEDBACK,
        RunStatus.FAILED,
        RunStatus.INTERRUPTED,
        RunStatus.CANCELLED,
    },
    RunStatus.AWAITING_FEEDBACK: {RunStatus.RUNNING, RunStatus.CANCELLED},
    RunStatus.FAILED: {RunStatus.RESUMING, RunStatus.CANCELLED},
    RunStatus.INTERRUPTED: {RunStatus.RESUMING, RunStatus.CANCELLED},
    RunStatus.RESUMING: {RunStatus.RUNNING, RunStatus.INTERRUPTED, RunStatus.CANCELLED},
    RunStatus.COMPLETED: set(),
    RunStatus.CANCELLED: {
        RunStatus.QUEUED,
        RunStatus.RESUMING,
        RunStatus.AWAITING_FEEDBACK,
    },
}

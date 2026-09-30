from __future__ import annotations

import os
from pathlib import Path


class PiActivityMetrics:
    def __init__(self) -> None:
        self.active = 0
        self.requests = 0
        self.source_bytes = 0
        self.response_bytes = 0
        self.duration_seconds = 0.0
        self.last_file_bytes = 0

    def begin(self, file_bytes: int) -> None:
        self.active += 1
        self.last_file_bytes = file_bytes

    def finish(self, source_bytes: int, response_bytes: int, duration_seconds: float) -> None:
        self.active -= 1
        self.requests += 1
        self.source_bytes += source_bytes
        self.response_bytes += response_bytes
        self.duration_seconds += duration_seconds

    def prometheus(self) -> str:
        values = {
            "kyron_pi_activity_requests_total": self.requests,
            "kyron_pi_activity_active_requests": self.active,
            "kyron_pi_activity_source_bytes_total": self.source_bytes,
            "kyron_pi_activity_response_bytes_total": self.response_bytes,
            "kyron_pi_activity_duration_seconds_sum": self.duration_seconds,
            "kyron_pi_activity_last_file_bytes": self.last_file_bytes,
        }
        try:
            pages = int(Path("/proc/self/statm").read_text().split()[1])
            values["kyron_backend_resident_memory_bytes"] = pages * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError, IndexError):
            pass
        try:
            values["kyron_backend_cgroup_memory_bytes"] = int(
                Path("/sys/fs/cgroup/memory.current").read_text().strip()
            )
        except (OSError, ValueError):
            pass
        return "".join(f"{name} {value}\n" for name, value in values.items())


pi_activity_metrics = PiActivityMetrics()

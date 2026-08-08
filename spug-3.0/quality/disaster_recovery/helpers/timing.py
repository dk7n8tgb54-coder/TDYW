"""
RPO/RTO Timing Utilities

Provides functions for measuring and reporting Recovery Point Objective (RPO)
and Recovery Time Objective (RTO) during restore drills.
"""

import time
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import List, Optional, Dict


@dataclass
class TimingPhase:
    """A single phase of a restore/recovery operation."""
    name: str
    start_time: str = ""
    end_time: str = ""
    duration_seconds: float = 0.0
    status: str = "pending"  # pending, running, completed, failed
    detail: str = ""

    def start(self):
        self.start_time = datetime.now().isoformat()
        self.status = "running"

    def finish(self, status: str = "completed", detail: str = ""):
        self.end_time = datetime.now().isoformat()
        if self.start_time:
            start_dt = datetime.fromisoformat(self.start_time)
            end_dt = datetime.fromisoformat(self.end_time)
            self.duration_seconds = (end_dt - start_dt).total_seconds()
        self.status = status
        self.detail = detail


@dataclass
class RecoveryTimingReport:
    """Full timing report for a recovery operation."""
    operation: str  # e.g. "database_restore", "file_restore"
    phases: List[TimingPhase] = field(default_factory=list)
    total_duration_seconds: float = 0.0
    rpo_measured_seconds: Optional[float] = None  # data loss window
    rto_measured_seconds: Optional[float] = None  # total recovery time
    started_at: str = ""
    completed_at: str = ""
    target_rpo_seconds: Optional[float] = None
    target_rto_seconds: Optional[float] = None
    rpo_met: Optional[bool] = None
    rto_met: Optional[bool] = None
    notes: List[str] = field(default_factory=list)

    def add_phase(self, name: str) -> TimingPhase:
        phase = TimingPhase(name=name)
        self.phases.append(phase)
        return phase

    def finalize(self):
        """Calculate totals and check against targets."""
        if self.phases:
            self.total_duration_seconds = sum(p.duration_seconds for p in self.phases)
            self.rto_measured_seconds = self.total_duration_seconds
            first_start = min(
                datetime.fromisoformat(p.start_time) for p in self.phases if p.start_time
            )
            last_end = max(
                datetime.fromisoformat(p.end_time) for p in self.phases if p.end_time
            )
            self.started_at = first_start.isoformat()
            self.completed_at = last_end.isoformat()

        if self.target_rpo_seconds is not None and self.rpo_measured_seconds is not None:
            self.rpo_met = self.rpo_measured_seconds <= self.target_rpo_seconds

        if self.target_rto_seconds is not None and self.rto_measured_seconds is not None:
            self.rto_met = self.rto_measured_seconds <= self.target_rto_seconds

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def summary(self) -> str:
        lines = []
        lines.append("=" * 60)
        lines.append(f"RECOVERY TIMING REPORT: {self.operation}")
        lines.append("=" * 60)
        lines.append(f"  Started:  {self.started_at}")
        lines.append(f"  Completed: {self.completed_at}")
        lines.append(f"  Total duration: {self.total_duration_seconds:.1f}s")
        lines.append("-" * 60)
        for phase in self.phases:
            status_icon = {"completed": "OK", "failed": "FAIL", "running": "...", "pending": "  "}.get(phase.status, "??")
            lines.append(f"  [{status_icon}] {phase.name}: {phase.duration_seconds:.1f}s - {phase.detail}")
        lines.append("-" * 60)
        if self.rpo_measured_seconds is not None:
            rpo_str = f"{self.rpo_measured_seconds:.0f}s"
            if self.target_rpo_seconds:
                rpo_str += f" (target: {self.target_rpo_seconds:.0f}s, {'MET' if self.rpo_met else 'EXCEEDED'})"
            lines.append(f"  RPO: {rpo_str}")
        if self.rto_measured_seconds is not None:
            rto_str = f"{self.rto_measured_seconds:.0f}s"
            if self.target_rto_seconds:
                rto_str += f" (target: {self.target_rto_seconds:.0f}s, {'MET' if self.rto_met else 'EXCEEDED'})"
            lines.append(f"  RTO: {rto_str}")
        if self.notes:
            lines.append("  Notes:")
            for note in self.notes:
                lines.append(f"    - {note}")
        lines.append("=" * 60)
        return "\n".join(lines)


class RPOCalculator:
    """Calculate RPO based on backup timestamp vs failure timestamp."""

    @staticmethod
    def calculate_rpo(backup_timestamp: datetime, failure_timestamp: datetime) -> float:
        """
        Calculate RPO in seconds.
        RPO = time between last successful backup and the failure point.
        """
        delta = failure_timestamp - backup_timestamp
        return max(0, delta.total_seconds())

    @staticmethod
    def format_duration(seconds: float) -> str:
        """Format seconds into human-readable duration."""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            return f"{seconds/60:.1f}m"
        elif seconds < 86400:
            return f"{seconds/3600:.1f}h"
        else:
            return f"{seconds/86400:.1f}d"


class Stopwatch:
    """Simple stopwatch for timing operations."""

    def __init__(self):
        self._start: Optional[float] = None
        self._elapsed: float = 0.0
        self._running: bool = False

    def start(self):
        if not self._running:
            self._start = time.monotonic()
            self._running = True

    def stop(self) -> float:
        if self._running:
            self._elapsed += time.monotonic() - self._start
            self._running = False
        return self._elapsed

    def reset(self):
        self._elapsed = 0.0
        self._start = None
        self._running = False

    @property
    def elapsed(self) -> float:
        if self._running and self._start is not None:
            return self._elapsed + (time.monotonic() - self._start)
        return self._elapsed


def load_rpo_rto_targets(yaml_path: str) -> dict:
    """Load RPO/RTO targets from baselines/rpo_rto_targets.yml."""
    import yaml
    with open(yaml_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_target_for_component(targets: dict, component: str) -> Optional[dict]:
    """Get RPO/RTO target for a specific component."""
    for comp in targets.get("components", []):
        if comp.get("component") == component:
            return comp
    return None

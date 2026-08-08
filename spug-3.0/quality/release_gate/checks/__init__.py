"""共享数据模型和常量。"""

from dataclasses import dataclass, field
from typing import List

# 检查项状态
PASS = "PASS"
FAIL = "FAIL"
BLOCKED = "BLOCKED"
NOT_RUN = "NOT_RUN"
NOT_REVERIFIED = "NOT_REVERIFIED"
NOT_APPLICABLE = "NOT_APPLICABLE"

# 门禁最终状态
RELEASE_READY = "RELEASE_READY"
NOT_READY = "NOT_READY"
BLOCKED_GATE = "BLOCKED"
INPUT_INVALID = "INPUT_INVALID"

# 不可转换为 PASS 的状态
NON_PASS_STATUSES = {NOT_RUN, NOT_REVERIFIED, BLOCKED}

# 所有合法的检查项状态
VALID_CHECK_STATUSES = {PASS, FAIL, BLOCKED, NOT_RUN, NOT_REVERIFIED, NOT_APPLICABLE}

# 所有合法的门禁状态
VALID_GATE_STATUSES = {RELEASE_READY, NOT_READY, BLOCKED_GATE, INPUT_INVALID}


@dataclass
class CheckResult:
    """单条检查结果。"""
    check_id: str
    category: str
    status: str
    blocking: bool
    evidence: str
    reason: str

    def to_dict(self) -> dict:
        return {
            "check_id": self.check_id,
            "category": self.category,
            "status": self.status,
            "blocking": self.blocking,
            "evidence": self.evidence,
            "reason": self.reason,
        }


@dataclass
class GateResult:
    """门禁最终结果。"""
    gate_status: str
    input_valid: bool
    consumable_by_release_gate: bool
    can_release_now: bool
    checks: List[CheckResult] = field(default_factory=list)
    blocking_reasons: List[str] = field(default_factory=list)
    generated_at: str = ""
    input_file: str = ""
    schema_valid: bool = True

    def to_dict(self) -> dict:
        return {
            "gate_status": self.gate_status,
            "input_valid": self.input_valid,
            "schema_valid": self.schema_valid,
            "consumable_by_release_gate": self.consumable_by_release_gate,
            "can_release_now": self.can_release_now,
            "checks": [c.to_dict() for c in self.checks],
            "blocking_reasons": self.blocking_reasons,
            "generated_at": self.generated_at,
            "input_file": self.input_file,
        }

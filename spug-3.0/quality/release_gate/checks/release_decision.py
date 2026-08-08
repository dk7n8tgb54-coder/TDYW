"""最终决策：聚合所有检查结果，确定门禁状态。"""

from typing import List
from . import (
    CheckResult, GateResult,
    PASS, FAIL, BLOCKED, NOT_RUN, NOT_REVERIFIED,
    RELEASE_READY, NOT_READY, BLOCKED_GATE, INPUT_INVALID,
    NON_PASS_STATUSES,
)


def decide_gate_status(checks: List[CheckResult], input_valid: bool, schema_valid: bool = True) -> GateResult:
    """根据检查结果确定最终门禁状态。

    决策规则：
    1. input_valid=False -> INPUT_INVALID
    2. 存在 blocking=True 的检查 -> BLOCKED
    3. 存在 FAIL 或非 PASS 的强制检查（但无 blocking） -> NOT_READY
    4. 全部强制检查 PASS -> RELEASE_READY
    """
    # 规则 1: 输入无效
    if not input_valid or not schema_valid:
        return GateResult(
            gate_status=INPUT_INVALID,
            input_valid=input_valid,
            schema_valid=schema_valid,
            consumable_by_release_gate=False,
            can_release_now=False,
            checks=checks,
            blocking_reasons=["Input is invalid; gate cannot consume this input"],
        )

    # 收集阻断原因
    blocking_reasons = []
    has_blocking = False
    has_fail = False
    has_non_pass_mandatory = False

    # 强制检查类别（非 NOT_APPLICABLE 的检查都是强制的）
    mandatory_checks = [c for c in checks if c.status != "NOT_APPLICABLE"]

    for check in checks:
        if check.blocking:
            has_blocking = True
            blocking_reasons.append(f"[{check.check_id}] {check.reason}: {check.evidence}")
        elif check.status == FAIL:
            has_fail = True
        elif check.status in NON_PASS_STATUSES:
            has_non_pass_mandatory = True

    # 规则 2: 存在阻断项 -> BLOCKED
    if has_blocking:
        return GateResult(
            gate_status=BLOCKED_GATE,
            input_valid=True,
            schema_valid=True,
            consumable_by_release_gate=True,
            can_release_now=False,
            checks=checks,
            blocking_reasons=blocking_reasons,
        )

    # 规则 3: 存在失败或非 PASS 的强制检查 -> NOT_READY
    if has_fail or has_non_pass_mandatory:
        non_pass_reasons = []
        for check in mandatory_checks:
            if check.status != PASS:
                non_pass_reasons.append(f"[{check.check_id}] {check.status}: {check.reason}")
        return GateResult(
            gate_status=NOT_READY,
            input_valid=True,
            schema_valid=True,
            consumable_by_release_gate=True,
            can_release_now=False,
            checks=checks,
            blocking_reasons=non_pass_reasons,
        )

    # 规则 4: 全部通过 -> RELEASE_READY
    return GateResult(
        gate_status=RELEASE_READY,
        input_valid=True,
        schema_valid=True,
        consumable_by_release_gate=True,
        can_release_now=True,
        checks=checks,
        blocking_reasons=[],
    )

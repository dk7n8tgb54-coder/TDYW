"""工作包状态检查。

规则：
- PASS + blocking_findings > 0 -> BLOCKED（状态与发现矛盾）
- FAIL 且 blocking_on_fail -> BLOCKED
- NOT_REVERIFIED 且 not_reverified_blocks_release -> BLOCKED
- NOT_RUN -> BLOCKED
- PARTIAL -> FAIL (non-blocking unless blocking_on_fail)
- PASS + blocking_findings == 0 -> PASS
"""

from typing import List
from . import CheckResult, PASS, FAIL, BLOCKED, NOT_RUN, NOT_REVERIFIED, NON_PASS_STATUSES


def check_work_packages(data: dict, policy: dict) -> List[CheckResult]:
    """检查每个工作包的状态。"""
    results = []
    wp_list = data.get("packages", [])
    wp_map = {wp.get("id"): wp for wp in wp_list if isinstance(wp, dict)}

    required_wps = policy.get("required_work_packages", [])

    for req_wp in required_wps:
        wp_id = req_wp["id"]
        wp_name = req_wp["name"]
        required_status = req_wp.get("required_status", PASS)
        blocking_on_fail = req_wp.get("blocking_on_fail", False)
        not_reverified_blocks = req_wp.get("not_reverified_blocks_release", False)

        actual_wp = wp_map.get(wp_id)
        check_id = f"WP-{wp_id}"

        if actual_wp is None:
            results.append(CheckResult(
                check_id=check_id,
                category="work_packages",
                status=BLOCKED,
                blocking=True,
                evidence=f"Work package {wp_id} not found in input",
                reason=f"{wp_name}: missing from input data",
            ))
            continue

        actual_status = actual_wp.get("final_status", NOT_RUN)
        findings_count = actual_wp.get("blocking_findings", 0)
        if not isinstance(findings_count, int):
            findings_count = 0
        notes = actual_wp.get("notes", "")
        warnings = actual_wp.get("warnings", [])
        fail_reason = actual_wp.get("fail_reason", "")

        # 用 warnings 或 fail_reason 作为额外证据
        extra_evidence = ""
        if fail_reason:
            extra_evidence = f", fail_reason={fail_reason}"
        elif warnings:
            extra_evidence = f", warnings={len(warnings)}"

        if actual_status == PASS:
            # P1 修复：PASS + blocking_findings > 0 -> BLOCKED
            if findings_count > 0:
                results.append(CheckResult(
                    check_id=check_id,
                    category="work_packages",
                    status=BLOCKED,
                    blocking=True,
                    evidence=f"{wp_id} final_status={actual_status}, blocking_findings={findings_count}",
                    reason=f"{wp_name}: PASS status contradicts {findings_count} blocking finding(s)",
                ))
            else:
                results.append(CheckResult(
                    check_id=check_id,
                    category="work_packages",
                    status=PASS,
                    blocking=False,
                    evidence=f"{wp_id} final_status={actual_status}, blocking_findings={findings_count}",
                    reason=f"{wp_name}: passed",
                ))
        elif actual_status == FAIL:
            is_blocking = blocking_on_fail
            results.append(CheckResult(
                check_id=check_id,
                category="work_packages",
                status=BLOCKED if is_blocking else FAIL,
                blocking=is_blocking,
                evidence=f"{wp_id} final_status=FAIL, blocking_findings={findings_count}{extra_evidence}",
                reason=f"{wp_name}: failed{' (blocking)' if is_blocking else ''}",
            ))
        elif actual_status == "PARTIAL":
            is_blocking = blocking_on_fail
            results.append(CheckResult(
                check_id=check_id,
                category="work_packages",
                status=BLOCKED if is_blocking else FAIL,
                blocking=is_blocking,
                evidence=f"{wp_id} final_status=PARTIAL{extra_evidence}",
                reason=f"{wp_name}: partially complete{' (blocking)' if is_blocking else ''}",
            ))
        elif actual_status == NOT_REVERIFIED:
            is_blocking = not_reverified_blocks
            results.append(CheckResult(
                check_id=check_id,
                category="work_packages",
                status=BLOCKED if is_blocking else NOT_REVERIFIED,
                blocking=is_blocking,
                evidence=f"{wp_id} final_status=NOT_REVERIFIED",
                reason=f"{wp_name}: not independently re-verified{' (blocks release)' if is_blocking else ''}",
            ))
        elif actual_status == NOT_RUN:
            results.append(CheckResult(
                check_id=check_id,
                category="work_packages",
                status=BLOCKED,
                blocking=True,
                evidence=f"{wp_id} final_status=NOT_RUN",
                reason=f"{wp_name}: tests not executed",
            ))
        elif actual_status == BLOCKED:
            results.append(CheckResult(
                check_id=check_id,
                category="work_packages",
                status=BLOCKED,
                blocking=True,
                evidence=f"{wp_id} final_status=BLOCKED{extra_evidence}",
                reason=f"{wp_name}: blocked",
            ))
        elif actual_status == "NOT_APPLICABLE":
            results.append(CheckResult(
                check_id=check_id,
                category="work_packages",
                status="NOT_APPLICABLE",
                blocking=False,
                evidence=f"{wp_id} final_status=NOT_APPLICABLE",
                reason=f"{wp_name}: not applicable",
            ))
        else:
            results.append(CheckResult(
                check_id=check_id,
                category="work_packages",
                status=BLOCKED,
                blocking=True,
                evidence=f"{wp_id} final_status={actual_status}",
                reason=f"{wp_name}: unknown status",
            ))

    return results

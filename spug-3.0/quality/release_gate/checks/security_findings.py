"""安全发现检查：检查 CRITICAL/HIGH 发现和泄露凭据。

关键规则：
- CRITICAL 严重度始终按等级阻断，不信任报告中的 blocking=false。
  只有 remediation_status 严格匹配 resolved/mitigated/fixed/completed/verified 时才视为已关闭。
  子字符串匹配（如 "Unfixed" 包含 "fixed"）禁止使用。
- HIGH 严重度在未关闭时导致 NOT_READY。
- 凭据轮换状态通过显式 rotation_status 字段判断。
"""

from typing import List
from . import CheckResult, PASS, FAIL, BLOCKED

# 视为已关闭的 remediation_status（严格枚举匹配，不做子字符串匹配）
RESOLVED_STATUSES = {
    "resolved",
    "mitigated",
    "fixed",
    "completed",
    "verified",
}


def _is_resolved(remediation_status: str) -> bool:
    """判断 remediation_status 是否表示已关闭。
    
    使用严格枚举匹配：strip + lower 后必须完全匹配集合中的值。
    禁止子字符串匹配（如 "Unfixed" 包含 "fixed" 会误判）。
    """
    if not remediation_status:
        return False
    return remediation_status.strip().lower() in RESOLVED_STATUSES


def check_security_findings(data: dict, policy: dict) -> List[CheckResult]:
    """检查安全发现和泄露凭据。"""
    results = []
    security_policy = policy.get("security", {})
    blocking_severities = set(security_policy.get("blocking_severities", ["CRITICAL"]))
    not_ready_severities = set(security_policy.get("not_ready_severities", ["HIGH"]))
    require_rotation = security_policy.get("require_secret_rotation", True)
    rotated_statuses = set(security_policy.get("rotated_statuses", ["completed", "verified", "not_required"]))
    unrotated_statuses = set(security_policy.get("unrotated_statuses", ["pending", "unrotated", "needs_rotation"]))

    # --- 检查 confirmed_findings ---
    findings = data.get("confirmed_findings", [])
    critical_open = []
    high_open = []

    for f in findings:
        if not isinstance(f, dict):
            continue
        severity = f.get("severity", "")
        remediation_status = f.get("remediation_status", "")

        # 判断是否已关闭：仅看 remediation_status，不看 blocking 字段
        # CRITICAL 始终按严重等级处理，blocking=false 不能绕过
        is_open = not _is_resolved(remediation_status)

        if is_open:
            if severity in blocking_severities:
                critical_open.append(f)
            elif severity in not_ready_severities:
                high_open.append(f)

    # CRITICAL 发现检查
    if critical_open:
        ids = [f.get("id", "?") for f in critical_open]
        results.append(CheckResult(
            check_id="SEC-001",
            category="security_findings",
            status=BLOCKED,
            blocking=True,
            evidence=f"{len(critical_open)} open CRITICAL finding(s): {', '.join(ids)}",
            reason="Open CRITICAL findings block release (severity-based, blocking field ignored)",
        ))
    else:
        results.append(CheckResult(
            check_id="SEC-001",
            category="security_findings",
            status=PASS,
            blocking=False,
            evidence="No open CRITICAL findings",
            reason="No blocking security findings",
        ))

    # HIGH 发现检查
    if high_open:
        ids = [f.get("id", "?") for f in high_open]
        results.append(CheckResult(
            check_id="SEC-002",
            category="security_findings",
            status=FAIL,
            blocking=False,
            evidence=f"{len(high_open)} open HIGH finding(s): {', '.join(ids)}",
            reason="Open HIGH findings prevent RELEASE_READY",
        ))
    else:
        results.append(CheckResult(
            check_id="SEC-002",
            category="security_findings",
            status=PASS,
            blocking=False,
            evidence="No open HIGH findings",
            reason="No HIGH findings blocking release readiness",
        ))

    # --- 泄露凭据检查 ---
    if require_rotation:
        secret_findings = data.get("secret_findings", [])
        unrotated = []
        for s in secret_findings:
            if not isinstance(s, dict):
                continue

            rotation_status = s.get("rotation_status", "")

            if rotation_status in rotated_statuses:
                continue
            elif rotation_status in unrotated_statuses:
                unrotated.append(s)
            else:
                # rotation_status 字段缺失 -> 回退到推断逻辑（向后兼容）
                git_commit = s.get("git_commit", "")
                recommendation = s.get("recommendation", "").lower()

                needs_rotation = (
                    git_commit != "" or
                    "rotate" in recommendation or
                    "轮换" in recommendation
                )

                if "acceptable" in recommendation:
                    needs_rotation = False

                if needs_rotation:
                    unrotated.append(s)

        if unrotated:
            ids = [s.get("id", "?") for s in unrotated]
            results.append(CheckResult(
                check_id="SEC-003",
                category="security_findings",
                status=BLOCKED,
                blocking=True,
                evidence=f"{len(unrotated)} unrotated secret(s): {', '.join(ids)}",
                reason="Leaked credentials must be rotated before release",
            ))
        else:
            results.append(CheckResult(
                check_id="SEC-003",
                category="security_findings",
                status=PASS,
                blocking=False,
                evidence="All leaked credentials rotated or no leaks found",
                reason="No unrotated credentials blocking release",
            ))
    else:
        results.append(CheckResult(
            check_id="SEC-003",
            category="security_findings",
            status="NOT_APPLICABLE",
            blocking=False,
            evidence="Secret rotation not required by policy",
            reason="Policy does not require secret rotation",
        ))

    return results

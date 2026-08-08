"""必需证据检查：检查必需报告和测试执行记录。

核心原则：每项证据独立验证，status=PASS 不是声明而是需要验证的证据。
- 路径必须是仓库内相对路径，禁止绝对路径和 .. 穿越
- 文件必须存在且非空（当 project_root 提供时）
- 性能和灾备环境必须在隔离环境白名单中
- 执行时间必须是合法时间（ISO 8601，不在未来）
- 每类报告需要校验自己的结果字段
- WP2/3/4/7 应分别提供执行报告路径，不能只依赖 tests_executed=true
"""

import os
from datetime import datetime
from typing import List, Tuple
from . import CheckResult, PASS, FAIL, BLOCKED, NOT_RUN


def _validate_path(path: str, project_root: str = None) -> Tuple[bool, str]:
    """验证路径：相对路径、无穿越、文件存在且非空。

    Returns:
        (is_valid, error_message)
    """
    if not path or not isinstance(path, str):
        return False, "path is empty or not a string"

    # 禁止绝对路径
    if os.path.isabs(path):
        return False, f"absolute path not allowed: {path}"

    # 禁止路径穿越
    parts = path.replace("\\", "/").split("/")
    if ".." in parts:
        return False, f"path traversal not allowed: {path}"

    # 文件存在且非空
    if project_root:
        full_path = os.path.join(project_root, path)
        if not os.path.isfile(full_path):
            return False, f"file does not exist: {path}"
        if os.path.getsize(full_path) == 0:
            return False, f"file is empty: {path}"

    return True, ""


def _validate_environment(env: str, whitelist: list) -> Tuple[bool, str]:
    """验证环境是否在白名单中。"""
    if not env:
        return False, "environment is empty"
    if env not in whitelist:
        return False, f"environment '{env}' not in whitelist: {whitelist}"
    return True, ""


def _validate_datetime(dt_str: str) -> Tuple[bool, str]:
    """验证时间字符串（ISO 8601，不在未来）。"""
    if not dt_str:
        return False, "datetime is empty"
    try:
        dt = datetime.fromisoformat(dt_str)
        if dt > datetime.now():
            return False, f"datetime is in the future: {dt_str}"
        return True, ""
    except (ValueError, TypeError):
        return False, f"invalid datetime format: {dt_str}"


def _check_required_fields(entry: dict, required_fields: list) -> Tuple[bool, list]:
    """检查必需字段是否存在且非 None。"""
    missing = []
    for field in required_fields:
        val = entry.get(field)
        if val is None:
            missing.append(field)
    return len(missing) == 0, missing


def _is_check_blocked(blocked_checks_list: list, check_key: str) -> Tuple[bool, str]:
    """检查 blocked_checks 中是否有指定的 check 条目。"""
    for bc in blocked_checks_list:
        if not isinstance(bc, dict):
            continue
        if bc.get("check") == check_key:
            status = bc.get("status", "")
            if status in ("BLOCKED", "NOT_RUN", "NOT_EXECUTED"):
                return True, bc.get("reason", "")
    return False, ""


def _has_missing_for_package(missing_artifacts_list: list, package: str) -> list:
    """检查 missing_artifacts 中是否有指定 package 的条目。"""
    return [
        ma for ma in missing_artifacts_list
        if isinstance(ma, dict) and ma.get("package") == package
    ]


def _get_evidence_entry(data: dict, key: str) -> dict:
    """从 evidence 区块中获取指定条目。"""
    evidence = data.get("evidence", {})
    if not isinstance(evidence, dict):
        return {}
    entry = evidence.get(key, {})
    if not isinstance(entry, dict):
        return {}
    return entry


def check_required_evidence(
    data: dict, policy: dict, project_root: str = None
) -> List[CheckResult]:
    """检查必需证据是否存在。

    每项证据独立验证：status=PASS 时还需验证路径、环境、时间、必需字段。
    """
    results = []
    required_evidence = policy.get("required_evidence", [])
    evidence_validation = policy.get("evidence_validation", {})
    env_whitelist = evidence_validation.get("environment_whitelist", [])
    required_fields_map = evidence_validation.get("required_fields", {})

    wp_list = data.get("packages", [])
    wp_map = {wp.get("id"): wp for wp in wp_list if isinstance(wp, dict)}

    blocked_checks_list = data.get("blocked_checks", [])
    missing_artifacts_list = data.get("missing_artifacts", [])

    for ev in required_evidence:
        check_id = ev.get("check_id", "EVID-UNKNOWN")
        description = ev.get("description", "")
        category = ev.get("category", "")
        required = ev.get("required", False)
        blocking_if_missing = ev.get("blocking_if_missing", True)

        if not required:
            results.append(CheckResult(
                check_id=check_id,
                category="required_evidence",
                status="NOT_APPLICABLE",
                blocking=False,
                evidence=f"{description}: not required by policy",
                reason="Evidence not required",
            ))
            continue

        if category == "required_report":
            results.extend(_check_required_report(
                data, ev, wp_map, blocked_checks_list, missing_artifacts_list,
                required_fields_map, project_root, blocking_if_missing
            ))
        elif category == "test_executed":
            results.extend(_check_test_executed(
                data, ev, blocked_checks_list,
                required_fields_map, env_whitelist, project_root, blocking_if_missing
            ))
        elif category == "reverification":
            results.extend(_check_reverification(
                wp_map, ev, project_root, blocking_if_missing
            ))
        else:
            results.append(CheckResult(
                check_id=check_id,
                category="required_evidence",
                status=NOT_RUN,
                blocking=blocking_if_missing,
                evidence=f"category={category} has no handler",
                reason=f"{description}: unknown evidence category",
            ))

    return results


def _check_required_report(
    data, ev, wp_map, blocked_checks_list, missing_artifacts_list,
    required_fields_map, project_root, blocking_if_missing
) -> List[CheckResult]:
    """验证必需报告（如 WP6 权限审计报告）。"""
    check_id = ev.get("check_id", "EVID-UNKNOWN")
    description = ev.get("description", "")
    wp_ref = ev.get("wp_ref", "WP6")
    evidence_key = ev.get("evidence_key", "permission_audit")

    wp = wp_map.get(wp_ref, {})
    wp_status = wp.get("final_status", NOT_RUN)
    wp_artifacts_complete = wp.get("artifacts_complete", None)

    ev_entry = _get_evidence_entry(data, evidence_key)
    ev_status = ev_entry.get("status", "")

    # 负面信号
    missing_for_wp = _has_missing_for_package(missing_artifacts_list, wp_ref)
    missing_for_wp_blocking = [
        ma for ma in missing_for_wp if ma.get("severity", "HIGH") != "INFO"
    ]
    audit_blocked, audit_reason = _is_check_blocked(
        blocked_checks_list, "permission_audit_report"
    )
    artifacts_incomplete = (wp_artifacts_complete is False)

    evidence_parts = []
    validation_errors = []

    if ev_status == "PASS":
        # 验证必需字段
        req_fields = required_fields_map.get(evidence_key, [])
        fields_ok, missing_fields = _check_required_fields(ev_entry, req_fields)
        if not fields_ok:
            validation_errors.append(f"missing required fields: {', '.join(missing_fields)}")
        else:
            evidence_parts.append(f"evidence.{evidence_key}.status=PASS")

            # 验证路径
    report_paths = ev_entry.get("report_paths", [])
    if isinstance(report_paths, list):
        for rp in report_paths:
            path_ok, path_err = _validate_path(rp, project_root)
            if not path_ok:
                validation_errors.append(path_err)
            else:
                evidence_parts.append(f"path={rp}")

            # 验证时间
        generated_at = ev_entry.get("generated_at")
        if generated_at:
            dt_ok, dt_err = _validate_datetime(generated_at)
            if not dt_ok:
                validation_errors.append(dt_err)
            else:
                evidence_parts.append(f"generated_at={generated_at}")
    else:
        evidence_parts.append(f"evidence.{evidence_key}.status={ev_status or 'MISSING'}")

    if missing_for_wp_blocking:
        paths = [ma.get("path", "?") for ma in missing_for_wp_blocking[:3]]
        evidence_parts.append(f"missing_artifacts: {', '.join(paths)}")
    if audit_blocked:
        evidence_parts.append(f"blocked_check: {audit_reason}")
    if artifacts_incomplete:
        evidence_parts.append("artifacts_complete=False")
    evidence_parts.append(f"{wp_ref} final_status={wp_status}")

    # 通过条件：status=PASS + 无验证错误 + 无负面信号
    all_clear = (
        ev_status == "PASS"
        and not validation_errors
        and not missing_for_wp_blocking
        and not audit_blocked
        and not artifacts_incomplete
    )

    if all_clear:
        return [CheckResult(
            check_id=check_id,
            category="required_evidence",
            status=PASS,
            blocking=False,
            evidence="; ".join(evidence_parts),
            reason=f"{description}: evidence confirmed",
        )]
    else:
        reason = f"{description}: evidence not confirmed"
        if validation_errors:
            reason += f" ({'; '.join(validation_errors)})"
        elif ev_status != "PASS":
            reason += f" (requires evidence.{evidence_key}.status=PASS)"
        return [CheckResult(
            check_id=check_id,
            category="required_evidence",
            status=BLOCKED if blocking_if_missing else FAIL,
            blocking=blocking_if_missing,
            evidence="; ".join(evidence_parts),
            reason=reason,
        )]


def _check_test_executed(
    data, ev, blocked_checks_list,
    required_fields_map, env_whitelist, project_root, blocking_if_missing
) -> List[CheckResult]:
    """验证测试执行（性能负载 / 灾备恢复）。"""
    check_id = ev.get("check_id", "EVID-UNKNOWN")
    description = ev.get("description", "")
    blocked_check_key = ev.get("blocked_check_key", "")
    evidence_key = ev.get("evidence_key", blocked_check_key)

    ev_entry = _get_evidence_entry(data, evidence_key)
    ev_status = ev_entry.get("status", "")

    is_blocked, block_reason = _is_check_blocked(blocked_checks_list, blocked_check_key)

    evidence_parts = []
    validation_errors = []

    if ev_status == "PASS":
        # 验证必需字段
        req_fields = required_fields_map.get(evidence_key, [])
        fields_ok, missing_fields = _check_required_fields(ev_entry, req_fields)
        if not fields_ok:
            validation_errors.append(f"missing required fields: {', '.join(missing_fields)}")
        else:
            evidence_parts.append(f"evidence.{evidence_key}.status=PASS")

            # 验证结果路径
        result_path = ev_entry.get("result_path") or ev_entry.get("drill_report", "")
        if result_path:
            path_ok, path_err = _validate_path(result_path, project_root)
            if not path_ok:
                validation_errors.append(path_err)
            else:
                evidence_parts.append(f"path={result_path}")

        # 验证环境
        environment = ev_entry.get("environment", "")
        if environment:
            env_ok, env_err = _validate_environment(environment, env_whitelist)
            if not env_ok:
                validation_errors.append(env_err)
            else:
                evidence_parts.append(f"environment={environment}")

        # 验证执行时间
        executed_at = ev_entry.get("executed_at") or ev_entry.get("restored_at", "")
        if executed_at:
            dt_ok, dt_err = _validate_datetime(executed_at)
            if not dt_ok:
                validation_errors.append(dt_err)
            else:
                evidence_parts.append(f"executed_at={executed_at}")
    else:
        evidence_parts.append(f"evidence.{evidence_key}.status={ev_status or 'MISSING'}")

    if is_blocked:
        evidence_parts.append(f"blocked_check {blocked_check_key}: {block_reason}")

    # 通过条件：status=PASS + 无验证错误 + 无负面信号
    all_clear = ev_status == "PASS" and not validation_errors and not is_blocked

    if all_clear:
        return [CheckResult(
            check_id=check_id,
            category="required_evidence",
            status=PASS,
            blocking=False,
            evidence="; ".join(evidence_parts),
            reason=f"{description}: evidence confirmed",
        )]
    else:
        reason = f"{description}: evidence not confirmed"
        if validation_errors:
            reason += f" ({'; '.join(validation_errors)})"
        elif ev_status != "PASS":
            reason += f" (requires evidence.{evidence_key}.status=PASS)"
        return [CheckResult(
            check_id=check_id,
            category="required_evidence",
            status=BLOCKED if blocking_if_missing else FAIL,
            blocking=blocking_if_missing,
            evidence="; ".join(evidence_parts),
            reason=reason,
        )]


def _check_reverification(
    wp_map, ev, project_root, blocking_if_missing
) -> List[CheckResult]:
    """验证 WP2/WP3/WP4/WP7 独立复验：每个 WP 需 tests_executed=true + execution_report 路径。"""
    check_id = ev.get("check_id", "EVID-UNKNOWN")
    description = ev.get("description", "")

    reverify_wps = ["WP2", "WP3", "WP4", "WP7"]
    not_reverified = []
    not_executed = []
    missing_reports = []
    invalid_reports = []

    for wp_id in reverify_wps:
        wp = wp_map.get(wp_id, {})
        status = wp.get("final_status", NOT_RUN)
        tests_executed = wp.get("tests_executed", None)
        execution_report = wp.get("execution_report", None)

        if status == "NOT_REVERIFIED":
            not_reverified.append(wp_id)
            continue

        if tests_executed is not True:
            not_executed.append(wp_id)
            continue

        # 验证 execution_report 路径
        if not execution_report:
            missing_reports.append(wp_id)
        else:
            path_ok, path_err = _validate_path(execution_report, project_root)
            if not path_ok:
                invalid_reports.append(f"{wp_id}: {path_err}")

    evidence_parts = []
    reason_parts = []

    if not_reverified:
        evidence_parts.append(f"NOT_REVERIFIED: {', '.join(not_reverified)}")
        reason_parts.append(f"{len(not_reverified)} WP(s) not re-verified")
    if not_executed:
        evidence_parts.append(f"tests_executed != true: {', '.join(not_executed)}")
        reason_parts.append(f"{len(not_executed)} WP(s) missing tests_executed=true")
    if missing_reports:
        evidence_parts.append(f"missing execution_report: {', '.join(missing_reports)}")
        reason_parts.append(f"{len(missing_reports)} WP(s) missing execution_report path")
    if invalid_reports:
        evidence_parts.append(f"invalid execution_report: {'; '.join(invalid_reports)}")
        reason_parts.append(f"{len(invalid_reports)} WP(s) with invalid execution_report")

    if not evidence_parts:
        evidence_parts.append("all 4 WPs final_status=PASS, tests_executed=true, execution_report verified")

    if reason_parts:
        return [CheckResult(
            check_id=check_id,
            category="required_evidence",
            status=BLOCKED if blocking_if_missing else FAIL,
            blocking=blocking_if_missing,
            evidence="; ".join(evidence_parts),
            reason=f"{description}: {', '.join(reason_parts)}",
        )]
    else:
        return [CheckResult(
            check_id=check_id,
            category="required_evidence",
            status=PASS,
            blocking=False,
            evidence="; ".join(evidence_parts),
            reason=f"{description}: evidence confirmed",
        )]

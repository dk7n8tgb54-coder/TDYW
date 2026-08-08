"""输入校验：检查 JSON 可解析性、必需字段和类型。

门禁输出字段（schema_valid/input_valid/consumable_by_release_gate/can_release_now/gate_status）
由门禁计算，不属于输入必需字段。如果输入中包含这些字段，仅做类型检查。
"""

import json
from typing import Tuple
from . import CheckResult, PASS, FAIL

# 必需的顶层字段（仅数据字段，不含门禁输出字段）
REQUIRED_FIELDS = [
    "schema_version",
    "generated_at",
    "git_commit",
    "worktree_status",
    "packages",
    "confirmed_findings",
    "secret_findings",
    "verified_test_results",
]

# 字段类型约束（必需 + 可选字段）
FIELD_TYPES = {
    "schema_version": str,
    "generated_at": str,
    "git_commit": str,
    "worktree_status": str,
    "packages": list,
    "confirmed_findings": list,
    "secret_findings": list,
    "verified_test_results": dict,
    # 门禁输出字段（可选，如果存在则检查类型）
    "schema_valid": bool,
    "input_valid": bool,
    "consumable_by_release_gate": bool,
    "can_release_now": bool,
    "gate_status": str,
}

# packages 子项必需字段
WP_REQUIRED_FIELDS = ["id", "name", "final_status"]
WP_VALID_STATUSES = {
    "PASS", "FAIL", "PARTIAL", "NOT_REVERIFIED", "NOT_RUN", "BLOCKED", "NOT_APPLICABLE"
}

# confirmed_findings 子项必需字段
FINDING_REQUIRED_FIELDS = ["id", "severity", "title"]
FINDING_VALID_SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}

# secret_findings 子项必需字段
SECRET_REQUIRED_FIELDS = ["id", "type", "location"]

# verified_test_results 子项必需字段
VTR_REQUIRED_FIELDS = ["total_verified_executed"]


def validate_json(raw_text: str) -> Tuple[bool, dict, str]:
    """尝试解析 JSON 文本。

    Returns:
        (success, parsed_data, error_message)
    """
    try:
        data = json.loads(raw_text)
        if not isinstance(data, dict):
            return False, {}, "Input is valid JSON but not a JSON object"
        return True, data, ""
    except json.JSONDecodeError as e:
        return False, {}, f"JSON parse error: {e}"
    except UnicodeDecodeError as e:
        return False, {}, f"Encoding error: {e}"


def validate_schema(data: dict) -> Tuple[bool, list]:
    """手动校验 schema（不依赖 jsonschema 库）。

    校验规则与 schemas/release_gate_input.schema.json 保持一致。
    该 JSON Schema 文件供参考和文档化使用，实际校验由此函数执行。

    Returns:
        (is_valid, list_of_errors)
    """
    errors = []

    # 检查必需字段
    for field_name in REQUIRED_FIELDS:
        if field_name not in data:
            errors.append(f"Missing required field: {field_name}")

    # 检查字段类型（包括可选的门禁输出字段）
    for field_name, expected_type in FIELD_TYPES.items():
        if field_name in data:
            if not isinstance(data[field_name], expected_type):
                errors.append(
                    f"Field '{field_name}' has wrong type: "
                    f"expected {expected_type.__name__}, got {type(data[field_name]).__name__}"
                )

    # 检查 verified_test_results 子项
    if "verified_test_results" in data and isinstance(data["verified_test_results"], dict):
        vtr = data["verified_test_results"]
        for rf in VTR_REQUIRED_FIELDS:
            if rf not in vtr:
                errors.append(f"verified_test_results missing field: {rf}")
        if "total_verified_executed" in vtr and not isinstance(vtr["total_verified_executed"], int):
            errors.append(
                f"verified_test_results.total_verified_executed has wrong type: "
                f"expected int, got {type(vtr['total_verified_executed']).__name__}"
            )

    # 检查 packages 子项
    if "packages" in data and isinstance(data["packages"], list):
        for i, wp in enumerate(data["packages"]):
            if not isinstance(wp, dict):
                errors.append(f"packages[{i}] is not an object")
                continue
            for rf in WP_REQUIRED_FIELDS:
                if rf not in wp:
                    errors.append(f"packages[{i}] missing field: {rf}")
            if "final_status" in wp and wp["final_status"] not in WP_VALID_STATUSES:
                errors.append(
                    f"packages[{i}] has invalid final_status: {wp['final_status']}"
                )

    # 检查 confirmed_findings 子项
    if "confirmed_findings" in data and isinstance(data["confirmed_findings"], list):
        for i, f in enumerate(data["confirmed_findings"]):
            if not isinstance(f, dict):
                errors.append(f"confirmed_findings[{i}] is not an object")
                continue
            for rf in FINDING_REQUIRED_FIELDS:
                if rf not in f:
                    errors.append(f"confirmed_findings[{i}] missing field: {rf}")
            if "severity" in f and f["severity"] not in FINDING_VALID_SEVERITIES:
                errors.append(
                    f"confirmed_findings[{i}] has invalid severity: {f['severity']}"
                )

    # 检查 secret_findings 子项
    if "secret_findings" in data and isinstance(data["secret_findings"], list):
        for i, s in enumerate(data["secret_findings"]):
            if not isinstance(s, dict):
                errors.append(f"secret_findings[{i}] is not an object")
                continue
            for rf in SECRET_REQUIRED_FIELDS:
                if rf not in s:
                    errors.append(f"secret_findings[{i}] missing field: {rf}")

    # 检查 secret_findings 不含 secret_value 字段
    if "secret_findings" in data and isinstance(data["secret_findings"], list):
        for i, s in enumerate(data["secret_findings"]):
            if isinstance(s, dict) and "secret_value" in s:
                errors.append(
                    f"secret_findings[{i}] contains forbidden field: secret_value"
                )

    return len(errors) == 0, errors


def check_input(raw_text: str) -> Tuple[CheckResult, dict, bool]:
    """执行完整的输入校验。

    Returns:
        (check_result, parsed_data, input_valid)
        - 如果 JSON 无法解析，parsed_data 为空字典
    """
    # Step 1: JSON 可解析性
    success, data, error = validate_json(raw_text)
    if not success:
        result = CheckResult(
            check_id="INPUT-001",
            category="input_validation",
            status=FAIL,
            blocking=True,
            evidence=error,
            reason="Input JSON cannot be parsed; gate cannot proceed",
        )
        return result, {}, False

    # Step 2: Schema 校验
    schema_valid, errors = validate_schema(data)
    if not schema_valid:
        error_str = "; ".join(errors[:5])
        if len(errors) > 5:
            error_str += f" (and {len(errors) - 5} more errors)"
        result = CheckResult(
            check_id="INPUT-002",
            category="input_validation",
            status=FAIL,
            blocking=True,
            evidence=error_str,
            reason="Input does not conform to schema; gate cannot proceed",
        )
        return result, data, False

    # Step 3: 检查 secret_value 不存在（已在 validate_schema 中检查，这里做二次确认）
    has_secret_value = False
    for s in data.get("secret_findings", []):
        if isinstance(s, dict) and "secret_value" in s:
            has_secret_value = True
            break

    if has_secret_value:
        result = CheckResult(
            check_id="INPUT-003",
            category="input_validation",
            status=FAIL,
            blocking=True,
            evidence="secret_findings contains secret_value field(s)",
            reason="Input contains forbidden secret_value fields; gate cannot proceed",
        )
        return result, data, False

    # 全部通过
    result = CheckResult(
        check_id="INPUT-001",
        category="input_validation",
        status=PASS,
        blocking=False,
        evidence="JSON parsed successfully; all required data fields present and valid; no secret_value fields",
        reason="Input is valid and consumable by release gate",
    )
    return result, data, True

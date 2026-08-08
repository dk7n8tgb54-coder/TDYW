#!/usr/bin/env python
"""WP10 统一发布门禁主入口。

用法:
    python quality/release_gate/gate.py [input_json_path]

如果不提供 input_json_path，默认使用:
    quality/reports/acceptance/release_gate_input.json

输出保存到:
    quality/reports/release_gate/
    - release_gate_result.json   (机器可读)
    - release_gate_summary.md    (人工阅读)
    - check_results.csv          (逐项结果)

依赖：仅 Python 标准库（json/csv/os/sys/datetime）。不依赖 PyYAML 或 jsonschema。
策略配置使用 policy.json（JSON 格式），schema 校验使用手动规则（与 schemas/ 目录下 JSON Schema 文件保持一致）。
"""

import csv
import json
import os
import sys
from datetime import datetime

# 将当前文件所在目录加入 sys.path，使 checks 包可被导入
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

from checks import (
    CheckResult, GateResult,
    PASS, FAIL, BLOCKED, NOT_RUN, NOT_REVERIFIED,
    RELEASE_READY, NOT_READY, BLOCKED_GATE, INPUT_INVALID,
)
from checks.input_validation import check_input
from checks.work_packages import check_work_packages
from checks.security_findings import check_security_findings
from checks.required_evidence import check_required_evidence
from checks.release_decision import decide_gate_status


DEFAULT_INPUT = os.path.join(
    os.path.dirname(_THIS_DIR), "reports", "acceptance", "release_gate_input.json"
)
DEFAULT_OUTPUT_DIR = os.path.join(
    os.path.dirname(_THIS_DIR), "reports", "release_gate"
)


def load_policy() -> dict:
    """加载门禁策略（JSON 格式，不依赖 PyYAML）。"""
    policy_path = os.path.join(_THIS_DIR, "policy.json")
    with open(policy_path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_gate(input_path: str, output_dir: str = None) -> GateResult:
    """执行完整的发布门禁检查。

    Args:
        input_path: 输入 JSON 文件路径
        output_dir: 输出目录路径（默认 quality/reports/release_gate/）

    Returns:
        GateResult 对象
    """
    if output_dir is None:
        output_dir = DEFAULT_OUTPUT_DIR

    # 读取输入文件
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            raw_text = f.read()
    except FileNotFoundError:
        return GateResult(
            gate_status=INPUT_INVALID,
            input_valid=False,
            schema_valid=False,
            consumable_by_release_gate=False,
            can_release_now=False,
            checks=[],
            blocking_reasons=[f"Input file not found: {input_path}"],
            generated_at=datetime.now().isoformat(),
            input_file=input_path,
        )
    except UnicodeDecodeError as e:
        return GateResult(
            gate_status=INPUT_INVALID,
            input_valid=False,
            schema_valid=False,
            consumable_by_release_gate=False,
            can_release_now=False,
            checks=[],
            blocking_reasons=[f"Input file encoding error: {e}"],
            generated_at=datetime.now().isoformat(),
            input_file=input_path,
        )

    # 加载策略
    policy = load_policy()

    # Step 1: 输入校验
    input_result, data, input_valid = check_input(raw_text)
    all_checks = [input_result]

    schema_valid = input_valid

    if input_valid:
        # Step 2: 工作包检查
        wp_checks = check_work_packages(data, policy)
        all_checks.extend(wp_checks)

        # Step 3: 安全发现检查
        sec_checks = check_security_findings(data, policy)
        all_checks.extend(sec_checks)

        # Step 4: 必需证据检查（传入 project_root 用于文件存在性验证）
        project_root = os.path.dirname(os.path.dirname(_THIS_DIR))
        ev_checks = check_required_evidence(data, policy, project_root=project_root)
        all_checks.extend(ev_checks)

    # Step 5: 最终决策
    gate_result = decide_gate_status(all_checks, input_valid, schema_valid)
    gate_result.generated_at = datetime.now().isoformat()
    gate_result.input_file = input_path

    # 生成输出
    os.makedirs(output_dir, exist_ok=True)
    write_json_output(gate_result, output_dir)
    write_markdown_output(gate_result, output_dir)
    write_csv_output(gate_result, output_dir)

    return gate_result


def write_json_output(result: GateResult, output_dir: str):
    """生成 JSON 输出。"""
    output_path = os.path.join(output_dir, "release_gate_result.json")
    output_data = result.to_dict()

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)


def write_markdown_output(result: GateResult, output_dir: str):
    """生成 Markdown 摘要。"""
    output_path = os.path.join(output_dir, "release_gate_summary.md")

    lines = []
    lines.append("# WP10 统一发布门禁结果")
    lines.append("")
    lines.append(f"> 生成时间：{result.generated_at}")
    lines.append(f"> 输入文件：{result.input_file}")
    lines.append(f"> 门禁状态：**{result.gate_status}**")
    lines.append("")

    lines.append("## 状态汇总")
    lines.append("")
    lines.append("| 字段 | 值 |")
    lines.append("|------|-----|")
    lines.append(f"| schema_valid | {result.schema_valid} |")
    lines.append(f"| input_valid | {result.input_valid} |")
    lines.append(f"| consumable_by_release_gate | {result.consumable_by_release_gate} |")
    lines.append(f"| can_release_now | {result.can_release_now} |")
    lines.append(f"| gate_status | **{result.gate_status}** |")
    lines.append("")

    # 统计独立根因
    blocking_check_count = len(result.blocking_reasons)
    lines.append(f"> 注：以下 {blocking_check_count} 条为门禁检查项结果（含重复展开），不代表 {blocking_check_count} 个独立根因。")
    lines.append("")

    if result.blocking_reasons:
        lines.append("## 门禁检查项结果（阻断项）")
        lines.append("")
        for reason in result.blocking_reasons:
            lines.append(f"- {reason}")
        lines.append("")

    lines.append("## 检查结果明细")
    lines.append("")
    lines.append("| check_id | category | status | blocking | evidence | reason |")
    lines.append("|----------|----------|--------|----------|----------|--------|")
    for check in result.checks:
        evidence = check.evidence.replace("|", "\\|") if check.evidence else ""
        reason = check.reason.replace("|", "\\|") if check.reason else ""
        lines.append(
            f"| {check.check_id} | {check.category} | {check.status} | "
            f"{'是' if check.blocking else '否'} | {evidence} | {reason} |"
        )
    lines.append("")

    lines.append("## 状态模型说明")
    lines.append("")
    lines.append("### 检查项状态")
    lines.append("- PASS: 检查通过")
    lines.append("- FAIL: 检查失败（非阻断）")
    lines.append("- BLOCKED: 检查被阻断")
    lines.append("- NOT_RUN: 检查未执行")
    lines.append("- NOT_REVERIFIED: 历史结果未独立复验")
    lines.append("- NOT_APPLICABLE: 不适用于当前场景")
    lines.append("")
    lines.append("### 门禁最终状态")
    lines.append("- RELEASE_READY: 可发布")
    lines.append("- NOT_READY: 无基础设施阻断，但存在失败项")
    lines.append("- BLOCKED: 存在阻断项")
    lines.append("- INPUT_INVALID: 输入无效")
    lines.append("")
    lines.append("### 决策规则")
    lines.append("1. 输入无法解析或缺少必要字段 -> INPUT_INVALID")
    lines.append("2. 存在 CRITICAL 阻断、凭据未轮换、必需报告缺失 -> BLOCKED")
    lines.append("3. 无阻断但存在失败测试或 HIGH 发现 -> NOT_READY")
    lines.append("4. 全部强制检查 PASS -> RELEASE_READY")
    lines.append("5. NOT_RUN/NOT_REVERIFIED/BLOCKED 绝对不能转换为 PASS")
    lines.append("6. 门禁必须正常读取含有问题的有效报告，并根据问题输出 BLOCKED")
    lines.append("")
    lines.append("### 凭据轮换闭环")
    lines.append("- secret_findings 使用显式 `rotation_status` 字段")
    lines.append("- `pending` / `unrotated` / `needs_rotation` -> BLOCKED")
    lines.append("- `completed` / `verified` / `not_required` -> PASS")
    lines.append("- 字段缺失时回退到推断逻辑（向后兼容）")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_csv_output(result: GateResult, output_dir: str):
    """生成 CSV 输出。"""
    output_path = os.path.join(output_dir, "check_results.csv")

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["check_id", "category", "status", "blocking", "evidence", "reason"])
        for check in result.checks:
            writer.writerow([
                check.check_id,
                check.category,
                check.status,
                "True" if check.blocking else "False",
                check.evidence,
                check.reason,
            ])


def main():
    input_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_INPUT
    result = run_gate(input_path)

    print(f"Gate Status: {result.gate_status}")
    print(f"Input Valid: {result.input_valid}")
    print(f"Consumable: {result.consumable_by_release_gate}")
    print(f"Can Release: {result.can_release_now}")
    print(f"Checks: {len(result.checks)}")
    if result.blocking_reasons:
        print(f"Blocking checks: {len(result.blocking_reasons)} (expanded, not independent root causes)")
        for reason in result.blocking_reasons:
            print(f"  - {reason}")

    return 0 if result.gate_status == RELEASE_READY else 1


if __name__ == "__main__":
    sys.exit(main())

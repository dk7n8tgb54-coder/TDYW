"""发布决策模块的单元测试。

测试覆盖：
1. 所有强制检查通过（含已验证结构化证据） -> RELEASE_READY
2. 存在 CRITICAL -> BLOCKED
3. NOT_RUN 不得算 PASS
4. NOT_REVERIFIED 不得算 PASS
5. 存在 HIGH 但无阻断 -> NOT_READY
6. 有效但被阻断的输入（端到端）
7. 无效输入 -> INPUT_INVALID
8. all_pass_no_evidence: WP 全 PASS 但无结构化证据 -> BLOCKED
9. CRITICAL blocking=false 仍然阻断
10. PASS + blocking_findings>0 -> BLOCKED
11. 凭据 rotation_status=completed 可闭环
12. 凭据 rotation_status=pending 阻断
13. P0: CRITICAL remediation_status=Unfixed 阻断（不是 fixed）
14. P0: CRITICAL remediation_status="not fixed" 阻断
15. P0: 不存在的证据路径阻断
16. P0: 缺少必需证据字段阻断
17. P0: 绝对路径和路径穿越阻断
"""

import json
import os
import sys
import unittest

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_GATE_DIR = os.path.dirname(_THIS_DIR)
if _GATE_DIR not in sys.path:
    sys.path.insert(0, _GATE_DIR)

# Project root = parent of quality/
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_GATE_DIR))

from checks import (
    CheckResult, GateResult,
    PASS, FAIL, BLOCKED, NOT_RUN, NOT_REVERIFIED,
    RELEASE_READY, NOT_READY, BLOCKED_GATE, INPUT_INVALID,
)
from checks.release_decision import decide_gate_status
from checks.input_validation import check_input
from checks.work_packages import check_work_packages
from checks.security_findings import check_security_findings
from checks.required_evidence import check_required_evidence

FIXTURES_DIR = os.path.join(_THIS_DIR, "fixtures")
POLICY_PATH = os.path.join(_GATE_DIR, "policy.json")

with open(POLICY_PATH, "r", encoding="utf-8") as f:
    POLICY = json.load(f)


def load_fixture(name: str) -> str:
    path = os.path.join(FIXTURES_DIR, name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def run_full_gate(raw_text: str, project_root: str = None):
    """端到端运行门禁检查（不写文件）。"""
    input_result, data, input_valid = check_input(raw_text)
    all_checks = [input_result]
    if input_valid:
        all_checks.extend(check_work_packages(data, POLICY))
        all_checks.extend(check_security_findings(data, POLICY))
        all_checks.extend(check_required_evidence(data, POLICY, project_root=project_root or _PROJECT_ROOT))
    return decide_gate_status(all_checks, input_valid, schema_valid=input_valid)


class TestReleaseDecision(unittest.TestCase):

    def test_all_pass_releases_ready(self):
        """所有强制检查通过（含已验证结构化证据）时才能 RELEASE_READY。"""
        checks = [
            CheckResult("INPUT-001", "input_validation", PASS, False, "ok", "valid"),
            CheckResult("WP-WP1", "work_packages", PASS, False, "PASS", "ok"),
            CheckResult("WP-WP5", "work_packages", PASS, False, "PASS", "ok"),
            CheckResult("SEC-001", "security_findings", PASS, False, "none", "ok"),
            CheckResult("SEC-002", "security_findings", PASS, False, "none", "ok"),
            CheckResult("SEC-003", "security_findings", PASS, False, "none", "ok"),
            CheckResult("EVID-WP6-REPORT", "required_evidence", PASS, False, "ok", "ok"),
            CheckResult("EVID-PERF-LOAD", "required_evidence", PASS, False, "ok", "ok"),
            CheckResult("EVID-DR-RESTORE", "required_evidence", PASS, False, "ok", "ok"),
            CheckResult("EVID-WP-REVERIFICATION", "required_evidence", PASS, False, "ok", "ok"),
        ]
        result = decide_gate_status(checks, input_valid=True, schema_valid=True)

        self.assertEqual(result.gate_status, RELEASE_READY)
        self.assertTrue(result.can_release_now)
        self.assertEqual(result.blocking_reasons, [])

    def test_critical_finding_blocks(self):
        """存在 CRITICAL 阻断 -> BLOCKED。"""
        checks = [
            CheckResult("INPUT-001", "input_validation", PASS, False, "ok", "valid"),
            CheckResult("WP-WP5", "work_packages", BLOCKED, True, "FAIL", "租户隔离漏洞"),
            CheckResult("SEC-001", "security_findings", BLOCKED, True, "2 CRITICAL", "阻断"),
        ]
        result = decide_gate_status(checks, input_valid=True, schema_valid=True)

        self.assertEqual(result.gate_status, BLOCKED_GATE)
        self.assertFalse(result.can_release_now)
        self.assertTrue(len(result.blocking_reasons) > 0)

    def test_not_run_cannot_be_pass(self):
        """NOT_RUN 不得算 PASS。"""
        checks = [
            CheckResult("INPUT-001", "input_validation", PASS, False, "ok", "valid"),
            CheckResult("WP-WP9", "work_packages", BLOCKED, True, "NOT_RUN", "负载测试未执行"),
        ]
        result = decide_gate_status(checks, input_valid=True, schema_valid=True)

        self.assertEqual(result.gate_status, BLOCKED_GATE)
        self.assertFalse(result.can_release_now)

    def test_not_reverified_cannot_be_pass(self):
        """NOT_REVERIFIED 不得算 PASS。"""
        checks = [
            CheckResult("INPUT-001", "input_validation", PASS, False, "ok", "valid"),
            CheckResult("WP-WP2", "work_packages", BLOCKED, True, "NOT_REVERIFIED", "未复验"),
        ]
        result = decide_gate_status(checks, input_valid=True, schema_valid=True)

        self.assertEqual(result.gate_status, BLOCKED_GATE)
        self.assertFalse(result.can_release_now)

    def test_high_finding_not_ready(self):
        """存在 HIGH 发现但无阻断 -> NOT_READY。"""
        checks = [
            CheckResult("INPUT-001", "input_validation", PASS, False, "ok", "valid"),
            CheckResult("WP-WP1", "work_packages", PASS, False, "PASS", "ok"),
            CheckResult("SEC-001", "security_findings", PASS, False, "none", "ok"),
            CheckResult("SEC-002", "security_findings", FAIL, False, "1 HIGH", "非阻断但不可发布"),
            CheckResult("SEC-003", "security_findings", PASS, False, "none", "ok"),
        ]
        result = decide_gate_status(checks, input_valid=True, schema_valid=True)

        self.assertEqual(result.gate_status, NOT_READY)
        self.assertFalse(result.can_release_now)

    def test_invalid_input(self):
        """无效输入 -> INPUT_INVALID。"""
        checks = [
            CheckResult("INPUT-001", "input_validation", FAIL, True, "parse error", "invalid"),
        ]
        result = decide_gate_status(checks, input_valid=False, schema_valid=False)

        self.assertEqual(result.gate_status, INPUT_INVALID)
        self.assertFalse(result.consumable_by_release_gate)
        self.assertFalse(result.can_release_now)

    def test_end_to_end_blocked(self):
        """端到端：有效但被阻断的输入 -> BLOCKED。"""
        raw = load_fixture("valid_blocked.json")
        result = run_full_gate(raw)

        self.assertEqual(result.gate_status, BLOCKED_GATE)
        self.assertTrue(result.input_valid)
        self.assertTrue(result.consumable_by_release_gate)
        self.assertFalse(result.can_release_now)

        reasons_text = " ".join(result.blocking_reasons)
        self.assertIn("WP5", reasons_text)
        self.assertIn("SS-001", reasons_text)
        self.assertIn("WP6", reasons_text)
        self.assertIn("WP2", reasons_text)

    def test_end_to_end_all_pass(self):
        """端到端：全部通过（含已验证结构化证据，文件存在） -> RELEASE_READY。"""
        raw = load_fixture("all_pass.json")
        result = run_full_gate(raw, project_root=_PROJECT_ROOT)

        self.assertEqual(result.gate_status, RELEASE_READY)
        self.assertTrue(result.can_release_now)

    def test_end_to_end_no_evidence_blocked(self):
        """P0 核心：WP 全 PASS 但无结构化证据 -> BLOCKED（不可被全局计数欺骗）。"""
        raw = load_fixture("all_pass_no_evidence.json")
        result = run_full_gate(raw, project_root=_PROJECT_ROOT)

        self.assertNotEqual(result.gate_status, RELEASE_READY)
        self.assertFalse(result.can_release_now)

        reasons_text = " ".join(result.blocking_reasons)
        self.assertIn("permission_audit", reasons_text)
        self.assertIn("performance_load", reasons_text)
        self.assertIn("disaster_recovery_restore", reasons_text)

    def test_end_to_end_critical_blocking_false(self):
        """P1：CRITICAL blocking=false 仍然阻断。"""
        raw = load_fixture("critical_blocking_false.json")
        result = run_full_gate(raw, project_root=_PROJECT_ROOT)

        self.assertEqual(result.gate_status, BLOCKED_GATE)
        self.assertFalse(result.can_release_now)

        sec001 = [c for c in result.checks if c.check_id == "SEC-001"]
        self.assertEqual(len(sec001), 1)
        self.assertEqual(sec001[0].status, BLOCKED)

    def test_end_to_end_pass_with_blocking_findings(self):
        """P1：PASS + blocking_findings>0 -> BLOCKED。"""
        raw = load_fixture("pass_with_blocking_findings.json")
        result = run_full_gate(raw, project_root=_PROJECT_ROOT)

        self.assertNotEqual(result.gate_status, RELEASE_READY)
        self.assertFalse(result.can_release_now)

        wp5 = [c for c in result.checks if c.check_id == "WP-WP5"]
        self.assertEqual(len(wp5), 1)
        self.assertEqual(wp5[0].status, BLOCKED)
        self.assertIn("contradicts", wp5[0].reason)

    def test_end_to_end_invalid_json(self):
        """端到端：无效 JSON -> INPUT_INVALID。"""
        raw = load_fixture("invalid_json.txt")
        result = run_full_gate(raw)
        self.assertEqual(result.gate_status, INPUT_INVALID)

    def test_end_to_end_missing_fields(self):
        """端到端：缺少字段 -> INPUT_INVALID。"""
        raw = load_fixture("missing_fields.json")
        result = run_full_gate(raw)
        self.assertEqual(result.gate_status, INPUT_INVALID)

    def test_secret_rotation_completed(self):
        """凭据 rotation_status=completed 可闭环 -> PASS。"""
        data = {
            "schema_version": "1.0", "generated_at": "2026-08-08", "git_commit": "abc",
            "worktree_status": "test", "packages": [], "confirmed_findings": [],
            "secret_findings": [
                {"id": "SS-001", "type": "password", "location": "Git commit eb8ecf00",
                 "git_commit": "eb8ecf00", "rotation_status": "completed"}
            ],
            "verified_test_results": {"total_verified_executed": 0},
        }
        raw = json.dumps(data, ensure_ascii=False)
        result = run_full_gate(raw)

        sec003 = [c for c in result.checks if c.check_id == "SEC-003"]
        self.assertEqual(len(sec003), 1)
        self.assertEqual(sec003[0].status, PASS)

    def test_secret_rotation_pending_blocks(self):
        """凭据 rotation_status=pending 阻断 -> BLOCKED。"""
        data = {
            "schema_version": "1.0", "generated_at": "2026-08-08", "git_commit": "abc",
            "worktree_status": "test", "packages": [], "confirmed_findings": [],
            "secret_findings": [
                {"id": "SS-001", "type": "password", "location": "Git commit eb8ecf00",
                 "rotation_status": "pending"}
            ],
            "verified_test_results": {"total_verified_executed": 0},
        }
        raw = json.dumps(data, ensure_ascii=False)
        result = run_full_gate(raw)

        sec003 = [c for c in result.checks if c.check_id == "SEC-003"]
        self.assertEqual(len(sec003), 1)
        self.assertEqual(sec003[0].status, BLOCKED)
        self.assertTrue(sec003[0].blocking)

    # === P0 回归测试 ===

    def test_unfixed_critical_blocks(self):
        """P0: CRITICAL remediation_status=Unfixed 必须阻断（不包含 fixed）。"""
        raw = load_fixture("unfixed_critical.json")
        result = run_full_gate(raw, project_root=_PROJECT_ROOT)

        self.assertEqual(result.gate_status, BLOCKED_GATE)
        self.assertFalse(result.can_release_now)

        sec001 = [c for c in result.checks if c.check_id == "SEC-001"]
        self.assertEqual(len(sec001), 1)
        self.assertEqual(sec001[0].status, BLOCKED)
        self.assertIn("F-001", sec001[0].evidence)

    def test_not_fixed_critical_blocks(self):
        """P0: CRITICAL remediation_status='not fixed' 必须阻断。"""
        raw = load_fixture("not_fixed_critical.json")
        result = run_full_gate(raw, project_root=_PROJECT_ROOT)

        self.assertEqual(result.gate_status, BLOCKED_GATE)
        self.assertFalse(result.can_release_now)

        sec001 = [c for c in result.checks if c.check_id == "SEC-001"]
        self.assertEqual(len(sec001), 1)
        self.assertEqual(sec001[0].status, BLOCKED)

    def test_nonexistent_evidence_paths_block(self):
        """P0: 证据路径指向不存在的文件 -> BLOCKED。"""
        raw = load_fixture("nonexistent_evidence_paths.json")
        result = run_full_gate(raw, project_root=_PROJECT_ROOT)

        self.assertNotEqual(result.gate_status, RELEASE_READY)
        self.assertFalse(result.can_release_now)

        # 所有三个证据检查都应该 BLOCKED
        reasons_text = " ".join(result.blocking_reasons)
        self.assertIn("does not exist", reasons_text)

    def test_missing_evidence_fields_block(self):
        """P0: 证据条目缺少必需字段 -> BLOCKED。"""
        raw = load_fixture("missing_evidence_fields.json")
        result = run_full_gate(raw, project_root=_PROJECT_ROOT)

        self.assertNotEqual(result.gate_status, RELEASE_READY)
        self.assertFalse(result.can_release_now)

        reasons_text = " ".join(result.blocking_reasons)
        self.assertIn("missing required fields", reasons_text)

    def test_absolute_or_traversal_paths_block(self):
        """P0: 绝对路径和路径穿越 -> BLOCKED。"""
        raw = load_fixture("traversal_evidence_paths.json")
        result = run_full_gate(raw, project_root=_PROJECT_ROOT)

        self.assertNotEqual(result.gate_status, RELEASE_READY)
        self.assertFalse(result.can_release_now)

        reasons_text = " ".join(result.blocking_reasons)
        # 应该检测到路径穿越和绝对路径
        has_traversal = "traversal" in reasons_text.lower() or "absolute" in reasons_text.lower()
        self.assertTrue(has_traversal, f"Expected traversal or absolute path error, got: {reasons_text}")


if __name__ == "__main__":
    unittest.main()

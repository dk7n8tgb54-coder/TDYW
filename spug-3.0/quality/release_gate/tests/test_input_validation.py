"""输入校验模块的单元测试。

测试覆盖：
1. 有效但被阻断的输入 -> input_valid=true
2. 无效 JSON -> INPUT_INVALID
3. 缺少必要字段 -> INPUT_INVALID
4. 存在 secret_value 字段 -> INPUT_INVALID
5. 门禁输出字段不是必需字段 -> 有无均可
"""

import json
import os
import sys
import unittest

# 将 release_gate 目录加入 sys.path
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_GATE_DIR = os.path.dirname(_THIS_DIR)
if _GATE_DIR not in sys.path:
    sys.path.insert(0, _GATE_DIR)

from checks.input_validation import check_input, validate_json, validate_schema
from checks import INPUT_INVALID, PASS, FAIL


FIXTURES_DIR = os.path.join(_THIS_DIR, "fixtures")


def load_fixture(name: str) -> str:
    """读取 fixture 文件的原始文本。"""
    path = os.path.join(FIXTURES_DIR, name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class TestInputValidation(unittest.TestCase):

    def test_valid_blocked_input(self):
        """有效但被阻断的输入：JSON 可解析，字段完整，input_valid=true。"""
        raw = load_fixture("valid_blocked.json")
        result, data, input_valid = check_input(raw)

        self.assertTrue(input_valid, "有效输入应返回 input_valid=True")
        self.assertEqual(result.status, PASS)
        self.assertFalse(result.blocking)
        self.assertIn("packages", data)
        self.assertIn("confirmed_findings", data)
        self.assertIn("secret_findings", data)

    def test_invalid_json(self):
        """无效 JSON：无法解析，input_valid=false。"""
        raw = load_fixture("invalid_json.txt")
        result, data, input_valid = check_input(raw)

        self.assertFalse(input_valid, "无效 JSON 应返回 input_valid=False")
        self.assertEqual(result.status, FAIL)
        self.assertTrue(result.blocking)
        self.assertEqual(data, {})

    def test_missing_required_fields(self):
        """缺少必要字段：input_valid=false。"""
        raw = load_fixture("missing_fields.json")
        result, data, input_valid = check_input(raw)

        self.assertFalse(input_valid, "缺少字段应返回 input_valid=False")
        self.assertEqual(result.status, FAIL)
        self.assertTrue(result.blocking)
        # 应该能解析 JSON 但 schema 校验失败
        self.assertIn("schema_version", data)

    def test_secret_value_forbidden(self):
        """包含 secret_value 字段：input_valid=false。"""
        data = {
            "schema_version": "1.0",
            "generated_at": "2026-08-08",
            "git_commit": "abc",
            "worktree_status": "test",
            "packages": [],
            "confirmed_findings": [],
            "secret_findings": [
                {"id": "SS-001", "type": "password",
                 "location": "test",
                 "secret_value": "REDACTED"}
            ],
            "verified_test_results": {"total_verified_executed": 0},
        }
        raw = json.dumps(data, ensure_ascii=False)
        result, parsed_data, input_valid = check_input(raw)

        self.assertFalse(input_valid, "包含 secret_value 应返回 input_valid=False")
        self.assertEqual(result.status, FAIL)
        self.assertTrue(result.blocking)
        self.assertIn("secret_value", result.evidence)

    def test_gate_output_fields_not_required(self):
        """门禁输出字段（schema_valid 等）不是必需字段。"""
        data = {
            "schema_version": "1.0",
            "generated_at": "2026-08-08",
            "git_commit": "abc",
            "worktree_status": "test",
            "packages": [],
            "confirmed_findings": [],
            "secret_findings": [],
            "verified_test_results": {"total_verified_executed": 0},
        }
        raw = json.dumps(data, ensure_ascii=False)
        result, parsed_data, input_valid = check_input(raw)

        self.assertTrue(input_valid, "不包含门禁输出字段也应 input_valid=True")
        self.assertEqual(result.status, PASS)

    def test_validate_json_valid(self):
        """validate_json 能正确解析有效 JSON。"""
        success, data, error = validate_json('{"key": "value"}')
        self.assertTrue(success)
        self.assertEqual(data, {"key": "value"})
        self.assertEqual(error, "")

    def test_validate_json_invalid(self):
        """validate_json 对无效 JSON 返回错误。"""
        success, data, error = validate_json('{invalid}')
        self.assertFalse(success)
        self.assertEqual(data, {})
        self.assertIn("parse error", error.lower())

    def test_validate_schema_missing_field(self):
        """validate_schema 检测到缺失必需数据字段。"""
        is_valid, errors = validate_schema({"schema_version": "1.0"})
        self.assertFalse(is_valid)
        self.assertTrue(any("generated_at" in e for e in errors))

    def test_validate_schema_wrong_type(self):
        """validate_schema 检测到字段类型错误。"""
        data = {
            "schema_version": "1.0",
            "generated_at": "2026-08-08",
            "git_commit": "abc",
            "worktree_status": "test",
            "packages": "should_be_list",
            "confirmed_findings": [],
            "secret_findings": [],
            "verified_test_results": {"total_verified_executed": 0},
        }
        is_valid, errors = validate_schema(data)
        self.assertFalse(is_valid)
        self.assertTrue(any("packages" in e and "wrong type" in e for e in errors))

    def test_validate_schema_missing_verified_test_results(self):
        """validate_schema 检测到缺少 verified_test_results。"""
        data = {
            "schema_version": "1.0",
            "generated_at": "2026-08-08",
            "git_commit": "abc",
            "worktree_status": "test",
            "packages": [],
            "confirmed_findings": [],
            "secret_findings": [],
        }
        is_valid, errors = validate_schema(data)
        self.assertFalse(is_valid)
        self.assertTrue(any("verified_test_results" in e for e in errors))


if __name__ == "__main__":
    unittest.main()

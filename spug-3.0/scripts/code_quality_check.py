#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
【任务5.1】代码质量检查工具
检查项目代码是否符合规范要求。历史代码通过 baseline 增量治理，
新增代码和被修改函数使用更严格的阈值。
"""

import os
import sys
import ast
import argparse
import json
import re
import subprocess
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Tuple


class CodeQualityChecker:
    """代码质量检查器"""

    # 历史代码的保底阈值。超过这些阈值仍然报告问题。
    LEGACY_MAX_FILE_LINES = 1000
    LEGACY_MAX_FUNCTION_LINES = 250
    LEGACY_MAX_COMPLEXITY = 25

    # 新增代码和被修改函数的收紧阈值。
    NEW_MAX_FILE_LINES = 800
    NEW_MAX_FUNCTION_LINES = 120
    NEW_MAX_COMPLEXITY = 15

    DEFAULT_BASELINE = Path("quality/baselines/code_quality_baseline.json")

    def __init__(self, root_dir: str, baseline_path: str | None = None,
                 write_baseline: bool = False, frontend_only: bool = False,
                 backend_only: bool = False):
        self.root_dir = Path(root_dir)
        self.issues = []
        self.stats = defaultdict(int)
        self.write_baseline = write_baseline
        self.frontend_only = frontend_only
        self.backend_only = backend_only
        self.baseline_path = self.root_dir / (baseline_path or self.DEFAULT_BASELINE)
        self.baseline = self._load_baseline()
        self.changed_ranges = self._load_changed_ranges()
        self.observed_files = {}
        self.observed_functions = []

    def _load_baseline(self) -> dict:
        """读取历史问题基线；基线不存在时从空基线开始。"""
        if not self.baseline_path.exists():
            return {"version": 1, "files": {}, "functions": []}
        try:
            with self.baseline_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            data.setdefault("version", 1)
            data.setdefault("files", {})
            data.setdefault("functions", [])
            return data
        except (OSError, json.JSONDecodeError) as exc:
            print(f"警告: 无法读取代码质量基线 {self.baseline_path}: {exc}")
            return {"version": 1, "files": {}, "functions": []}

    def _load_changed_ranges(self) -> dict[str, list[tuple[int, int]]]:
        """读取相对 HEAD 的新增/修改行，用于增量门禁。"""
        changed = defaultdict(list)
        try:
            result = subprocess.run(
                ["git", "diff", "--unified=0", "--no-color", "HEAD", "--"],
                cwd=self.root_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            current_file = None
            for line in (result.stdout or "").splitlines():
                if line.startswith("+++ b/"):
                    current_file = line[6:].replace("\\", "/")
                elif current_file and line.startswith("@@"):
                    match = re.search(r"\+(\d+)(?:,(\d+))?", line)
                    if match:
                        start = int(match.group(1))
                        count = int(match.group(2) or 1)
                        changed[current_file].append((start, start + max(count - 1, 0)))

            status = subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=all"],
                cwd=self.root_dir,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            for line in (status.stdout or "").splitlines():
                if line.startswith("?? "):
                    changed[line[3:].replace("\\", "/")].append((1, 10**9))
        except OSError:
            # 在源码压缩包或没有 Git 的环境中按全量检查执行。
            return {}
        return dict(changed)

    @staticmethod
    def _rel_path(path: Path) -> str:
        return str(path).replace("\\", "/")

    def _is_changed_file(self, rel_path: str) -> bool:
        return rel_path in self.changed_ranges

    def _line_changed(self, rel_path: str, start: int, end: int) -> bool:
        return any(start <= changed_end and end >= changed_start
                   for changed_start, changed_end in self.changed_ranges.get(rel_path, []))

    def _baseline_file_allows(self, rel_path: str, code_lines: int) -> bool:
        entry = self.baseline.get("files", {}).get(rel_path)
        return bool(entry and code_lines <= int(entry.get("code_lines", 0)))

    def _baseline_function_allows(self, rel_path: str, line: int, kind: str,
                                  name: str | None = None,
                                  func_lines: int | None = None,
                                  complexity: int | None = None) -> bool:
        candidates = []
        for entry in self.baseline.get("functions", []):
            if entry.get("file") != rel_path:
                continue
            if entry.get("kind", kind) != kind:
                continue
            if entry.get("line") == line:
                candidates.insert(0, entry)
            elif entry.get("name") == name:
                candidates.append(entry)
        for entry in candidates:
            if entry.get("name") and entry.get("line") != line:
                if entry.get("name") != name:
                    continue
            if (func_lines is not None and entry.get("code_lines") is not None
                    and int(entry.get("code_lines", 0)) > 0
                    and func_lines > int(entry["code_lines"])):
                return False
            if (complexity is not None and entry.get("complexity") is not None
                    and complexity > int(entry["complexity"])):
                return False
            return True
        return False

    def _remember_file(self, rel_path: str, code_lines: int):
        self.observed_files[rel_path] = {"code_lines": code_lines}

    def _remember_function(self, rel_path: str, line: int, kind: str,
                           code_lines: int, complexity: int | None = None,
                           name: str | None = None):
        entry = {
            "file": rel_path,
            "line": line,
            "kind": kind,
            "code_lines": code_lines,
            "complexity": complexity,
        }
        if name:
            entry["name"] = name
        self.observed_functions.append(entry)

    def _write_baseline(self):
        """写入当前超过新阈值的现状，供历史代码增量治理使用。"""
        files = {
            path: value for path, value in self.observed_files.items()
            if value["code_lines"] > self.NEW_MAX_FILE_LINES
        }
        functions = [
            value for value in self.observed_functions
            if value["code_lines"] > self.NEW_MAX_FUNCTION_LINES
            or (value["complexity"] is not None
                and value["complexity"] > self.NEW_MAX_COMPLEXITY)
        ]
        self.baseline_path.parent.mkdir(parents=True, exist_ok=True)
        with self.baseline_path.open("w", encoding="utf-8", newline="\n") as f:
            json.dump({
                "version": 1,
                "generated_by": "scripts/code_quality_check.py --write-baseline",
                "policy": {
                    "legacy": {
                        "max_file_lines": self.LEGACY_MAX_FILE_LINES,
                        "max_function_lines": self.LEGACY_MAX_FUNCTION_LINES,
                        "max_complexity": self.LEGACY_MAX_COMPLEXITY,
                    },
                    "new": {
                        "max_file_lines": self.NEW_MAX_FILE_LINES,
                        "max_function_lines": self.NEW_MAX_FUNCTION_LINES,
                        "max_complexity": self.NEW_MAX_COMPLEXITY,
                    },
                },
                "files": files,
                "functions": functions,
            }, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"已写入代码质量基线: {self.baseline_path}")

    def _count_code_lines(self, content: str, is_python: bool = True) -> tuple[int, int]:
        """统计有效代码行数（排除注释和空行）。

        Args:
            content: 文件内容
            is_python: 是否为Python文件

        Returns:
            tuple: (总行数, 有效代码行数)
        """
        lines = content.split('\n')
        total_lines = len(lines)
        code_lines = 0

        in_multiline_comment = False
        multiline_start = None

        for line in lines:
            stripped = line.strip()

            # 跳过空行
            if not stripped:
                continue

            if is_python:
                # Python: 处理多行字符串（文档字符串）
                if in_multiline_comment:
                    # 检查多行字符串结束
                    if multiline_start in stripped:
                        in_multiline_comment = False
                        multiline_start = None
                    continue

                # 检测多行字符串开始
                if stripped.startswith('"""') or stripped.startswith("'''"):
                    quote = stripped[:3]
                    if stripped.count(quote) >= 2:
                        # 单行文档字符串，视为注释
                        continue
                    else:
                        in_multiline_comment = True
                        multiline_start = quote
                        continue

                # 跳过单行注释
                if stripped.startswith('#'):
                    continue
            else:
                # JavaScript: 处理多行注释 /* */
                if in_multiline_comment:
                    if '*/' in stripped:
                        in_multiline_comment = False
                    continue

                # 检测多行注释开始
                if stripped.startswith('/*'):
                    if '*/' in stripped:
                        # 单行 /* ... */
                        continue
                    else:
                        in_multiline_comment = True
                        continue

                # 跳过单行注释
                if stripped.startswith('//') or stripped.startswith('/*'):
                    continue

            # 有效代码行
            code_lines += 1

        return total_lines, code_lines

    def check_all(self) -> bool:
        """运行所有检查"""
        print("=" * 60)
        print("       代码质量检查工具 - 任务5.1")
        print("=" * 60)
        print()

        if not self.backend_only:
            print("[1/2] 检查前端代码...")
            print("-" * 60)
            self._check_frontend()

        if not self.frontend_only:
            print()
            print("[2/2] 检查后端代码...")
            print("-" * 60)
            self._check_backend()

        print()
        self._print_summary()

        if self.write_baseline:
            self._write_baseline()
            return True
        return len(self.issues) == 0

    def _check_frontend(self):
        """检查前端代码"""
        web_dir = self.root_dir / "spug_web" / "src"
        if not web_dir.exists():
            print(f"  跳过: 前端目录不存在: {web_dir}")
            return

        js_files = list(web_dir.rglob("*.js")) + list(web_dir.rglob("*.jsx"))

        for file_path in js_files:
            self._check_js_file(file_path)

        print(f"  检查了 {len(js_files)} 个前端文件")

    def _check_js_file(self, file_path: Path):
        """检查单个 JS 文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            rel_path = file_path.relative_to(self.root_dir)

            # 统计代码行数（排除注释和空行）
            total_lines, code_lines = self._count_code_lines(content, is_python=False)
            rel_path_text = self._rel_path(rel_path)
            self._remember_file(rel_path_text, code_lines)

            # 检查有效代码行数
            file_limit = (self.NEW_MAX_FILE_LINES
                          if self._is_changed_file(rel_path_text)
                          else self.LEGACY_MAX_FILE_LINES)
            if (code_lines > file_limit
                    and not self._baseline_file_allows(rel_path_text, code_lines)):
                self.issues.append({
                    'type': 'error',
                    'file': str(rel_path),
                    'line': 1,
                    'message': f'有效代码行数超标: {code_lines} 行 (总行数: {total_lines}, 限制: {file_limit})',
                    'category': 'file_length'
                })
                self.stats['frontend_file_too_long'] += 1

            # 检查函数行数 (简单的函数检测)
            function_pattern = r'(?:function\s+\w+|const\s+\w+\s*=\s*(?:async\s*)?\(|\w+\s*:\s*(?:async\s*)?\([^)]*\)\s*=>)'
            functions = re.finditer(function_pattern, content)

            for match in functions:
                start_pos = match.start()
                # 找到函数体的开始
                brace_start = content.find('{', start_pos)
                if brace_start == -1:
                    continue

                # 计算函数行数
                line_num = content[:start_pos].count('\n') + 1

                # 简单估计函数体大小（实际应该解析AST）
                end_pos = self._find_function_end(content, brace_start)
                if end_pos:
                    func_lines = content[brace_start:end_pos].count('\n')
                    self._remember_function(rel_path_text, line_num, 'javascript', func_lines)
                    function_changed = self._line_changed(rel_path_text, line_num,
                                                           line_num + func_lines)
                    function_limit = (self.NEW_MAX_FUNCTION_LINES
                                      if function_changed
                                      else self.LEGACY_MAX_FUNCTION_LINES)
                    baseline_allows = (not function_changed and
                                       self._baseline_function_allows(
                                           rel_path_text, line_num, 'javascript',
                                           func_lines=func_lines))
                    if func_lines > function_limit and not baseline_allows:
                        self.issues.append({
                            'type': 'error',
                            'file': str(rel_path),
                            'line': line_num,
                            'message': f'函数行数超标: ~{func_lines} 行 (限制: {function_limit})',
                            'category': 'function_length'
                        })
                        self.stats['frontend_function_too_long'] += 1

        except Exception as e:
            print(f"  检查失败 {file_path}: {e}")

    def _find_function_end(self, content: str, start: int) -> int:
        """简单查找函数结束位置"""
        brace_count = 0
        in_string = False
        string_char = None

        for i in range(start, len(content)):
            char = content[i]

            # 处理字符串
            if char in ('"', "'", '`') and not in_string:
                in_string = True
                string_char = char
            elif char == string_char and in_string:
                # 检查是否是转义
                if i > 0 and content[i-1] != '\\':
                    in_string = False
                    string_char = None

            if in_string:
                continue

            # 处理大括号
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    return i

        return None

    def _check_backend(self):
        """检查后端代码"""
        api_dir = self.root_dir / "spug_api"
        if not api_dir.exists():
            print(f"警告: 后端目录不存在: {api_dir}")
            return

        # 检查 apps, libs, consumer 目录
        check_dirs = ['apps', 'libs', 'consumer']
        py_files = []

        for dir_name in check_dirs:
            dir_path = api_dir / dir_name
            if dir_path.exists():
                py_files.extend(dir_path.rglob("*.py"))

        for file_path in py_files:
            self._check_py_file(file_path)

        print(f"  检查了 {len(py_files)} 个后端文件")

    def _check_py_file(self, file_path: Path):
        """检查单个 Python 文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            rel_path = file_path.relative_to(self.root_dir)

            # 统计代码行数（排除注释和空行）
            total_lines, code_lines = self._count_code_lines(content, is_python=True)
            rel_path_text = self._rel_path(rel_path)
            self._remember_file(rel_path_text, code_lines)

            # 检查有效代码行数（测试文件放行行数限制，仅业务代码受约束）
            file_limit = (self.NEW_MAX_FILE_LINES
                          if self._is_changed_file(rel_path_text)
                          else self.LEGACY_MAX_FILE_LINES)
            if (not self._is_test_file(file_path)
                    and code_lines > file_limit
                    and not self._baseline_file_allows(rel_path_text, code_lines)):
                self.issues.append({
                    'type': 'error',
                    'file': str(rel_path),
                    'line': 1,
                    'message': f'有效代码行数超标: {code_lines} 行 (总行数: {total_lines}, 限制: {file_limit})',
                    'category': 'file_length'
                })
                self.stats['backend_file_too_long'] += 1

            # 使用 AST 分析函数
            try:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        func_lines = node.end_lineno - node.lineno + 1
                        complexity = self._calculate_complexity(node)
                        self._remember_function(rel_path_text, node.lineno, 'python',
                                                func_lines, complexity, node.name)
                        function_changed = self._line_changed(
                            rel_path_text, node.lineno, node.end_lineno)
                        function_limit = (self.NEW_MAX_FUNCTION_LINES
                                          if function_changed
                                          else self.LEGACY_MAX_FUNCTION_LINES)
                        baseline_allows_length = (
                            not function_changed
                            and self._baseline_function_allows(
                                rel_path_text, node.lineno, 'python', node.name,
                                func_lines=func_lines))
                        if func_lines > function_limit and not baseline_allows_length:
                            self.issues.append({
                                'type': 'error',
                                'file': str(rel_path),
                                'line': node.lineno,
                                'message': f'函数行数超标: {func_lines} 行 (限制: {function_limit})',
                                'category': 'function_length'
                            })
                            self.stats['backend_function_too_long'] += 1

                        complexity_limit = (self.NEW_MAX_COMPLEXITY
                                            if function_changed
                                            else self.LEGACY_MAX_COMPLEXITY)
                        baseline_allows_complexity = (
                            not function_changed
                            and self._baseline_function_allows(
                                rel_path_text, node.lineno, 'python', node.name,
                                complexity=complexity))
                        if (complexity > complexity_limit
                                and not baseline_allows_complexity):
                            self.issues.append({
                                'type': 'warning',
                                'file': str(rel_path),
                                'line': node.lineno,
                                'message': f'函数复杂度过高: {complexity} (限制: {complexity_limit})',
                                'category': 'complexity'
                            })
                            self.stats['high_complexity'] += 1

            except SyntaxError as e:
                self.issues.append({
                    'type': 'error',
                    'file': str(rel_path),
                    'line': e.lineno or 1,
                    'message': f'语法错误: {e}',
                    'category': 'syntax'
                })

        except Exception as e:
            print(f"  检查失败 {file_path}: {e}")

    def _is_test_file(self, file_path: Path) -> bool:
        """判断是否为测试文件（行数检查对其放行，复杂度仍检查）。

        命中规则（与门禁文档约定一致）：
        - 文件名以 test 开头（tests.py / test_*.py / testxxx.py）
        - 路径含 tests/ 或 test/ 目录组件
        """
        if file_path.name.startswith('test'):
            return True
        parts = file_path.parts
        return 'tests' in parts or 'test' in parts

    def _calculate_complexity(self, node: ast.AST) -> int:
        """计算函数复杂度（简单的圈复杂度估算）"""
        complexity = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1
        return complexity

    def _print_summary(self):
        """打印检查结果摘要"""
        print("=" * 60)
        print("               检查结果摘要")
        print("=" * 60)

        if not self.issues:
            print()
            print("[OK] 所有检查通过！未发现代码质量问题。")
            print()
            print("统计信息:")
            for key, value in self.stats.items():
                print(f"  - {key}: {value}")
            return

        # 按类别分组
        errors = [i for i in self.issues if i['type'] == 'error']
        warnings = [i for i in self.issues if i['type'] == 'warning']

        print()
        print(f"发现 {len(errors)} 个错误，{len(warnings)} 个警告")
        print()

        if errors:
            print("错误:")
            for issue in errors[:20]:  # 只显示前20个
                print(f"  [ERROR] {issue['file']}:{issue['line']}")
                print(f"     {issue['message']}")
            if len(errors) > 20:
                print(f"  ... 还有 {len(errors) - 20} 个错误")
            print()

        if warnings:
            print("警告:")
            for issue in warnings[:10]:  # 只显示前10个
                print(f"  [WARN]  {issue['file']}:{issue['line']}")
                print(f"     {issue['message']}")
            if len(warnings) > 10:
                print(f"  ... 还有 {len(warnings) - 10} 个警告")

        print()
        print("=" * 60)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="运行项目代码质量门禁")
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="根据当前代码生成历史问题基线，不以现有问题失败",
    )
    parser.add_argument(
        "--baseline",
        help="指定代码质量基线 JSON 路径（相对于仓库根目录）",
    )
    parser.add_argument(
        "--frontend-only",
        action="store_true",
        help="只检查前端代码",
    )
    parser.add_argument(
        "--backend-only",
        action="store_true",
        help="只检查后端代码",
    )
    args = parser.parse_args()
    if args.frontend_only and args.backend_only:
        parser.error("--frontend-only 与 --backend-only 不能同时使用")

    # 获取项目根目录
    script_dir = Path(__file__).parent
    root_dir = script_dir.parent

    checker = CodeQualityChecker(
        root_dir,
        baseline_path=args.baseline,
        write_baseline=args.write_baseline,
        frontend_only=args.frontend_only,
        backend_only=args.backend_only,
    )
    success = checker.check_all()

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()

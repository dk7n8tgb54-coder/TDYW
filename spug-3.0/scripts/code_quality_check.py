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
import io
import json
import re
import shutil
import subprocess
import tokenize
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
                 backend_only: bool = False, output_format: str = "text"):
        self.root_dir = Path(root_dir)
        self.issues = []
        self.stats = defaultdict(int)
        self.write_baseline = write_baseline
        self.frontend_only = frontend_only
        self.backend_only = backend_only
        self.output_format = output_format
        self.baseline_path = self.root_dir / (baseline_path or self.DEFAULT_BASELINE)
        self.baseline = self._load_baseline()
        self.changed_ranges = self._load_changed_ranges()
        self.observed_files = {}
        self.observed_functions = []

    def _log(self, message=''):
        """输出进度信息；JSON 模式写到 stderr，保持 stdout 为合法 JSON。"""
        stream = sys.stderr if self.output_format == "json" else sys.stdout
        print(message, file=stream)

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
            self._log(f"警告: 无法读取代码质量基线 {self.baseline_path}: {exc}")
            return {"version": 1, "files": {}, "functions": []}

    def _load_changed_ranges(self) -> dict[str, list[tuple[int, int]]]:
        """合并工作区和暂存区 diff，读取新增/修改行。"""
        changed = defaultdict(list)
        try:
            for diff_args in (("diff",), ("diff", "--cached")):
                result = subprocess.run(
                    ["git", *diff_args, "--unified=0", "--no-color", "--"],
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
                        current_file = self._git_path_to_project(line[6:])
                    elif current_file and line.startswith("@@"):
                        match = re.search(r"\+(\d+)(?:,(\d+))?", line)
                        if match:
                            start = int(match.group(1))
                            count = int(match.group(2) or 1)
                            changed[current_file].append(
                                (start, start + max(count - 1, 0))
                            )

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
                if len(line) < 4:
                    continue
                state, path = line[:2], line[3:]
                if state == "??":
                    changed[self._git_path_to_project(path)].append((1, 10**9))
        except OSError:
            # 在源码压缩包或没有 Git 的环境中按全量检查执行。
            return {}
        return dict(changed)

    @staticmethod
    def _rel_path(path: Path) -> str:
        return str(path).replace("\\", "/")

    def _git_path_to_project(self, path: str) -> str:
        """将 Git 仓库根相对路径转换为项目根相对路径。"""
        normalized = path.replace("\\", "/")
        prefix = f"{self.root_dir.name}/"
        if normalized.startswith(prefix):
            return normalized[len(prefix):]
        return normalized

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
            if (entry.get("line") == line
                    and (not entry.get("name") or entry.get("name") == name)):
                candidates.insert(0, entry)
            elif entry.get("name") == name:
                candidates.append(entry)
        for entry in candidates:
            # 逐条验证所有已记录的上限。某条候选过期时继续尝试其他候选，
            # 只有找到一条完整满足约束的记录才允许放行。
            ok = True
            if (func_lines is not None and entry.get("code_lines") is not None
                    and int(entry.get("code_lines", 0)) > 0
                    and func_lines > int(entry["code_lines"])):
                ok = False
            if (complexity is not None and entry.get("complexity") is not None
                    and complexity > int(entry["complexity"])):
                ok = False
            if ok:
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
        # 单独检查前后端时只更新对应作用域，避免 --frontend-only 意外删除
        # 后端基线（反之亦然）。全量写入仍会清理已经修复的历史条目。
        if self.frontend_only or self.backend_only:
            scope_prefix = "spug_web/" if self.frontend_only else "spug_api/"
            old_files = self.baseline.get("files", {})
            old_functions = self.baseline.get("functions", [])
            files = {
                **{
                    path: value for path, value in old_files.items()
                    if not path.startswith(scope_prefix)
                },
                **files,
            }
            functions = [
                entry for entry in old_functions
                if not entry.get("file", "").startswith(scope_prefix)
            ] + [entry for entry in functions
                 if entry.get("file", "").startswith(scope_prefix)]
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
        self._log(f"已写入代码质量基线: {self.baseline_path}")

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
        if is_python:
            return total_lines, self._count_python_code_lines(content)
        return total_lines, self._count_javascript_code_lines(content)

    @staticmethod
    def _count_python_code_lines(content: str) -> int:
        """使用 Python tokenizer 统计代码行，避免文本匹配三引号误判。"""
        code_lines = set()
        try:
            tokens = tokenize.generate_tokens(io.StringIO(content).readline)
            for token in tokens:
                if token.type in {
                    tokenize.ENCODING,
                    tokenize.ENDMARKER,
                    tokenize.INDENT,
                    tokenize.DEDENT,
                    tokenize.NEWLINE,
                    tokenize.NL,
                    tokenize.COMMENT,
                }:
                    continue
                code_lines.update(range(token.start[0], token.end[0] + 1))
        except (tokenize.TokenError, IndentationError):
            # 语法错误由 AST 检查单独报告；这里保守地统计非空非注释行。
            return sum(1 for line in content.splitlines()
                       if line.strip() and not line.lstrip().startswith('#'))
        # 仅排除真正位于模块、类或函数首位的 docstring；普通字符串表达式
        # 和赋值中的多行字符串仍然属于有效代码。
        try:
            tree = ast.parse(content)
            docstring_lines = set()
            for node in ast.walk(tree):
                body = getattr(node, "body", None)
                if not isinstance(body, list) or not body:
                    continue
                first = body[0]
                if (isinstance(first, ast.Expr)
                        and isinstance(first.value, ast.Constant)
                        and isinstance(first.value.value, str)):
                    docstring_lines.update(
                        range(first.lineno, first.end_lineno + 1)
                    )
            code_lines.difference_update(docstring_lines)
        except SyntaxError:
            pass
        return len(code_lines)

    @staticmethod
    def _count_javascript_code_lines(content: str) -> int:
        """用 Babel tokenizer 之外的轻量词法扫描统计 JS 行，忽略注释和字符串。"""
        code_lines = set()
        in_block_comment = False
        quote = None
        escaped = False
        for line_no, line in enumerate(content.splitlines(), 1):
            has_code = False
            i = 0
            while i < len(line):
                char = line[i]
                nxt = line[i + 1] if i + 1 < len(line) else ''
                if in_block_comment:
                    if char == '*' and nxt == '/':
                        in_block_comment = False
                        i += 2
                        continue
                    i += 1
                    continue
                if quote:
                    if escaped:
                        escaped = False
                    elif char == '\\':
                        escaped = True
                    elif char == quote:
                        quote = None
                    i += 1
                    continue
                if char == '/' and nxt == '*':
                    in_block_comment = True
                    i += 2
                    continue
                if char == '/' and nxt == '/':
                    break
                if char in "'\"`":
                    quote = char
                    has_code = True
                    i += 1
                    continue
                if not char.isspace():
                    has_code = True
                i += 1
            if has_code:
                code_lines.add(line_no)
        return len(code_lines)

    def check_all(self) -> bool:
        """运行所有检查"""
        self._log("=" * 60)
        self._log("       代码质量检查工具 - 任务5.1")
        self._log("=" * 60)
        self._log()

        if not self.backend_only:
            self._log("[1/2] 检查前端代码...")
            self._log("-" * 60)
            self._check_frontend()

        if not self.frontend_only:
            self._log()
            self._log("[2/2] 检查后端代码...")
            self._log("-" * 60)
            self._check_backend()

        self._log()
        if self.output_format == "json":
            self._print_json_summary()
        else:
            self._print_summary()

        if self.write_baseline:
            self._write_baseline()
            return True
        # 复杂度目前是 advisory warning；只有错误阻断本次门禁。
        return not any(issue['type'] == 'error' for issue in self.issues)

    def _check_frontend(self):
        """检查前端代码"""
        web_dir = self.root_dir / "spug_web" / "src"
        if not web_dir.exists():
            self._log(f"  跳过: 前端目录不存在: {web_dir}")
            return

        js_files = list(web_dir.rglob("*.js")) + list(web_dir.rglob("*.jsx"))

        for file_path in js_files:
            self._check_js_file(file_path)

        self._log(f"  检查了 {len(js_files)} 个前端文件")

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

            functions = self._parse_js_functions(
                content, file_path.parent, str(rel_path)
            )
            for function in functions:
                line_num = function['line']
                end_line = function['end_line']
                func_lines = end_line - line_num + 1
                self._remember_function(
                    rel_path_text, line_num, 'javascript', func_lines,
                    name=function.get('name'),
                )
                function_changed = self._line_changed(
                    rel_path_text, line_num, end_line)
                function_limit = (self.NEW_MAX_FUNCTION_LINES
                                  if function_changed
                                  else self.LEGACY_MAX_FUNCTION_LINES)
                baseline_allows = (not function_changed and
                                   self._baseline_function_allows(
                                       rel_path_text, line_num, 'javascript',
                                       name=function.get('name'),
                                       func_lines=func_lines))
                if func_lines > function_limit and not baseline_allows:
                    self.issues.append({
                        'type': 'error',
                        'file': str(rel_path),
                        'line': line_num,
                        'message': f'函数行数超标: {func_lines} 行 (限制: {function_limit})',
                        'category': 'function_length'
                    })
                    self.stats['frontend_function_too_long'] += 1

        except Exception as e:
            self._log(f"  检查失败 {file_path}: {e}")

    def _parse_js_functions(self, content: str, working_dir: Path,
                            display_path: str = '') -> list[dict]:
        """用 Babel parser 识别 JS 函数，避免正则和手写括号匹配误报。"""
        node = shutil.which("node")
        parser_dir = self.root_dir / "spug_web" / "node_modules"
        if not node or not parser_dir.exists():
            return []
        script = r'''
const parser = require('@babel/parser');
let source = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => source += chunk);
process.stdin.on('end', () => {
  try {
    const ast = parser.parse(source, {
      sourceType: 'unambiguous',
      plugins: ['jsx', 'decorators-legacy', 'classProperties',
        'classPrivateProperties', 'classPrivateMethods', 'objectRestSpread',
        'optionalChaining', 'dynamicImport', 'importMeta', 'topLevelAwait',
        'logicalAssignment', 'nullishCoalescingOperator']
    });
    const result = [];
    const functionTypes = new Set([
      'FunctionDeclaration', 'FunctionExpression', 'ArrowFunctionExpression',
      'ObjectMethod', 'ClassMethod', 'ClassPrivateMethod'
    ]);
    const walk = node => {
      if (!node || typeof node !== 'object') return;
      if (functionTypes.has(node.type) && node.loc) {
        result.push({
          line: node.loc.start.line,
          end_line: node.loc.end.line,
          name: node.id?.name || node.key?.name || null
        });
      }
      for (const value of Object.values(node)) {
        if (Array.isArray(value)) value.forEach(walk);
        else if (value && typeof value === 'object') walk(value);
      }
    };
    walk(ast);
    process.stdout.write(JSON.stringify(result));
  } catch (error) {
    process.stderr.write(String(error.message || error));
    process.exitCode = 2;
  }
});
'''
        try:
            result = subprocess.run(
                [node, "-e", script],
                cwd=working_dir,
                input=content,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=10,
            )
            if result.returncode != 0:
                self._log(f"警告: JS AST 解析失败，跳过函数长度检查 {display_path}: "
                          f"{result.stderr.strip()}")
                return []
            return json.loads(result.stdout or "[]")
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            self._log(f"警告: JS AST 解析不可用，跳过函数长度检查 {display_path}: {exc}")
            return []

    def _check_backend(self):
        """检查后端代码"""
        api_dir = self.root_dir / "spug_api"
        if not api_dir.exists():
            self._log(f"警告: 后端目录不存在: {api_dir}")
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

        self._log(f"  检查了 {len(py_files)} 个后端文件")

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
            self._log(f"  检查失败 {file_path}: {e}")

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
        """计算接近 radon 的圈复杂度，且不把嵌套函数计入外层函数。"""
        class ComplexityVisitor(ast.NodeVisitor):
            def __init__(self, root):
                self.root = root
                self.value = 1

            def visit_FunctionDef(self, current):
                if current is not self.root:
                    return
                self.generic_visit(current)

            visit_AsyncFunctionDef = visit_FunctionDef

            def visit_If(self, current):
                self.value += 1
                self.generic_visit(current)

            def visit_IfExp(self, current):
                self.value += 1
                self.generic_visit(current)

            def visit_For(self, current):
                self.value += 1
                self.generic_visit(current)

            visit_AsyncFor = visit_For

            def visit_While(self, current):
                self.value += 1
                self.generic_visit(current)

            def visit_ExceptHandler(self, current):
                self.value += 1
                self.generic_visit(current)

            def visit_BoolOp(self, current):
                self.value += max(len(current.values) - 1, 0)
                self.generic_visit(current)

            def visit_Match(self, current):
                self.value += len(current.cases)
                self.generic_visit(current)

            def visit_comprehension(self, current):
                self.value += 1
                self.generic_visit(current)

        visitor = ComplexityVisitor(node)
        visitor.visit(node)
        return visitor.value

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

    def _print_json_summary(self):
        """输出机器可读结果，供 CI 和质量看板使用。"""
        print(json.dumps({
            "passed": not any(issue['type'] == 'error' for issue in self.issues),
            "errors": [issue for issue in self.issues if issue['type'] == 'error'],
            "warnings": [issue for issue in self.issues if issue['type'] == 'warning'],
            "stats": dict(self.stats),
        }, ensure_ascii=False, indent=2))


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
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="输出格式，默认 text",
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
        output_format=args.format,
    )
    success = checker.check_all()

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()

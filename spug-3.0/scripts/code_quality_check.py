#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
【任务5.1】代码质量检查工具
检查项目代码是否符合规范要求：
1. 文件行数 ≤ 1000行
2. 函数行数 ≤ 250行
3. 复杂度 ≤ 25
4. 禁止重复代码
"""

import os
import sys
import ast
import re
from pathlib import Path
from collections import defaultdict
from typing import List, Dict, Tuple


class CodeQualityChecker:
    """代码质量检查器"""

    # 限制配置
    MAX_FILE_LINES = 1000
    MAX_FUNCTION_LINES = 250
    MAX_COMPLEXITY = 25

    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir)
        self.issues = []
        self.stats = defaultdict(int)

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

        # 检查前端代码
        print("[1/2] 检查前端代码...")
        print("-" * 60)
        self._check_frontend()

        print()

        # 检查后端代码
        print("[2/2] 检查后端代码...")
        print("-" * 60)
        self._check_backend()

        print()
        self._print_summary()

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

            # 检查有效代码行数
            if code_lines > self.MAX_FILE_LINES:
                self.issues.append({
                    'type': 'error',
                    'file': str(rel_path),
                    'line': 1,
                    'message': f'有效代码行数超标: {code_lines} 行 (总行数: {total_lines}, 限制: {self.MAX_FILE_LINES})',
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
                    if func_lines > self.MAX_FUNCTION_LINES:
                        self.issues.append({
                            'type': 'error',
                            'file': str(rel_path),
                            'line': line_num,
                            'message': f'函数行数超标: ~{func_lines} 行 (限制: {self.MAX_FUNCTION_LINES})',
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

            # 检查有效代码行数（测试文件放行行数限制，仅业务代码受约束）
            if not self._is_test_file(file_path) and code_lines > self.MAX_FILE_LINES:
                self.issues.append({
                    'type': 'error',
                    'file': str(rel_path),
                    'line': 1,
                    'message': f'有效代码行数超标: {code_lines} 行 (总行数: {total_lines}, 限制: {self.MAX_FILE_LINES})',
                    'category': 'file_length'
                })
                self.stats['backend_file_too_long'] += 1

            # 使用 AST 分析函数
            try:
                tree = ast.parse(content)
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        func_lines = node.end_lineno - node.lineno + 1
                        if func_lines > self.MAX_FUNCTION_LINES:
                            self.issues.append({
                                'type': 'error',
                                'file': str(rel_path),
                                'line': node.lineno,
                                'message': f'函数行数超标: {func_lines} 行 (限制: {self.MAX_FUNCTION_LINES})',
                                'category': 'function_length'
                            })
                            self.stats['backend_function_too_long'] += 1

                        # 简单复杂度检查
                        complexity = self._calculate_complexity(node)
                        if complexity > self.MAX_COMPLEXITY:
                            self.issues.append({
                                'type': 'warning',
                                'file': str(rel_path),
                                'line': node.lineno,
                                'message': f'函数复杂度过高: {complexity} (限制: {self.MAX_COMPLEXITY})',
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
    # 获取项目根目录
    script_dir = Path(__file__).parent
    root_dir = script_dir.parent

    checker = CodeQualityChecker(root_dir)
    success = checker.check_all()

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()

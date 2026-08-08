"""
Django URL 路由解析器
解析 urls.py 文件，提取 URL 模式到 View 的映射。
使用 AST 解析 urlpatterns 中的 path()/re_path() 调用。
"""
import ast
import os
import re
from dataclasses import dataclass


@dataclass
class URLPattern:
    """URL 路由条目"""
    pattern: str = ""
    view_name: str = ""
    source_file: str = ""
    line: int = 0
    app: str = ""


class RouteParser:
    """解析 Django URL 配置"""

    def __init__(self, spug_api_path: str):
        self.spug_api_path = spug_api_path
        self.patterns: list[URLPattern] = []
        self.url_view_map: dict[str, str] = {}

    def parse_all(self):
        """解析所有 URL 配置"""
        # 1. 解析主 urls.py 获取 app -> url_prefix 映射
        main_urls = os.path.join(self.spug_api_path, 'spug', 'urls.py')
        app_url_prefix = {}  # app_name -> url_prefix
        if os.path.isfile(main_urls):
            app_url_prefix = self._parse_main_urls(main_urls)

        # 2. 解析每个 app 的 urls.py
        apps_dir = os.path.join(self.spug_api_path, 'apps')
        if not os.path.isdir(apps_dir):
            return

        for app_name in os.listdir(apps_dir):
            app_dir = os.path.join(apps_dir, app_name)
            if not os.path.isdir(app_dir) or app_name.startswith('__'):
                continue

            # 查找 urls.py
            urls_file = os.path.join(app_dir, 'urls.py')
            if os.path.isfile(urls_file):
                prefix = app_url_prefix.get(app_name, f'{app_name}/')
                self._parse_app_urls(urls_file, app_name, prefix)

            # 也检查子目录中的 urls.py
            for root, dirs, files in os.walk(app_dir):
                dirs[:] = [d for d in dirs if not d.startswith('__')]
                if root == app_dir:
                    continue
                for fname in files:
                    if fname == 'urls.py':
                        sub_prefix = app_url_prefix.get(app_name, f'{app_name}/')
                        self._parse_app_urls(
                            os.path.join(root, fname),
                            app_name,
                            sub_prefix
                        )

    def _parse_main_urls(self, fpath: str) -> dict:
        """解析主 urls.py，提取 app -> url_prefix 映射"""
        result = {}
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                source = f.read()
            tree = ast.parse(source, filename=fpath)
        except (SyntaxError, UnicodeDecodeError):
            return result

        for node in ast.walk(tree):
            if not isinstance(node, ast.List):
                continue
            # 检查是否是 urlpatterns
            for item in node.elts:
                if isinstance(item, ast.Call):
                    func_name = self._get_name(item.func)
                    if func_name in ('path', 're_path', 'include'):
                        prefix, app_name = self._extract_include_info(item)
                        if prefix and app_name:
                            result[app_name] = prefix
        return result

    def _extract_include_info(self, call_node) -> tuple:
        """从 path('xxx/', include('apps.xxx.urls')) 提取前缀和 app 名"""
        if not call_node.args:
            return ('', '')

        prefix = ''
        if len(call_node.args) >= 1:
            arg = call_node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                prefix = arg.value

        app_name = ''
        if len(call_node.args) >= 2:
            arg = call_node.args[1]
            if isinstance(arg, ast.Call):
                func_name = self._get_name(arg.func)
                if func_name == 'include' and arg.args:
                    include_arg = arg.args[0]
                    if isinstance(include_arg, ast.Constant) and isinstance(include_arg.value, str):
                        # 'apps.home.urls' -> 'home'
                        parts = include_arg.value.split('.')
                        if len(parts) >= 3:
                            app_name = parts[1]
                            # 检查 namespace 参数
                            if not app_name:
                                app_name = parts[-2] if len(parts) >= 2 else ''

        return (prefix, app_name)

    def _parse_app_urls(self, fpath: str, app_name: str, prefix: str):
        """解析 app 的 urls.py"""
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                source = f.read()
            tree = ast.parse(source, filename=fpath)
        except (SyntaxError, UnicodeDecodeError):
            return

        lines = source.splitlines()

        for node in ast.walk(tree):
            if not isinstance(node, ast.List):
                continue
            for item in node.elts:
                if isinstance(item, ast.Call):
                    self._extract_url_pattern(item, fpath, app_name, prefix, lines)

    def _extract_url_pattern(self, call_node, fpath: str, app_name: str, prefix: str, lines: list):
        """从 path('pattern', ViewClass.as_view()) 提取 URL 模式"""
        func_name = self._get_name(call_node.func)
        if func_name not in ('path', 're_path', 'url'):
            return

        if not call_node.args:
            return

        # 第一个参数是 URL 模式
        pattern = ''
        if call_node.args:
            arg = call_node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                pattern = arg.value

        # 第二个参数是 View（通常是 ViewClass.as_view() 或函数）
        view_name = ''
        if len(call_node.args) >= 2:
            arg = call_node.args[1]
            if isinstance(arg, ast.Call):
                # ViewClass.as_view()
                func = arg.func
                if isinstance(func, ast.Attribute):
                    view_name = self._get_name(func.value)
                elif isinstance(func, ast.Name):
                    view_name = func.id
            elif isinstance(arg, ast.Name):
                view_name = arg.id
            elif isinstance(arg, ast.Attribute):
                view_name = self._get_name(arg)

        if pattern and view_name:
            full_pattern = f'/api/{prefix}{pattern}'
            self.patterns.append(URLPattern(
                pattern=full_pattern,
                view_name=view_name,
                source_file=fpath,
                line=call_node.lineno if hasattr(call_node, 'lineno') else 0,
                app=app_name,
            ))
            self.url_view_map[full_pattern] = view_name

    def _get_name(self, node) -> str:
        """从 AST 节点提取名称"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return node.attr
        elif isinstance(node, ast.Subscript):
            return self._get_name(node.value)
        return ''

"""
后端权限解析器
使用 Python AST 解析 View 类、PERM_MAP、@auth 装饰器。
"""
import ast
import os
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BackendPermEntry:
    """后端权限使用记录"""
    api: str = ""
    http_method: str = ""
    view_class: str = ""
    service: str = ""
    model: str = ""
    operation: str = ""
    login_required: bool = True
    permission_code: str = ""
    object_check: str = ""
    tenant_check: str = ""
    source_file: str = ""
    line: int = 0
    status: str = ""
    notes: str = ""


@dataclass
class ViewInfo:
    """View 类信息"""
    name: str
    file_path: str
    line: int
    base_classes: list = field(default_factory=list)
    perm_map: dict = field(default_factory=dict)
    perm_map_line: int = 0
    methods: dict = field(default_factory=dict)  # method_name -> {perm, line, has_auth}
    has_auth_on_any: bool = False
    is_admin_view: bool = False


class BackendParser:
    """解析后端 Python 源码，提取权限使用信息"""

    # 已知的 HTTP 方法名
    HTTP_METHODS = {'get', 'post', 'put', 'patch', 'delete', 'head', 'options'}

    def __init__(self, spug_api_path: str):
        self.spug_api_path = spug_api_path
        self.views: list[ViewInfo] = []
        self.perm_entries: list[BackendPermEntry] = []
        self.url_view_map: dict[str, str] = {}  # url_pattern -> view_class_name

    def parse_all(self):
        """解析所有 apps 下的 Python 文件"""
        apps_dir = os.path.join(self.spug_api_path, 'apps')
        if not os.path.isdir(apps_dir):
            return
        for app_name in os.listdir(apps_dir):
            app_dir = os.path.join(apps_dir, app_name)
            if not os.path.isdir(app_dir):
                continue
            # 跳过 __pycache__
            if app_name.startswith('__'):
                continue
            self._parse_app_dir(app_dir, app_name)

    def _parse_app_dir(self, app_dir: str, app_name: str):
        """解析单个 app 目录"""
        for root, dirs, files in os.walk(app_dir):
            # 跳过 __pycache__
            dirs[:] = [d for d in dirs if not d.startswith('__')]
            for fname in files:
                if not fname.endswith('.py'):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    self._parse_python_file(fpath, app_name)
                except Exception as e:
                    # 记录但继续
                    pass

    def _parse_python_file(self, fpath: str, app_name: str):
        """解析单个 Python 文件，提取 View 类和权限信息"""
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                source = f.read()
            tree = ast.parse(source, filename=fpath)
        except (SyntaxError, UnicodeDecodeError):
            return

        # 构建行号映射
        lines = source.splitlines()

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue

            view_info = self._extract_view_info(node, fpath, lines)
            if view_info:
                self.views.append(view_info)

    def _extract_view_info(self, node: ast.ClassDef, fpath: str, lines: list) -> Optional[ViewInfo]:
        """从 AST ClassDef 节点提取 View 信息"""
        view = ViewInfo(
            name=node.name,
            file_path=fpath,
            line=node.lineno,
        )

        # 提取基类
        for base in node.bases:
            base_name = self._get_name(base)
            if base_name:
                view.base_classes.append(base_name)
                if base_name in ('AdminView', 'View'):
                    view.is_admin_view = (base_name == 'AdminView')

        # 只有继承 View/AdminView 的类才关注
        is_view = any(
            self._get_name(base) in ('AdminView', 'View', 'SupperOnlyView')
            for base in node.bases
        )
        if not is_view:
            return None

        # 遍历类体
        for item in node.body:
            if isinstance(item, ast.Assign):
                # PERM_MAP = {...}
                if len(item.targets) == 1:
                    target_name = self._get_name(item.targets[0])
                    if target_name == 'PERM_MAP' and isinstance(item.value, ast.Dict):
                        view.perm_map_line = item.lineno
                        for key, val in zip(item.value.keys, item.value.values):
                            method = self._get_str(key)
                            perm = self._get_str(val)
                            if method and perm:
                                view.perm_map[method.upper()] = perm

            elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # 检查方法是否有 @auth 装饰器
                method_name = item.name
                if method_name.lower() not in self.HTTP_METHODS:
                    continue

                method_info = {'perm': '', 'line': item.lineno, 'has_auth': False}
                for dec in item.decorator_list:
                    dec_name = self._get_decorator_name(dec)
                    if dec_name == 'auth':
                        method_info['has_auth'] = True
                        view.has_auth_on_any = True
                        # 提取权限参数
                        perm_str = self._extract_auth_perm(dec, lines)
                        if perm_str:
                            method_info['perm'] = perm_str
                view.methods[method_name.lower()] = method_info

        return view

    def _get_name(self, node) -> str:
        """从 AST 节点提取名称"""
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return node.attr
        elif isinstance(node, ast.Subscript):
            return self._get_name(node.value)
        return ''

    def _get_str(self, node) -> str:
        """从 AST 节点提取字符串值"""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return ''

    def _get_decorator_name(self, node) -> str:
        """提取装饰器名称"""
        if isinstance(node, ast.Call):
            return self._get_name(node.func)
        elif isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return node.attr
        return ''

    def _extract_auth_perm(self, dec_node, lines: list) -> str:
        """从 @auth(...) 装饰器提取权限字符串"""
        if isinstance(dec_node, ast.Call) and dec_node.args:
            arg = dec_node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                return arg.value
        # 尝试从源码行提取
        if hasattr(dec_node, 'lineno') and dec_node.lineno <= len(lines):
            line = lines[dec_node.lineno - 1]
            m = re.search(r"@auth\(['\"]([^'\"]+)['\"]\)", line)
            if m:
                return m.group(1)
        return ''

    def build_perm_entries(self, url_view_map: dict):
        """根据 View 信息和 URL 映射构建权限条目"""
        # 构建 view_name -> ViewInfo 映射
        view_by_name = {}
        for v in self.views:
            view_by_name[v.name] = v

        for url_pattern, view_name in url_view_map.items():
            view = view_by_name.get(view_name)
            if not view:
                # 可能是函数视图或动态导入
                self.perm_entries.append(BackendPermEntry(
                    api=url_pattern,
                    view_class=view_name,
                    status="dynamic",
                    notes="View class not found in static analysis"
                ))
                continue

            if view.perm_map:
                # AdminView + PERM_MAP 模式
                for method, perm in view.perm_map.items():
                    self.perm_entries.append(BackendPermEntry(
                        api=url_pattern,
                        http_method=method,
                        view_class=view_name,
                        login_required=True,
                        permission_code=perm,
                        source_file=view.file_path,
                        line=view.perm_map_line,
                        status="ok",
                    ))
            elif view.has_auth_on_any:
                # @auth 装饰器模式
                for method_name, method_info in view.methods.items():
                    if method_info['has_auth']:
                        self.perm_entries.append(BackendPermEntry(
                            api=url_pattern,
                            http_method=method_name.upper(),
                            view_class=view_name,
                            login_required=True,
                            permission_code=method_info['perm'],
                            source_file=view.file_path,
                            line=method_info['line'],
                            status="ok",
                        ))
                    else:
                        # 方法存在但无 @auth
                        self.perm_entries.append(BackendPermEntry(
                            api=url_pattern,
                            http_method=method_name.upper(),
                            view_class=view_name,
                            login_required=True,
                            permission_code="",
                            source_file=view.file_path,
                            line=method_info['line'],
                            status="missing_perm",
                            notes=f"Method {method_name} has no @auth decorator"
                        ))
            elif view.is_admin_view:
                # AdminView without PERM_MAP - only super user
                self.perm_entries.append(BackendPermEntry(
                    api=url_pattern,
                    view_class=view_name,
                    login_required=True,
                    permission_code="super_only",
                    source_file=view.file_path,
                    line=view.line,
                    status="super_only",
                    notes="AdminView without PERM_MAP - only super user can access"
                ))
            else:
                # Plain View without any permission check
                self.perm_entries.append(BackendPermEntry(
                    api=url_pattern,
                    view_class=view_name,
                    login_required=True,
                    permission_code="",
                    source_file=view.file_path,
                    line=view.line,
                    status="no_perm_check",
                    notes="View has no permission check (no PERM_MAP, no @auth)"
                ))

    def get_all_permission_codes(self) -> set:
        """获取所有后端使用的权限编码"""
        codes = set()
        for entry in self.perm_entries:
            if entry.permission_code and entry.permission_code != 'super_only':
                # 处理 pipe-separated 权限
                for part in entry.permission_code.split('|'):
                    part = part.strip()
                    if part:
                        codes.add(part)
        return codes

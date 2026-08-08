"""
前端权限解析器
解析 routes.js 路由配置、hasPermission() 调用、AuthButton/AuthDiv 组件。
"""
import os
import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FrontendRoute:
    """前端路由条目"""
    path: str = ""
    title: str = ""
    auth: str = ""
    component: str = ""
    icon: str = ""
    source_file: str = ""
    line: int = 0


@dataclass
class FrontendPermEntry:
    """前端权限使用记录"""
    page: str = ""
    route: str = ""
    component: str = ""
    menu: str = ""
    operation: str = ""
    permission_code: str = ""
    api: str = ""
    source_file: str = ""
    line: int = 0
    status: str = ""
    notes: str = ""


class FrontendParser:
    """解析前端 JS 源码，提取权限使用信息"""

    # 匹配 hasPermission('xxx') 或 hasPermission("xxx")
    HAS_PERM_RE = re.compile(
        r'hasPermission\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)'
    )
    # 匹配 auth='xxx' 或 auth="xxx"
    AUTH_PROP_RE = re.compile(
        r'\bauth\s*=\s*[\'"]([^\'"]+)[\'"]'
    )
    # 匹配 AuthButton auth="xxx"
    AUTH_BUTTON_RE = re.compile(
        r'<AuthButton[^>]*\bauth\s*=\s*[\'"]([^\'"]+)[\'"]'
    )
    # 匹配 AuthDiv auth="xxx"
    AUTH_DIV_RE = re.compile(
        r'<AuthDiv[^>]*\bauth\s*=\s*[\'"]([^\'"]+)[\'"]'
    )
    # 匹配 ExportButton auth="xxx"
    EXPORT_BUTTON_RE = re.compile(
        r'<ExportButton[^>]*\bauth\s*=\s*[\'"]([^\'"]+)[\'"]'
    )
    # 匹配 Action.Button auth="xxx"
    ACTION_BUTTON_RE = re.compile(
        r'<Action\.Button[^>]*\bauth\s*=\s*[\'"]([^\'"]+)[\'"]'
    )
    # 匹配 HTTP 调用
    HTTP_CALL_RE = re.compile(
        r'HTTP\.(get|post|put|patch|delete)\s*\(\s*[\'"`]([^\'"`]+)[\'"`]'
    )

    def __init__(self, spug_web_src_path: str):
        self.spug_web_src_path = spug_web_src_path
        self.routes: list[FrontendRoute] = []
        self.perm_entries: list[FrontendPermEntry] = []

    def parse_all(self):
        """解析前端路由和页面权限"""
        # 1. 解析 routes.js
        self._parse_routes_js()
        # 2. 解析页面 JS 文件中的权限使用
        self._parse_page_permissions()

    def _parse_routes_js(self):
        """解析 routes.js 提取路由配置"""
        routes_file = os.path.join(self.spug_web_src_path, 'routes.js')
        if not os.path.isfile(routes_file):
            return

        with open(routes_file, 'r', encoding='utf-8') as f:
            content = f.read()
        lines = content.splitlines()

        # routes.js 使用对象数组格式，每条路由有 path, title, auth, component 等字段
        # 使用状态机解析
        current_route = {}
        current_indent = 0
        in_route = False

        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # 检测路由开始（包含 path:）
            if 'path:' in stripped and not stripped.startswith('//'):
                if current_route and 'path' in current_route:
                    self.routes.append(FrontendRoute(
                        path=current_route.get('path', ''),
                        title=current_route.get('title', ''),
                        auth=current_route.get('auth', ''),
                        component=current_route.get('component', ''),
                        source_file=routes_file,
                        line=current_route.get('line', 0),
                    ))
                current_route = {'line': i}
                in_route = True

            if in_route:
                # 提取各字段
                m = re.search(r"path:\s*['\"]([^'\"]+)['\"]", stripped)
                if m:
                    current_route['path'] = m.group(1)

                m = re.search(r"title:\s*['\"]([^'\"]*)['\"]", stripped)
                if m:
                    current_route['title'] = m.group(1)

                m = re.search(r"auth:\s*['\"]([^'\"]+)['\"]", stripped)
                if m:
                    current_route['auth'] = m.group(1)

                m = re.search(r"component:\s*['\"]([^'\"]+)['\"]", stripped)
                if m:
                    current_route['component'] = m.group(1)

                m = re.search(r"icon:\s*['\"]([^'\"]*)['\"]", stripped)
                if m:
                    current_route['icon'] = m.group(1)

        # 最后一条路由
        if current_route and 'path' in current_route:
            self.routes.append(FrontendRoute(
                path=current_route.get('path', ''),
                title=current_route.get('title', ''),
                auth=current_route.get('auth', ''),
                component=current_route.get('component', ''),
                source_file=routes_file,
                line=current_route.get('line', 0),
            ))

    def _parse_page_permissions(self):
        """解析所有页面 JS 文件中的权限使用"""
        pages_dir = os.path.join(self.spug_web_src_path, 'pages')
        if not os.path.isdir(pages_dir):
            return

        # 构建路由 -> 页面路径映射
        route_page_map = {}
        for route in self.routes:
            if route.component:
                # component 路径如 'home/Dashboard' -> pages/home/Dashboard
                comp_path = route.component.lstrip('./')
                route_page_map[comp_path] = route

        for root, dirs, files in os.walk(pages_dir):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for fname in files:
                if not fname.endswith('.js'):
                    continue
                fpath = os.path.join(root, fname)
                # 计算相对路径
                rel_path = os.path.relpath(fpath, pages_dir).replace('\\', '/')
                rel_path_no_ext = rel_path.rsplit('.js', 1)[0]

                # 找到对应路由
                route = self._find_route_for_page(rel_path, rel_path_no_ext, route_page_map)

                try:
                    self._parse_js_file(fpath, rel_path, route)
                except Exception:
                    pass

    def _find_route_for_page(self, rel_path: str, rel_path_no_ext: str, route_page_map: dict) -> Optional[FrontendRoute]:
        """根据文件相对路径查找对应路由"""
        # 尝试精确匹配
        for comp_path, route in route_page_map.items():
            if comp_path == rel_path_no_ext or comp_path == rel_path:
                return route
            # 模糊匹配：component 路径可能是目录下的 index
            if comp_path.endswith(rel_path_no_ext) or rel_path_no_ext.endswith(comp_path):
                return route
        return None

    def _parse_js_file(self, fpath: str, rel_path: str, route: Optional[FrontendRoute]):
        """解析单个 JS 文件中的权限使用"""
        with open(fpath, 'r', encoding='utf-8') as f:
            content = f.read()
        lines = content.splitlines()

        page_name = rel_path
        route_path = route.path if route else ''
        route_auth = route.auth if route else ''

        for i, line in enumerate(lines, 1):
            # hasPermission() 调用
            for m in self.HAS_PERM_RE.finditer(line):
                perm = m.group(1)
                operation = self._infer_operation(line, 'hasPermission')
                api = self._find_nearby_api(lines, i - 1)
                self.perm_entries.append(FrontendPermEntry(
                    page=page_name,
                    route=route_path,
                    component=rel_path,
                    menu=route.title if route else '',
                    operation=operation,
                    permission_code=perm,
                    api=api,
                    source_file=fpath,
                    line=i,
                    status="ok",
                ))

            # AuthButton auth="xxx"
            for m in self.AUTH_BUTTON_RE.finditer(line):
                perm = m.group(1)
                operation = self._infer_operation(line, 'AuthButton')
                self.perm_entries.append(FrontendPermEntry(
                    page=page_name,
                    route=route_path,
                    component=rel_path,
                    menu=route.title if route else '',
                    operation=operation,
                    permission_code=perm,
                    source_file=fpath,
                    line=i,
                    status="ok",
                ))

            # AuthDiv auth="xxx"
            for m in self.AUTH_DIV_RE.finditer(line):
                perm = m.group(1)
                self.perm_entries.append(FrontendPermEntry(
                    page=page_name,
                    route=route_path,
                    component=rel_path,
                    menu=route.title if route else '',
                    operation='page_container',
                    permission_code=perm,
                    source_file=fpath,
                    line=i,
                    status="ok",
                ))

            # ExportButton auth="xxx"
            for m in self.EXPORT_BUTTON_RE.finditer(line):
                perm = m.group(1)
                self.perm_entries.append(FrontendPermEntry(
                    page=page_name,
                    route=route_path,
                    component=rel_path,
                    menu=route.title if route else '',
                    operation='export',
                    permission_code=perm,
                    source_file=fpath,
                    line=i,
                    status="ok",
                ))

            # Action.Button auth="xxx"
            for m in self.ACTION_BUTTON_RE.finditer(line):
                perm = m.group(1)
                operation = self._infer_operation(line, 'Action.Button')
                self.perm_entries.append(FrontendPermEntry(
                    page=page_name,
                    route=route_path,
                    component=rel_path,
                    menu=route.title if route else '',
                    operation=operation,
                    permission_code=perm,
                    source_file=fpath,
                    line=i,
                    status="ok",
                ))

            # HTTP 调用 - 记录 API 使用点
            for m in self.HTTP_CALL_RE.finditer(line):
                method = m.group(1).upper()
                api_path = m.group(2)
                # 检查附近是否有权限检查
                has_perm_nearby = self._check_perm_nearby(lines, i - 1)
                self.perm_entries.append(FrontendPermEntry(
                    page=page_name,
                    route=route_path,
                    component=rel_path,
                    menu=route.title if route else '',
                    operation=f'api_call_{method.lower()}',
                    permission_code=has_perm_nearby if has_perm_nearby else '',
                    api=f'{method} {api_path}',
                    source_file=fpath,
                    line=i,
                    status="ok" if has_perm_nearby else "no_perm_check_nearby",
                    notes="" if has_perm_nearby else "API call without nearby permission check"
                ))

    def _infer_operation(self, line: str, component_type: str) -> str:
        """从代码行推断操作类型"""
        line_lower = line.lower()
        if 'add' in line_lower or 'create' in line_lower or '新建' in line_lower:
            return 'add'
        if 'edit' in line_lower or 'update' in line_lower or '编辑' in line_lower:
            return 'edit'
        if 'del' in line_lower or '删除' in line_lower:
            return 'delete'
        if 'export' in line_lower or '导出' in line_lower:
            return 'export'
        if 'import' in line_lower or '导入' in line_lower:
            return 'import'
        if 'download' in line_lower or '下载' in line_lower:
            return 'download'
        if 'view' in line_lower or '查看' in line_lower:
            return 'view'
        return component_type

    def _find_nearby_api(self, lines: list, line_idx: int) -> str:
        """查找附近的 API 调用"""
        search_range = 5
        start = max(0, line_idx - search_range)
        end = min(len(lines), line_idx + search_range + 1)
        for i in range(start, end):
            m = self.HTTP_CALL_RE.search(lines[i])
            if m:
                return f'{m.group(1).upper()} {m.group(2)}'
        return ''

    def _check_perm_nearby(self, lines: list, line_idx: str) -> str:
        """检查附近是否有权限检查"""
        search_range = 10
        start = max(0, line_idx - search_range)
        end = min(len(lines), line_idx + search_range + 1)
        for i in range(start, end):
            m = self.HAS_PERM_RE.search(lines[i])
            if m:
                return m.group(1)
            m = self.AUTH_PROP_RE.search(lines[i])
            if m:
                return m.group(1)
        return ''

    def get_all_permission_codes(self) -> set:
        """获取所有前端使用的权限编码"""
        codes = set()
        # 路由 auth
        for route in self.routes:
            if route.auth:
                codes.add(route.auth)
        # 页面中的权限使用
        for entry in self.perm_entries:
            if entry.permission_code:
                for part in entry.permission_code.split('|'):
                    part = part.strip()
                    if part:
                        codes.add(part)
        return codes

    def get_routes_without_auth(self) -> list[FrontendRoute]:
        """获取没有 auth 的路由"""
        return [r for r in self.routes if not r.auth and not r.path.startswith('/')]

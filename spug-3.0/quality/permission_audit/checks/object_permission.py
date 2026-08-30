"""
对象级权限检查
检查对象级权限的实现情况。
"""
import re
from dataclasses import dataclass


@dataclass
class ObjectPermissionFinding:
    module: str
    api: str
    view_class: str
    issue: str
    severity: str
    evidence: str
    source_file: str
    line: int
    recommended_action: str


class ObjectPermissionCheck:
    """检查对象级权限实现"""

    # 对象级权限关键词
    OBJECT_PERM_KEYWORDS = [
        'check_public_space_permission',
        'apply_tenant_filter',
        'filter(tenant_id=',
        'filter(created_by=',
        'filter(department=',
        'get_object_or_404',
        'objects.get(pk=',
    ]

    def __init__(self, backend_entries: list, views: list, url_patterns: list):
        self.backend_entries = backend_entries
        self.views = views
        self.url_patterns = url_patterns
        self.findings: list[ObjectPermissionFinding] = []

    def run(self) -> list[ObjectPermissionFinding]:
        # 构建文件内容缓存
        file_cache = {}

        for view in self.views:
            if not view.file_path:
                continue

            # 读取文件内容
            if view.file_path not in file_cache:
                try:
                    with open(view.file_path, 'r', encoding='utf-8') as f:
                        file_cache[view.file_path] = f.read()
                except (IOError, UnicodeDecodeError):
                    file_cache[view.file_path] = ''
                    continue

            content = file_cache[view.file_path]

            # 检查是否有对象级权限校验
            has_object_check = any(kw in content for kw in self.OBJECT_PERM_KEYWORDS)

            # 检查详情/修改/删除接口是否有对象级权限
            if view.has_auth_on_any or view.perm_map:
                # 有权限检查但可能缺少对象级检查
                if not has_object_check:
                    # 检查是否是需要对象级权限的模块
                    module = self._get_module_from_path(view.file_path)
                    if module in ('document', 'evidence', 'regulation', 'radio_license',
                                  'contract_agreement', 'coop_task', 'department_duty_log', 'fault',
                                  'interference', 'device', 'upgrade'):
                        self.findings.append(ObjectPermissionFinding(
                            module=module,
                            api=self._find_api_for_view(view.name),
                            view_class=view.name,
                            issue="No object-level permission check found",
                            severity="medium",
                            evidence=f"View '{view.name}' has permission checks but no object-level checks "
                                     f"(no check_public_space_permission, apply_tenant_filter, or similar)",
                            source_file=view.file_path,
                            line=view.line,
                            recommended_action="Verify if object-level permission is needed for this view",
                        ))

        return self.findings

    def _get_module_from_path(self, path: str) -> str:
        """从文件路径提取模块名"""
        parts = path.replace('\\', '/').split('/')
        if 'apps' in parts:
            idx = parts.index('apps')
            if idx + 1 < len(parts):
                return parts[idx + 1]
        return ''

    def _find_api_for_view(self, view_name: str) -> str:
        """从 URL 映射中查找 View 对应的 API"""
        for entry in self.backend_entries:
            if entry.view_class == view_name:
                return entry.api
        return ''

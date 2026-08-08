"""
角色策略解析器
解析 Role/RolePolicy 模型定义和角色权限数据结构。
用于理解权限编码在数据库中的存储格式。
"""
import ast
import os
import re
from dataclasses import dataclass, field


@dataclass
class RoleModelInfo:
    """角色模型信息"""
    model_name: str = ""
    file_path: str = ""
    fields: list = field(default_factory=list)
    page_perms_field: str = ""
    group_perms_field: str = ""
    perms_version_field: str = ""
    is_system_field: str = ""
    is_global_admin_field: str = ""
    tenant_id_field: str = ""


@dataclass
class PermissionCodeInfo:
    """权限编码信息"""
    code: str = ""
    namespace: str = ""
    resource: str = ""
    action: str = ""
    source_type: str = ""  # frontend_route, frontend_button, backend_perm_map, backend_auth, database
    source_file: str = ""
    line: int = 0
    module: str = ""
    registered: bool = False
    used_by_role: bool = False
    status: str = ""
    notes: str = ""


class RolePolicyParser:
    """解析角色策略模型和数据"""

    def __init__(self, spug_api_path: str):
        self.spug_api_path = spug_api_path
        self.role_models: list[RoleModelInfo] = []
        # 权限编码格式：<namespace>.<resource>.<action>
        self.perm_code_re = re.compile(r'^([a-z_]+)\.([a-z_]+)\.([a-z_]+)$')

    def parse_models(self):
        """解析 Role 和 RolePolicy 模型定义"""
        account_models = os.path.join(self.spug_api_path, 'apps', 'account', 'models.py')
        if not os.path.isfile(account_models):
            return

        try:
            with open(account_models, 'r', encoding='utf-8') as f:
                source = f.read()
            tree = ast.parse(source, filename=account_models)
        except (SyntaxError, UnicodeDecodeError):
            return

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            # 检查是否是模型类（继承 models.Model）
            is_model = False
            for base in node.bases:
                base_name = self._get_name(base)
                if 'Model' in base_name:
                    is_model = True
                    break

            if not is_model:
                continue

            if node.name not in ('Role', 'RolePolicy'):
                continue

            info = RoleModelInfo(
                model_name=node.name,
                file_path=account_models,
            )

            for item in node.body:
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        field_name = self._get_name(target)
                        if field_name:
                            info.fields.append(field_name)
                            if 'page_perms' in field_name:
                                info.page_perms_field = field_name
                            elif 'group_perms' in field_name:
                                info.group_perms_field = field_name
                            elif 'perms_version' in field_name:
                                info.perms_version_field = field_name
                            elif 'is_system' in field_name:
                                info.is_system_field = field_name
                            elif 'is_global_admin' in field_name:
                                info.is_global_admin_field = field_name
                            elif 'tenant_id' in field_name:
                                info.tenant_id_field = field_name

            self.role_models.append(info)

    def parse_permission_code(self, code: str) -> PermissionCodeInfo:
        """解析单个权限编码"""
        code = code.strip()
        m = self.perm_code_re.match(code)
        if m:
            return PermissionCodeInfo(
                code=code,
                namespace=m.group(1),
                resource=m.group(2),
                action=m.group(3),
                status="valid",
            )
        return PermissionCodeInfo(
            code=code,
            status="invalid_format",
            notes=f"Permission code does not match <namespace>.<resource>.<action> pattern",
        )

    def get_permission_catalog(self, frontend_codes: set, backend_codes: set,
                                namespace_aliases: dict = None) -> list[PermissionCodeInfo]:
        """构建权限编码目录"""
        all_codes = frontend_codes | backend_codes
        result = []

        # 构建反向别名映射：permission_namespace -> app
        alias_map = {}
        if namespace_aliases:
            for alias in namespace_aliases.get('aliases', []):
                alias_map[alias['permission_namespace']] = alias['app']

        for code in sorted(all_codes):
            info = self.parse_permission_code(code)
            info.registered = code in backend_codes
            info.used_by_role = code in frontend_codes

            if code in frontend_codes and code in backend_codes:
                info.status = "valid"
                info.notes = "Used in both frontend and backend"
            elif code in frontend_codes and code not in backend_codes:
                info.status = "frontend_only"
                info.notes = "Used in frontend but not found in backend permission checks"
            elif code not in frontend_codes and code in backend_codes:
                info.status = "backend_only"
                info.notes = "Used in backend but not found in frontend"

            result.append(info)

        return result

    def _get_name(self, node) -> str:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return node.attr
        return ''

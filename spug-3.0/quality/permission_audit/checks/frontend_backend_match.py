"""
前后端权限一致性检查
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class MismatchFinding:
    """权限不一致发现"""
    id: str = ""
    severity: str = ""  # critical, high, medium, low, pending
    module: str = ""
    page: str = ""
    operation: str = ""
    frontend_permission: str = ""
    backend_permission: str = ""
    database_registered: str = ""
    mismatch_type: str = ""
    evidence: str = ""
    runtime_test: str = ""
    current_status: str = ""
    recommended_owner: str = ""


class FrontendBackendMatchCheck:
    """检查前后端权限一致性"""

    def __init__(self, frontend_codes: set, backend_codes: set,
                 frontend_entries: list, backend_entries: list,
                 namespace_aliases: dict = None):
        self.frontend_codes = frontend_codes
        self.backend_codes = backend_codes
        self.frontend_entries = frontend_entries
        self.backend_entries = backend_entries
        self.namespace_aliases = namespace_aliases or {}
        self.findings: list[MismatchFinding] = []

    def run(self) -> list[MismatchFinding]:
        """执行所有一致性检查"""
        self._check_frontend_only_perms()
        self._check_backend_only_perms()
        self._check_permission_mismatches()
        self._check_routes_without_auth()
        return self.findings

    def _check_frontend_only_perms(self):
        """前端使用但后端未校验的权限"""
        frontend_only = self.frontend_codes - self.backend_codes
        for code in sorted(frontend_only):
            # 检查是否是合法别名
            if self._is_alias_valid(code):
                continue

            # 找到前端使用位置
            entries = [e for e in self.frontend_entries if code in (e.permission_code or '')]
            for entry in entries:
                self.findings.append(MismatchFinding(
                    id=f"FE_ONLY_{len(self.findings)+1}",
                    severity="high",
                    module=self._extract_module(code),
                    page=entry.page,
                    operation=entry.operation,
                    frontend_permission=code,
                    backend_permission="(none)",
                    mismatch_type="frontend_only_no_backend",
                    evidence=f"Frontend uses '{code}' at {entry.source_file}:{entry.line}, but no backend @auth or PERM_MAP found",
                    current_status="open",
                    recommended_owner="backend",
                ))

    def _check_backend_only_perms(self):
        """后端校验但前端未使用的权限"""
        backend_only = self.backend_codes - self.frontend_codes
        for code in sorted(backend_only):
            if code == 'super_only':
                continue
            entries = [e for e in self.backend_entries if code in (e.permission_code or '')]
            for entry in entries:
                self.findings.append(MismatchFinding(
                    id=f"BE_ONLY_{len(self.findings)+1}",
                    severity="low",
                    module=self._extract_module(code),
                    operation=entry.operation,
                    frontend_permission="(none)",
                    backend_permission=code,
                    mismatch_type="backend_only_no_frontend",
                    evidence=f"Backend checks '{code}' at {entry.source_file}:{entry.line}, but no frontend usage found",
                    current_status="open",
                    recommended_owner="frontend",
                ))

    def _check_permission_mismatches(self):
        """检查同一操作前后端使用不同权限编码"""
        # 构建 API -> 前端权限 映射
        fe_api_perms = {}
        for entry in self.frontend_entries:
            if entry.api and entry.permission_code:
                api_key = entry.api.split()[0] if ' ' in entry.api else entry.api
                if api_key not in fe_api_perms:
                    fe_api_perms[api_key] = set()
                for part in entry.permission_code.split('|'):
                    fe_api_perms[api_key].add(part.strip())

        # 构建 API -> 后端权限 映射
        be_api_perms = {}
        for entry in self.backend_entries:
            if entry.api and entry.permission_code and entry.permission_code != 'super_only':
                api_key = entry.api
                if api_key not in be_api_perms:
                    be_api_perms[api_key] = set()
                for part in entry.permission_code.split('|'):
                    be_api_perms[api_key].add(part.strip())

        # 检查不匹配
        for api, fe_perms in fe_api_perms.items():
            be_perms = be_api_perms.get(api, set())
            if be_perms and fe_perms and not fe_perms.intersection(be_perms):
                # 前后端都校验但权限不同
                # 检查是否是合法别名
                if all(self._are_aliases(p1, p2) for p1 in fe_perms for p2 in be_perms):
                    continue
                self.findings.append(MismatchFinding(
                    id=f"MISMATCH_{len(self.findings)+1}",
                    severity="medium",
                    module=self._extract_module(next(iter(fe_perms))),
                    operation=api,
                    frontend_permission='|'.join(sorted(fe_perms)),
                    backend_permission='|'.join(sorted(be_perms)),
                    mismatch_type="different_permission_codes",
                    evidence=f"API '{api}' uses different permission codes in frontend vs backend",
                    current_status="open",
                    recommended_owner="backend",
                ))

    def _check_routes_without_auth(self):
        """检查没有 auth 的路由"""
        for entry in self.frontend_entries:
            if hasattr(entry, 'route') and not entry.route and entry.status == 'no_perm_check_nearby':
                pass  # 已在其他检查中处理

    def _is_alias_valid(self, code: str) -> bool:
        """检查权限编码是否在合法别名表中"""
        aliases = self.namespace_aliases.get('aliases', [])
        for alias in aliases:
            if code.startswith(alias['permission_namespace'] + '.'):
                return True
        return False

    def _are_aliases(self, code1: str, code2: str) -> bool:
        """检查两个权限编码是否是合法别名关系"""
        if code1 == code2:
            return True
        aliases = self.namespace_aliases.get('aliases', [])
        for alias in aliases:
            ns = alias['permission_namespace']
            if code1.startswith(ns + '.') and code2.startswith(ns + '.'):
                return True
        return False

    def _extract_module(self, code: str) -> str:
        """从权限编码提取模块名"""
        parts = code.split('.')
        if len(parts) >= 2:
            return f"{parts[0]}.{parts[1]}"
        return code

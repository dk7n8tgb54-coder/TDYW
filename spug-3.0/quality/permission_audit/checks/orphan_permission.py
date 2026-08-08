"""
孤儿权限检查
查找没有被任何代码使用的权限编码。
"""
from dataclasses import dataclass


@dataclass
class OrphanPermissionFinding:
    code: str
    source: str
    severity: str
    evidence: str
    notes: str


class OrphanPermissionCheck:
    """检查孤儿权限"""

    def __init__(self, all_codes: set, frontend_codes: set, backend_codes: set,
                 approved_exceptions: list = None):
        self.all_codes = all_codes
        self.frontend_codes = frontend_codes
        self.backend_codes = backend_codes
        self.approved_exceptions = approved_exceptions or []
        self.findings: list[OrphanPermissionFinding] = []

    def run(self) -> list[OrphanPermissionFinding]:
        # 孤儿权限：在前端或后端存在但没有对应的 API 或页面使用
        # 注意：权限可能只在后端 PERM_MAP/@auth 中使用，前端只检查路由 auth
        # 所以前端 only 的权限不一定是孤儿

        # 后端有但前端完全没用的权限
        for code in sorted(self.backend_codes - self.frontend_codes):
            if code == 'super_only':
                continue
            if self._is_approved(code):
                continue
            self.findings.append(OrphanPermissionFinding(
                code=code,
                source='backend',
                severity='low',
                evidence=f"Permission '{code}' is checked in backend but not used in any frontend route or button",
                notes="May be a legacy permission or used only for API-level access control",
            ))

        # 前端有但后端完全没校验的权限（这些已在 missing_backend_check 中标记为 high）
        # 这里只标记纯孤儿：既不在后端也不在前端路由中的权限

        return self.findings

    def _is_approved(self, code: str) -> bool:
        for exc in self.approved_exceptions:
            if exc.get('check_type') == 'orphan_permission' and code in exc.get('reason', ''):
                return True
        return False

"""
后端缺失权限检查
查找没有权限校验的 API 接口。
"""
from dataclasses import dataclass


@dataclass
class MissingBackendFinding:
    """后端权限缺失发现"""
    api: str
    http_method: str
    view_class: str
    source_file: str
    line: int
    severity: str
    evidence: str
    recommended_action: str


class MissingBackendCheck:
    """查找后端没有权限校验的接口"""

    def __init__(self, backend_entries: list, approved_exceptions: list = None):
        self.backend_entries = backend_entries
        self.approved_exceptions = approved_exceptions or []
        self.findings: list[MissingBackendFinding] = []

    def run(self) -> list[MissingBackendFinding]:
        for entry in self.backend_entries:
            # 跳过已批准的例外
            if self._is_approved_exception(entry):
                continue

            if entry.status == 'no_perm_check':
                self.findings.append(MissingBackendFinding(
                    api=entry.api,
                    http_method=entry.http_method or 'ALL',
                    view_class=entry.view_class,
                    source_file=entry.source_file,
                    line=entry.line,
                    severity='high',
                    evidence=f"View '{entry.view_class}' has no PERM_MAP and no @auth decorator. "
                             f"Non-super users can access this endpoint without any permission check. "
                             f"File: {entry.source_file}:{entry.line}",
                    recommended_action="Add PERM_MAP or @auth decorator to enforce permission checks",
                ))
            elif entry.status == 'missing_perm':
                self.findings.append(MissingBackendFinding(
                    api=entry.api,
                    http_method=entry.http_method,
                    view_class=entry.view_class,
                    source_file=entry.source_file,
                    line=entry.line,
                    severity='medium',
                    evidence=f"Method {entry.http_method} in '{entry.view_class}' has no @auth decorator. "
                             f"Other methods in the same view have permission checks. "
                             f"File: {entry.source_file}:{entry.line}. Notes: {entry.notes}",
                    recommended_action=f"Add @auth decorator to {entry.http_method} method",
                ))
            elif entry.status == 'dynamic':
                self.findings.append(MissingBackendFinding(
                    api=entry.api,
                    http_method='UNKNOWN',
                    view_class=entry.view_class,
                    source_file='',
                    line=0,
                    severity='pending',
                    evidence=f"View '{entry.view_class}' could not be resolved by static analysis. "
                             f"May be a function-based view or dynamically imported.",
                    recommended_action="Manual verification required",
                ))

        return self.findings

    def _is_approved_exception(self, entry) -> bool:
        """检查是否在已批准例外列表中"""
        for exc in self.approved_exceptions:
            if (exc.get('view_class') == entry.view_class and
                exc.get('api', '').rstrip('/') in entry.api.rstrip('/')):
                return True
        return False

"""
无效权限编码检查
"""
import re
from dataclasses import dataclass


@dataclass
class InvalidPermissionFinding:
    code: str
    source: str  # frontend / backend
    source_file: str
    line: int
    issue: str
    severity: str


class InvalidPermissionCheck:
    """检查无效的权限编码格式"""

    # 权限编码格式：<namespace>.<resource>.<action>
    PERM_CODE_RE = re.compile(r'^[a-z_]+\.[a-z_]+\.[a-z_]+$')

    # 常见 action 列表
    KNOWN_ACTIONS = {
        'view', 'add', 'create', 'change', 'edit', 'update', 'del', 'delete',
        'export', 'import', 'download', 'upload', 'approve', 'publish',
        'revoke', 'sign', 'execute', 'manage',
        # 项目特有的 action
        'history_view', 'history_add', 'history_edit', 'history_delete',
        'update_add', 'update_view', 'update_edit', 'update_del',
        'statistics_view',
    }

    def __init__(self, all_codes: dict):
        """all_codes: {code: [{source, file, line}]}"""
        self.all_codes = all_codes
        self.findings: list[InvalidPermissionFinding] = []

    def run(self) -> list[InvalidPermissionFinding]:
        for code, usages in self.all_codes.items():
            if code == 'super_only':
                continue

            # 格式检查
            if not self.PERM_CODE_RE.match(code):
                for usage in usages:
                    self.findings.append(InvalidPermissionFinding(
                        code=code,
                        source=usage.get('source', 'unknown'),
                        source_file=usage.get('file', ''),
                        line=usage.get('line', 0),
                        issue=f"Invalid format: '{code}' does not match <namespace>.<resource>.<action>",
                        severity='medium',
                    ))
                continue

            # action 检查
            parts = code.split('.')
            action = parts[2]
            if action not in self.KNOWN_ACTIONS:
                # 不一定是错误，但需要人工确认
                for usage in usages:
                    self.findings.append(InvalidPermissionFinding(
                        code=code,
                        source=usage.get('source', 'unknown'),
                        source_file=usage.get('file', ''),
                        line=usage.get('line', 0),
                        issue=f"Unknown action '{action}' in permission code '{code}'",
                        severity='low',
                    ))

        return self.findings

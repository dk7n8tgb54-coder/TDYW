#!/usr/bin/env python3
"""
全系统权限一致性审计工具 - 主入口

用法:
  python audit_permissions.py                              # 默认运行
  python audit_permissions.py --format json                # JSON 输出
  python audit_permissions.py --format csv                 # CSV 输出
  python audit_permissions.py --format markdown            # Markdown 输出
  python audit_permissions.py --output-dir /path/to/output # 指定输出目录
  python audit_permissions.py --fail-on high               # 有高风险问题返回非零
  python audit_permissions.py --fail-on medium             # 有中高风险问题返回非零
  python audit_permissions.py --runtime-tests              # 生成并运行运行时测试
"""
import argparse
import csv
import io
import json
import os
import sys
import yaml
from datetime import datetime
from pathlib import Path

# 将当前目录加入 path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.join(SCRIPT_DIR, '..'))

from parsers.frontend_parser import FrontendParser
from parsers.backend_parser import BackendParser
from parsers.route_parser import RouteParser
from parsers.role_policy_parser import RolePolicyParser
from checks.frontend_backend_match import FrontendBackendMatchCheck
from checks.missing_backend_check import MissingBackendCheck
from checks.invalid_permission import InvalidPermissionCheck
from checks.orphan_permission import OrphanPermissionCheck
from checks.object_permission import ObjectPermissionCheck
from checks.permission_cache import PermissionCacheCheck


# ─── 常量 ──────────────────────────────────────────────

SEVERITY_ORDER = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3, 'pending': 4}


# ─── 工具函数 ──────────────────────────────────────────

def load_yaml(path: str) -> dict:
    if not os.path.isfile(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def find_project_root() -> str:
    """自动发现项目根目录"""
    # 从脚本位置向上查找
    current = SCRIPT_DIR
    for _ in range(10):
        if os.path.isfile(os.path.join(current, 'AGENTS.md')):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    # 回退到上级上级
    return os.path.dirname(os.path.dirname(SCRIPT_DIR))


# ─── 主审计流程 ────────────────────────────────────────

class PermissionAuditor:
    """权限审计器"""

    def __init__(self, project_root: str = None, output_dir: str = None):
        self.project_root = project_root or find_project_root()
        self.spug_api_path = os.path.join(self.project_root, 'spug_api')
        self.spug_web_src_path = os.path.join(self.project_root, 'spug_web', 'src')
        self.output_dir = output_dir or os.path.join(
            self.project_root, 'quality', 'reports', 'permission_audit'
        )

        # 加载配置
        self.namespace_aliases = load_yaml(
            os.path.join(SCRIPT_DIR, 'namespace_aliases.yml')
        )
        self.approved_exceptions = load_yaml(
            os.path.join(SCRIPT_DIR, 'baselines', 'approved_exceptions.yml')
        )

        # 解析结果
        self.frontend_parser = None
        self.backend_parser = None
        self.route_parser = None
        self.role_policy_parser = None
        self.findings = []
        self.stats = {}

    def run(self):
        """执行完整审计"""
        print(f"[permission_audit] Project root: {self.project_root}")
        print(f"[permission_audit] Output dir: {self.output_dir}")

        # 1. 解析前端
        print("[1/8] Parsing frontend...")
        self.frontend_parser = FrontendParser(self.spug_web_src_path)
        self.frontend_parser.parse_all()
        print(f"  Routes: {len(self.frontend_parser.routes)}")
        print(f"  Permission entries: {len(self.frontend_parser.perm_entries)}")

        # 2. 解析后端 URL 路由
        print("[2/8] Parsing URL routes...")
        self.route_parser = RouteParser(self.spug_api_path)
        self.route_parser.parse_all()
        print(f"  URL patterns: {len(self.route_parser.patterns)}")

        # 3. 解析后端 View 权限
        print("[3/8] Parsing backend views...")
        self.backend_parser = BackendParser(self.spug_api_path)
        self.backend_parser.parse_all()
        self.backend_parser.build_perm_entries(self.route_parser.url_view_map)
        print(f"  Views: {len(self.backend_parser.views)}")
        print(f"  Permission entries: {len(self.backend_parser.perm_entries)}")

        # 4. 解析角色策略
        print("[4/8] Parsing role policies...")
        self.role_policy_parser = RolePolicyParser(self.spug_api_path)
        self.role_policy_parser.parse_models()
        print(f"  Role models: {len(self.role_policy_parser.role_models)}")

        # 5. 收集所有权限编码
        print("[5/8] Building permission catalog...")
        frontend_codes = self.frontend_parser.get_all_permission_codes()
        backend_codes = self.backend_parser.get_all_permission_codes()
        all_codes = frontend_codes | backend_codes
        print(f"  Frontend permission codes: {len(frontend_codes)}")
        print(f"  Backend permission codes: {len(backend_codes)}")
        print(f"  Total unique codes: {len(all_codes)}")

        # 6. 运行检查
        print("[6/8] Running checks...")
        self._run_checks(frontend_codes, backend_codes, all_codes)

        # 7. 构建统计
        print("[7/8] Building statistics...")
        self._build_stats(frontend_codes, backend_codes, all_codes)

        # 8. 生成报告
        print("[8/8] Generating reports...")
        os.makedirs(self.output_dir, exist_ok=True)
        self._generate_reports(frontend_codes, backend_codes, all_codes)

        print(f"\n[permission_audit] Done! Reports saved to: {self.output_dir}")
        self._print_summary()

    def _run_checks(self, frontend_codes: set, backend_codes: set, all_codes: set):
        """运行所有检查"""
        # 前后端一致性
        match_check = FrontendBackendMatchCheck(
            frontend_codes, backend_codes,
            self.frontend_parser.perm_entries,
            self.backend_parser.perm_entries,
            self.namespace_aliases
        )
        match_findings = match_check.run()
        self.findings.extend(match_findings)
        print(f"  Frontend-backend match: {len(match_findings)} findings")

        # 后端缺失权限
        approved_list = self.approved_exceptions.get('exceptions', [])
        missing_check = MissingBackendCheck(self.backend_parser.perm_entries, approved_list)
        missing_findings = missing_check.run()
        # 转换为统一格式
        for f in missing_findings:
            self.findings.append(type('F', (), {
                'id': f"MISSING_{len(self.findings)+1}",
                'severity': f.severity,
                'module': '',
                'page': '',
                'operation': f.api,
                'frontend_permission': '',
                'backend_permission': '',
                'database_registered': '',
                'mismatch_type': 'missing_backend_check',
                'evidence': f.evidence,
                'runtime_test': '',
                'current_status': 'open',
                'recommended_owner': 'backend',
            })())
        print(f"  Missing backend check: {len(missing_findings)} findings")

        # 无效权限编码
        all_codes_with_source = {}
        for code in all_codes:
            usages = []
            for e in self.frontend_parser.perm_entries:
                if code in (e.permission_code or ''):
                    usages.append({'source': 'frontend', 'file': e.source_file, 'line': e.line})
            for e in self.backend_parser.perm_entries:
                if code in (e.permission_code or ''):
                    usages.append({'source': 'backend', 'file': e.source_file, 'line': e.line})
            all_codes_with_source[code] = usages

        invalid_check = InvalidPermissionCheck(all_codes_with_source)
        invalid_findings = invalid_check.run()
        print(f"  Invalid permission: {len(invalid_findings)} findings")

        # 孤儿权限
        orphan_check = OrphanPermissionCheck(
            all_codes, frontend_codes, backend_codes,
            self.approved_exceptions.get('exceptions', [])
        )
        orphan_findings = orphan_check.run()
        print(f"  Orphan permission: {len(orphan_findings)} findings")

        # 对象级权限
        obj_check = ObjectPermissionCheck(
            self.backend_parser.perm_entries,
            self.backend_parser.views,
            self.route_parser.patterns
        )
        obj_findings = obj_check.run()
        print(f"  Object permission: {len(obj_findings)} findings")

        # 将各类发现合并到 findings 列表
        for f in invalid_findings:
            self.findings.append(type('F', (), {
                'id': f"INVALID_{len(self.findings)+1}",
                'severity': f.severity,
                'module': '',
                'page': '',
                'operation': '',
                'frontend_permission': f.code,
                'backend_permission': '',
                'database_registered': '',
                'mismatch_type': 'invalid_permission',
                'evidence': f"{f.issue} at {f.source_file}:{f.line}",
                'runtime_test': '',
                'current_status': 'open',
                'recommended_owner': 'backend',
            })())

        for f in orphan_findings:
            self.findings.append(type('F', (), {
                'id': f"ORPHAN_{len(self.findings)+1}",
                'severity': f.severity,
                'module': '',
                'page': '',
                'operation': '',
                'frontend_permission': '',
                'backend_permission': f.code,
                'database_registered': '',
                'mismatch_type': 'orphan_permission',
                'evidence': f.evidence,
                'runtime_test': '',
                'current_status': 'open',
                'recommended_owner': 'backend',
            })())

        for f in obj_findings:
            self.findings.append(type('F', (), {
                'id': f"OBJ_{len(self.findings)+1}",
                'severity': f.severity,
                'module': f.module,
                'page': '',
                'operation': f.api,
                'frontend_permission': '',
                'backend_permission': '',
                'database_registered': '',
                'mismatch_type': 'object_permission',
                'evidence': f.evidence,
                'runtime_test': '',
                'current_status': 'open',
                'recommended_owner': 'backend',
            })())

    def _build_stats(self, frontend_codes: set, backend_codes: set, all_codes: set):
        """构建统计数据"""
        severity_counts = {}
        for f in self.findings:
            sev = getattr(f, 'severity', 'pending')
            severity_counts[sev] = severity_counts.get(sev, 0) + 1

        mismatch_type_counts = {}
        for f in self.findings:
            mt = getattr(f, 'mismatch_type', 'unknown')
            mismatch_type_counts[mt] = mismatch_type_counts.get(mt, 0) + 1

        self.stats = {
            'total_findings': len(self.findings),
            'severity_counts': severity_counts,
            'mismatch_type_counts': mismatch_type_counts,
            'frontend_routes': len(self.frontend_parser.routes),
            'frontend_perm_entries': len(self.frontend_parser.perm_entries),
            'frontend_perm_codes': len(frontend_codes),
            'backend_views': len(self.backend_parser.views),
            'backend_perm_entries': len(self.backend_parser.perm_entries),
            'backend_perm_codes': len(backend_codes),
            'url_patterns': len(self.route_parser.patterns),
            'total_perm_codes': len(all_codes),
            'timestamp': datetime.now().isoformat(),
        }

    def _generate_reports(self, frontend_codes: set, backend_codes: set, all_codes: set):
        """生成所有报告"""
        # 1. permission_catalog.csv
        self._write_permission_catalog(frontend_codes, backend_codes)
        # 2. frontend_permission_usage.csv
        self._write_frontend_usage()
        # 3. backend_permission_usage.csv
        self._write_backend_usage()
        # 4. permission_mismatch.csv
        self._write_mismatch()
        # 5. coverage_gaps.md
        self._write_coverage_gaps()
        # 6. JSON 汇总
        self._write_json_summary()

    def _write_permission_catalog(self, frontend_codes: set, backend_codes: set):
        fpath = os.path.join(self.output_dir, 'permission_catalog.csv')
        with open(fpath, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow([
                'permission_code', 'namespace', 'resource', 'action',
                'source_type', 'source_file', 'line', 'module',
                'registered', 'used_by_role', 'status', 'notes'
            ])
            for code in sorted(frontend_codes | backend_codes):
                parts = code.split('.')
                namespace = parts[0] if len(parts) >= 1 else ''
                resource = parts[1] if len(parts) >= 2 else ''
                action = parts[2] if len(parts) >= 3 else ''

                in_fe = code in frontend_codes
                in_be = code in backend_codes
                if in_fe and in_be:
                    status = 'valid'
                    source_type = 'both'
                elif in_fe:
                    status = 'frontend_only'
                    source_type = 'frontend'
                else:
                    status = 'backend_only'
                    source_type = 'backend'

                # 找到第一个使用位置
                source_file = ''
                line = 0
                module = namespace
                for e in self.frontend_parser.perm_entries:
                    if code in (e.permission_code or ''):
                        source_file = e.source_file
                        line = e.line
                        break
                if not source_file:
                    for e in self.backend_parser.perm_entries:
                        if code in (e.permission_code or ''):
                            source_file = e.source_file
                            line = e.line
                            break

                notes = ''
                if in_fe and not in_be:
                    notes = 'Used in frontend but not found in backend permission checks'
                elif in_be and not in_fe:
                    notes = 'Used in backend but not found in frontend routes/buttons'

                w.writerow([
                    code, namespace, resource, action,
                    source_type, source_file, line, module,
                    'yes' if in_be else 'no',
                    'yes' if in_fe else 'no',
                    status, notes
                ])

    def _write_frontend_usage(self):
        fpath = os.path.join(self.output_dir, 'frontend_permission_usage.csv')
        with open(fpath, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow([
                'page', 'route', 'component', 'menu', 'operation',
                'permission_code', 'api', 'source_file', 'line', 'status', 'notes'
            ])
            for e in self.frontend_parser.perm_entries:
                w.writerow([
                    e.page, e.route, e.component, e.menu, e.operation,
                    e.permission_code, e.api, e.source_file, e.line,
                    e.status, e.notes
                ])
            # 路由级别的权限
            for r in self.frontend_parser.routes:
                if r.auth:
                    w.writerow([
                        r.component, r.path, r.component, r.title,
                        'route_access', r.auth, '', r.source_file, r.line,
                        'ok', 'Route-level permission'
                    ])
                else:
                    w.writerow([
                        r.component, r.path, r.component, r.title,
                        'route_access', '', '', r.source_file, r.line,
                        'no_auth', 'Route without auth permission'
                    ])

    def _write_backend_usage(self):
        fpath = os.path.join(self.output_dir, 'backend_permission_usage.csv')
        with open(fpath, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow([
                'api', 'http_method', 'view', 'service', 'model', 'operation',
                'login_required', 'permission_code', 'object_check',
                'tenant_check', 'source_file', 'line', 'status', 'notes'
            ])
            for e in self.backend_parser.perm_entries:
                w.writerow([
                    e.api, e.http_method, e.view_class, e.service, e.model,
                    e.operation, 'yes' if e.login_required else 'no',
                    e.permission_code, e.object_check, e.tenant_check,
                    e.source_file, e.line, e.status, e.notes
                ])

    def _write_mismatch(self):
        fpath = os.path.join(self.output_dir, 'permission_mismatch.csv')
        with open(fpath, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow([
                'id', 'severity', 'module', 'page', 'operation',
                'frontend_permission', 'backend_permission',
                'database_registered', 'mismatch_type', 'evidence',
                'runtime_test', 'current_status', 'recommended_owner'
            ])
            for finding in self.findings:
                w.writerow([
                    getattr(finding, 'id', ''),
                    getattr(finding, 'severity', ''),
                    getattr(finding, 'module', ''),
                    getattr(finding, 'page', ''),
                    getattr(finding, 'operation', ''),
                    getattr(finding, 'frontend_permission', ''),
                    getattr(finding, 'backend_permission', ''),
                    getattr(finding, 'database_registered', ''),
                    getattr(finding, 'mismatch_type', ''),
                    getattr(finding, 'evidence', ''),
                    getattr(finding, 'runtime_test', ''),
                    getattr(finding, 'current_status', ''),
                    getattr(finding, 'recommended_owner', ''),
                ])

    def _write_coverage_gaps(self):
        fpath = os.path.join(self.output_dir, 'coverage_gaps.md')
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write("# 权限审计覆盖缺口\n\n")
            f.write(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

            f.write("## 动态权限无法解析\n\n")
            dynamic_entries = [e for e in self.backend_parser.perm_entries if e.status == 'dynamic']
            if dynamic_entries:
                for e in dynamic_entries:
                    f.write(f"- API: `{e.api}` - View: `{e.view_class}` - 需人工确认\n")
            else:
                f.write("无\n")

            f.write("\n## 数据库权限数据\n\n")
            f.write("- 数据库权限数据未直接查询（需要 Docker 环境）\n")
            f.write("- 运行时测试脚本已生成，可在 Docker 环境中执行验证\n")
            f.write("- 角色权限矩阵需要从数据库中读取 Role.page_perms 数据\n")

            f.write("\n## Redis 权限缓存\n\n")
            f.write("- 缓存测试脚本已生成，可在 Docker 环境中执行\n")
            f.write("- 测试脚本位置: `quality/permission_audit/tests/runtime/test_permission_behavior.py`\n")

            f.write("\n## 前端解析限制\n\n")
            f.write("- routes.js 使用正则+状态机解析，非完整 AST\n")
            f.write("- 动态 import 页面可能未被发现\n")
            f.write("- 嵌套路由的子路由权限可能未完全覆盖\n")

            f.write("\n## 业务权限含义不明确\n\n")
            # 列出 pending 级别的发现
            pending = [f for f in self.findings if getattr(f, 'severity', '') == 'pending']
            if pending:
                for p in pending:
                    f.write(f"- {getattr(p, 'evidence', '')}\n")
            else:
                f.write("无\n")

            f.write("\n## 未纳入的条件性模块\n\n")
            f.write("- schedule（排班模块）已删除，不在审计范围\n")
            f.write("- shift_handover（交接班模块）已删除，不在审计范围\n")
            f.write("- 非正式模块（backups/scripts/locustfile 等）不在审计范围\n")

    def _write_json_summary(self):
        fpath = os.path.join(self.output_dir, 'audit_summary.json')
        summary = {
            'timestamp': self.stats.get('timestamp', ''),
            'stats': self.stats,
            'findings': [
                {
                    'id': getattr(f, 'id', ''),
                    'severity': getattr(f, 'severity', ''),
                    'module': getattr(f, 'module', ''),
                    'mismatch_type': getattr(f, 'mismatch_type', ''),
                    'evidence': getattr(f, 'evidence', ''),
                    'current_status': getattr(f, 'current_status', ''),
                }
                for f in self.findings
            ],
        }
        with open(fpath, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

    def _print_summary(self):
        """打印摘要"""
        print(f"\n{'='*60}")
        print("权限审计摘要")
        print(f"{'='*60}")
        print(f"前端路由数: {self.stats.get('frontend_routes', 0)}")
        print(f"前端权限条目: {self.stats.get('frontend_perm_entries', 0)}")
        print(f"后端 View 数: {self.stats.get('backend_views', 0)}")
        print(f"后端权限条目: {self.stats.get('backend_perm_entries', 0)}")
        print(f"URL 模式数: {self.stats.get('url_patterns', 0)}")
        print(f"权限编码总数: {self.stats.get('total_perm_codes', 0)}")
        print(f"\n发现问题: {self.stats.get('total_findings', 0)}")
        for sev in ['critical', 'high', 'medium', 'low', 'pending']:
            count = self.stats.get('severity_counts', {}).get(sev, 0)
            if count:
                print(f"  {sev}: {count}")
        print(f"\n报告位置: {self.output_dir}")

    def get_exit_code(self, fail_on: str = None) -> int:
        """根据风险阈值返回退出码"""
        if not fail_on:
            return 0
        threshold = SEVERITY_ORDER.get(fail_on, 99)
        for f in self.findings:
            sev = getattr(f, 'severity', 'pending')
            if SEVERITY_ORDER.get(sev, 99) <= threshold:
                return 1
        return 0


# ─── CLI ───────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='全系统权限一致性审计工具'
    )
    parser.add_argument(
        '--format', choices=['json', 'csv', 'markdown'],
        default='csv',
        help='输出格式 (默认: csv)'
    )
    parser.add_argument(
        '--output-dir',
        default=None,
        help='输出目录 (默认: quality/reports/permission_audit/)'
    )
    parser.add_argument(
        '--fail-on', choices=['high', 'medium', 'low'],
        default=None,
        help='存在指定级别及以上问题时返回非零退出码'
    )
    parser.add_argument(
        '--project-root',
        default=None,
        help='项目根目录 (默认: 自动发现)'
    )
    parser.add_argument(
        '--runtime-tests',
        action='store_true',
        help='生成运行时权限行为测试脚本'
    )

    args = parser.parse_args()

    auditor = PermissionAuditor(
        project_root=args.project_root,
        output_dir=args.output_dir
    )

    auditor.run()

    if args.runtime_tests:
        print("\n[runtime_tests] 生成运行时测试脚本...")
        cache_check = PermissionCacheCheck()
        script_content = cache_check.generate_runtime_test_script()
        runtime_script_path = os.path.join(
            SCRIPT_DIR, 'tests', 'runtime', 'test_permission_behavior.py'
        )
        os.makedirs(os.path.dirname(runtime_script_path), exist_ok=True)
        with open(runtime_script_path, 'w', encoding='utf-8') as f:
            f.write(script_content)
        print(f"  生成: {runtime_script_path}")
        print(f"  运行: docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test "
              f"python -m quality.permission_audit.tests.runtime.test_permission_behavior")

    exit_code = auditor.get_exit_code(args.fail_on)
    sys.exit(exit_code)


if __name__ == '__main__':
    main()

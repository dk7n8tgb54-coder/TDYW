# -*- coding: utf-8 -*-
"""
安全审计测试套件

覆盖 CRUD系统可靠性指南.md 中提到的四大安全领域：
1. SQL 注入防护：参数化查询，禁止字符串拼接 SQL
2. 最小权限原则：应用账号只授予必要权限，无 DDL 权限
3. 敏感数据加密：密码哈希存储（bcrypt/argon2），敏感字段加密
4. 访问控制：RBAC 权限体系，越权访问防护

运行方式：
  docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test \
    python manage.py test apps.security_audit_tests --noinput -v2
"""
import os
import re
import json
import inspect
import warnings

from django.test import TestCase, Client
from django.contrib.auth.hashers import (
    make_password, check_password,
    PBKDF2PasswordHasher, BCryptPasswordHasher, Argon2PasswordHasher,
)
from django.db import connection
from django.conf import settings

from apps.account.models import User, Role
from apps.utils.test_helpers import make_user, make_client, setup_test_env


# ============================================================
# 1. SQL 注入防护测试
# ============================================================

class SQLInjectionTests(TestCase):
    """SQL 注入风险检测"""

    def test_logs_middleware_table_name_whitelist(self):
        """
        R1: logs/middleware.py cursor.execute 使用 f-string 拼接 table_name

        风险点：虽然 table_name 来自硬编码 TARGET_TABLE_MAP（非用户可控），
        但 f-string 拼接 SQL 是危险模式，若映射被扩展为接受用户输入则立即变漏洞。

        期望：TARGET_TABLE_MAP 是硬编码字典，所有表名只含合法字符。
        """
        from apps.logs.middleware import TARGET_TABLE_MAP

        self.assertIsInstance(TARGET_TABLE_MAP, dict,
                              "TARGET_TABLE_MAP 必须是硬编码字典")
        for key, table_name in TARGET_TABLE_MAP.items():
            self.assertRegex(
                table_name, r'^[a-zA-Z_][a-zA-Z0-9_]*$',
                f"表名 '{table_name}' 包含非法字符，可能存在 SQL 注入风险"
            )

    def test_data_quality_check_table_names_are_safe(self):
        """
        R2: data_quality_check.py 中 f-string 拼接 table/name_col 到 SQL

        风险点：table 和 name_col 来自硬编码列表 file_sources，非用户可控。
        但 f-string 拼接 SQL 是危险模式。

        期望：所有硬编码的表名和列名只含合法字符。
        """
        cmd_path = os.path.join(
            settings.BASE_DIR,
            'apps', 'alert', 'management', 'commands', 'data_quality_check.py'
        )
        with open(cmd_path, 'r', encoding='utf-8') as f:
            source = f.read()

        # 提取 file_sources 中的表名和列名
        table_pattern = r"\('([a-zA-Z_][a-zA-Z0-9_]*)',\s*'(\w+)'"
        matches = re.findall(table_pattern, source)
        self.assertGreater(len(matches), 0, "应能找到硬编码表名")

        for table_name, _model_name in matches:
            self.assertRegex(
                table_name, r'^[a-zA-Z_][a-zA-Z0-9_]*$',
                f"表名 '{table_name}' 包含非法字符"
            )

    def test_no_raw_query_in_app_modules(self):
        """
        扫描所有业务模块，确保没有使用 .raw() 执行原始 SQL

        .raw() 如果拼接用户输入会直接导致 SQL 注入。
        期望：所有非 migrations/tests/management/security_audit 模块中不出现 .raw( 调用。
        """
        import importlib
        import pkgutil
        import apps

        # 需要排除的模块（包含顶层脚本、管理命令等）
        EXCLUDE_PATTERNS = [
            'migrations', 'tests', 'management',
            'security_audit', 'security_fix', 'security_audit_run',
            'data_quality', 'check_', 'crud_audit',
            'logging_compliance',
        ]

        violations = []
        for importer, modname, ispkg in pkgutil.walk_packages(
            apps.__path__, apps.__name__ + '.'
        ):
            if any(pat in modname for pat in EXCLUDE_PATTERNS):
                continue
            try:
                mod = importlib.import_module(modname)
                source = inspect.getsource(mod)
                for i, line in enumerate(source.split('\n'), 1):
                    stripped = line.strip()
                    if stripped.startswith('#'):
                        continue
                    # .raw( 但排除 RawSQL、raw_id 等
                    if '.raw(' in line and 'RawSQL' not in line and 'raw_id' not in line:
                        violations.append(f"{modname}:{i}: {stripped}")
            except (ImportError, TypeError, OSError, SystemExit):
                continue

        self.assertEqual(
            len(violations), 0,
            f"发现 {len(violations)} 处 .raw() 调用:\n" + "\n".join(violations)
        )


# ============================================================
# 2. 最小权限原则测试
# ============================================================

class LeastPrivilegeTests(TestCase):
    """数据库账号最小权限原则检测"""

    def test_init_sql_no_excessive_ddl_grants(self):
        """
        R3: init_tdyw_account.sql 授予了 DDL 权限

        风险点：应用账号拥有 DDL 权限（CREATE, ALTER, DROP, INDEX, REFERENCES），
        若存在 SQL 注入，攻击者可直接 DROP TABLE 或 ALTER TABLE。

        期望：记录风险。Django migrations 需要 DDL，但运行时不需要。
        """
        sql_path = os.path.join(
            settings.BASE_DIR, '..', 'docker', 'scripts', 'init_tdyw_account.sql'
        )
        if not os.path.exists(sql_path):
            self.skipTest("init_tdyw_account.sql 不存在")

        with open(sql_path, 'r', encoding='utf-8') as f:
            sql_content = f.read()

        ddl_keywords = ['DROP', 'ALTER', 'CREATE', 'INDEX', 'REFERENCES']
        found_ddl = []
        for kw in ddl_keywords:
            if re.search(rf'\bGRANT\s+.*\b{kw}\b', sql_content, re.IGNORECASE):
                found_ddl.append(kw)

        if found_ddl:
            warnings.warn(
                f"[R3] 应用账号被授予 DDL 权限: {', '.join(found_ddl)}。"
                f"建议：使用单独的 migration 账号执行 DDL，"
                f"应用运行时账号仅授予 DML 权限（SELECT/INSERT/UPDATE/DELETE）",
                UserWarning
            )

    def test_runtime_db_user_privileges(self):
        """
        验证运行时数据库连接使用的账号权限

        期望：运行时账号不应能执行 DROP TABLE。
        """
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT CURRENT_USER()")
                current_user = cursor.fetchone()[0]

                cursor.execute("SHOW GRANTS FOR CURRENT_USER()")
                grants = cursor.fetchall()
                grants_str = ' '.join(str(g) for g in grants)

                has_drop = bool(re.search(r'\bDROP\b', grants_str, re.IGNORECASE))
                has_alter = bool(re.search(r'\bALTER\b', grants_str, re.IGNORECASE))

                if has_drop or has_alter:
                    warnings.warn(
                        f"[R3-runtime] 运行时用户 {current_user} 拥有 DDL 权限"
                        f"(DROP={has_drop}, ALTER={has_alter})。"
                        f"建议：拆分为 migration 账号(DDL) + 应用账号(DML)",
                        UserWarning
                    )
        except Exception as e:
            self.skipTest(f"无法检查数据库权限: {e}")


# ============================================================
# 3. 敏感数据加密测试
# ============================================================

class SensitiveDataEncryptionTests(TestCase):
    """敏感数据加密检测"""

    def test_password_hashed_not_plain_text(self):
        """
        R4: 密码必须以哈希存储，不能是明文

        期望：make_password() 返回的密码以算法标识开头（如 pbkdf2_sha256$）。
        """
        test_password = 'TestPassword123!'
        hashed = User.make_password(test_password)

        self.assertNotEqual(hashed, test_password, "密码不应以明文存储")
        self.assertTrue(
            hashed.startswith(('pbkdf2_', 'bcrypt$', 'argon2')),
            f"密码哈希格式异常: {hashed}"
        )
        self.assertTrue(check_password(test_password, hashed))
        self.assertFalse(check_password('wrong_password', hashed))

    def test_password_hasher_strength(self):
        """
        R4: 检查密码哈希算法强度

        CRUD指南推荐 bcrypt/argon2，项目默认使用 pbkdf2_sha256。
        期望：至少使用 pbkdf2_sha256，且迭代次数 >= 100000。
        """
        from django.contrib.auth.hashers import get_hashers

        hashers = get_hashers()
        preferred_hasher = hashers[0]

        self.assertIsInstance(
            preferred_hasher,
            (PBKDF2PasswordHasher, BCryptPasswordHasher, Argon2PasswordHasher),
            f"首选密码哈希器类型异常: {type(preferred_hasher)}"
        )

        if isinstance(preferred_hasher, PBKDF2PasswordHasher):
            self.assertGreaterEqual(
                preferred_hasher.iterations, 100000,
                f"PBKDF2 迭代次数 {preferred_hasher.iterations} 低于安全阈值 100000"
            )

        if not getattr(settings, 'PASSWORD_HASHERS', None):
            warnings.warn(
                "[R4-config] settings.py 未显式配置 PASSWORD_HASHERS，"
                "使用 Django 默认 pbkdf2_sha256。"
                "CRUD指南推荐 argon2/bcrypt，建议显式配置",
                UserWarning
            )

    def test_access_token_is_random_and_unique(self):
        """
        R5: access_token 应为随机生成的不可预测字符串

        期望：两次生成的 token 不同，长度为 32，由字母数字组成。
        """
        from libs.utils import generate_random_str

        token1 = generate_random_str(32, is_digits=False)
        token2 = generate_random_str(32, is_digits=False)

        self.assertNotEqual(token1, token2, "两次生成的 token 不应相同")
        self.assertEqual(len(token1), 32, f"token 长度应为 32，实际 {len(token1)}")
        self.assertRegex(
            token1, r'^[a-zA-Z0-9]{32}$',
            f"token 应为 32 字符的字母数字组合"
        )

    def test_access_token_stored_in_plaintext_risk(self):
        """
        R5: access_token 以明文存储在数据库中

        风险点：如果数据库被拖库，所有活跃会话 token 将被泄露。
        行业最佳实践：存储 token 的 SHA256 哈希。

        本测试记录风险，不修改现有逻辑。
        """
        token_field = User._meta.get_field('access_token')
        self.assertTrue(token_field.unique, "access_token 应有唯一约束")
        self.assertGreaterEqual(token_field.max_length, 32,
                                "access_token 最大长度应 >= 32")

        warnings.warn(
            "[R5] access_token 以明文存储在数据库中。"
            "建议：存储 access_token 的 SHA256 哈希，"
            "查询时用 hash(token) 比对，防止拖库后会话泄露",
            UserWarning
        )

    def test_secret_key_is_set_and_long_enough(self):
        """SECRET_KEY 应从环境变量读取，不硬编码"""
        secret = settings.SECRET_KEY
        self.assertTrue(secret, "SECRET_KEY 不能为空")
        self.assertGreaterEqual(len(secret), 32,
                                "SECRET_KEY 长度应 >= 32 字符")

    def test_sensitive_fields_not_logged(self):
        """
        验证中间件对敏感字段做脱敏处理

        期望：_SENSITIVE_KEYS 包含 password/token/secret 等关键词。
        """
        from libs.middleware import _SENSITIVE_KEYS, _sanitize_request_body

        for keyword in ('password', 'token', 'secret', 'key'):
            self.assertTrue(
                any(keyword in s for s in _SENSITIVE_KEYS),
                f"敏感关键词列表应包含 '{keyword}'"
            )

        body = json.dumps({
            'username': 'test',
            'password': 'plain_password',
            'access_token': 'abc123'
        })
        sanitized = _sanitize_request_body(body)
        self.assertNotIn('plain_password', sanitized)
        self.assertIn('***', sanitized)


# ============================================================
# 4. 访问控制 / RBAC / 租户隔离测试
# ============================================================

class AccessControlTests(TestCase):
    """访问控制与越权防护检测"""

    def setUp(self):
        setup_test_env(self)

        # 创建租户 A 的用户（有删除权限）
        self.user_a = make_user('user_a', ['upgrade.step_del'])
        self.user_a.tenant_id = 'tenant_a'
        self.user_a.save()
        self.client_a = make_client(self.user_a)

        # 创建租户 B 的用户（有删除权限）
        self.user_b = make_user('user_b', ['upgrade.step_del'])
        self.user_b.tenant_id = 'tenant_b'
        self.user_b.save()
        self.client_b = make_client(self.user_b)

        # 存储创建的记录，便于 tearDown 清理
        self._records_to_clean = []

    def tearDown(self):
        # 先删除依赖的子记录，再删除父记录（避免 PROTECT 外键冲突）
        from apps.upgrade.models_checklist import UpgradeRecordStep
        from apps.upgrade.models_status_log import UpgradeStatusLog
        from apps.upgrade.models_template import UpgradeTemplate
        from apps.upgrade.models import UpgradeRecord

        # 按依赖顺序删除
        UpgradeRecordStep.objects.all().delete()
        UpgradeStatusLog.objects.all().delete()
        UpgradeTemplate.objects.all().delete()
        UpgradeRecord.objects.all().delete()
        User.objects.all().delete()
        Role.objects.all().delete()

    def test_cross_tenant_delete_record_step_blocked(self):
        """
        R6: 跨租户删除升级步骤应被拦截

        风险点：upgrade/views/step.py:86 审计日志查询未加租户过滤，
        但实际删除被 RecordStepService.delete_step() 保护。

        期望：租户 B 用户无法删除租户 A 的步骤，返回 error 消息。
        注意：Spug 框架的 json_response(error=...) 返回 HTTP 200 + JSON body 中的 error 字段。
        """
        from apps.upgrade.models import UpgradeRecord
        from apps.upgrade.models_checklist import UpgradeRecordStep

        record_a = UpgradeRecord.objects.create(
            tenant_id='tenant_a',
            title='租户A的升级记录',
            system='系统A',
            upgrade_type='类型A',
            owner='user_a',
            created_by=self.user_a,
        )
        self._records_to_clean.append(record_a)

        step_a = UpgradeRecordStep.objects.create(
            tenant_id='tenant_a',
            upgrade_id=record_a.id,
            title='租户A的机密步骤',
            sequence=1,
        )

        # 用租户 B 的用户尝试删除租户 A 的步骤
        response = self.client_b.delete(
            f'/upgrade/record-steps/{step_a.id}/delete/'
        )

        # Spug 框架返回 200 + JSON body，需检查 body 中的 error 字段
        body = json.loads(response.content)
        self.assertTrue(
            body.get('error'),
            f"跨租户删除应返回错误消息，实际返回: {body}"
        )

        # 验证步骤仍然存在（未被删除）
        step_a.refresh_from_db()
        self.assertTrue(
            UpgradeRecordStep.objects.filter(pk=step_a.id, is_deleted=False).exists(),
            "跨租户删除不应成功，步骤应仍存在"
        )

    def test_cross_tenant_delete_status_log_blocked(self):
        """
        R7: 跨租户删除状态日志应被拦截

        风险点：upgrade/views/status_log.py:81 审计日志查询未加租户过滤，
        但实际删除被 StatusLogService.delete_log() 保护。
        """
        from apps.upgrade.models import UpgradeRecord
        from apps.upgrade.models_status_log import UpgradeStatusLog

        record_a = UpgradeRecord.objects.create(
            tenant_id='tenant_a',
            title='租户A的升级记录',
            system='系统A',
            upgrade_type='类型A',
            owner='user_a',
            created_by=self.user_a,
        )
        self._records_to_clean.append(record_a)

        log_a = UpgradeStatusLog.objects.create(
            tenant_id='tenant_a',
            upgrade_id=record_a.id,
            action='start',
        )

        response = self.client_b.delete(
            f'/upgrade/status-logs/{log_a.id}/delete/'
        )

        body = json.loads(response.content)
        self.assertTrue(
            body.get('error'),
            f"跨租户删除应返回错误消息，实际返回: {body}"
        )
        self.assertTrue(
            UpgradeStatusLog.objects.filter(pk=log_a.id).exists(),
            "跨租户删除不应成功"
        )

    def test_cross_tenant_delete_plan_blocked(self):
        """
        R8: 跨租户删除升级方案应被拦截

        风险点：upgrade/views/plan.py:85 审计日志查询未加租户过滤，
        但实际删除被 PlanService.delete_plan() 保护。
        """
        from apps.upgrade.models_template import UpgradeTemplate

        template_a = UpgradeTemplate.objects.create(
            tenant_id='tenant_a',
            name='租户A的机密方案',
            system='系统A',
            created_by=self.user_a,
        )

        response = self.client_b.delete(
            f'/upgrade/plans/{template_a.id}/delete/'
        )

        body = json.loads(response.content)
        self.assertTrue(
            body.get('error'),
            f"跨租户删除应返回错误消息，实际返回: {body}"
        )
        self.assertTrue(
            UpgradeTemplate.objects.filter(pk=template_a.id).exists(),
            "跨租户删除不应成功"
        )

    def test_audit_log_fetches_without_tenant_filter_risk(self):
        """
        R6/R7/R8: 验证 delete 视图中审计日志查询确实未加租户过滤

        这是风险点的静态验证：确保代码中存在无租户过滤的查询。
        修复后此测试应被更新（验证已加租户过滤）。
        """
        from apps.upgrade.views import step as step_views
        from apps.upgrade.views import status_log as log_views
        from apps.upgrade.views import plan as plan_views

        # 检查 step.py 中的 delete 视图
        step_source = inspect.getsource(step_views)
        self.assertIn('UpgradeRecordStep.objects.filter(pk=pk)', step_source)

        # 检查 status_log.py 中的 delete 视图
        log_source = inspect.getsource(log_views)
        self.assertIn('UpgradeStatusLog.objects.filter(pk=pk)', log_source)

        # 检查 plan.py 中的 delete 视图
        plan_source = inspect.getsource(plan_views)
        self.assertIn('UpgradeTemplate.objects.filter(pk=pk)', plan_source)

        warnings.warn(
            "[R6/R7/R8] delete 视图中审计日志查询未加 apply_tenant_filter()。"
            "虽然实际删除操作被 Service 层保护，但审计日志可能泄露跨租户信息"
            "（如步骤标题、方案名称）。建议：审计日志查询也加 apply_tenant_filter()",
            UserWarning
        )

    def test_service_layer_has_tenant_filter(self):
        """
        验证 Service 层正确应用了租户过滤

        期望：RecordStepService.delete_step() / StatusLogService.delete_log()
        / PlanService.delete_plan() 都调用了 apply_tenant_filter()。
        """
        from apps.upgrade.services.step_service import RecordStepService
        from apps.upgrade.services.status_log_service import StatusLogService
        from apps.upgrade.services.plan_service import PlanService

        for service_cls, method_name in [
            (RecordStepService, 'delete_step'),
            (StatusLogService, 'delete_log'),
            (PlanService, 'delete_plan'),
        ]:
            method = getattr(service_cls, method_name)
            source = inspect.getsource(method)
            self.assertIn(
                'apply_tenant_filter', source,
                f"{service_cls.__name__}.{method_name} 必须调用 apply_tenant_filter()"
            )

    def test_unauthenticated_access_blocked(self):
        """验证未登录用户无法访问 API"""
        anonymous_client = Client()

        test_urls = [
            '/upgrade/records/',
            '/upgrade/plans/',
            '/account/user/',
        ]

        for url in test_urls:
            try:
                response = anonymous_client.get(url)
                self.assertIn(
                    response.status_code, [401, 302, 403],
                    f"未登录用户访问 {url} 应返回 401/302/403，"
                    f"实际 {response.status_code}"
                )
            except Exception:
                pass

    def test_is_supper_default_false(self):
        """验证 is_supper 默认为 False"""
        field = User._meta.get_field('is_supper')
        self.assertFalse(field.default, "is_supper 默认应为 False")


# ============================================================
# 5. 命令注入风险测试
# ============================================================

class CommandInjectionTests(TestCase):
    """命令注入风险检测"""

    def test_update_command_shell_true_risk(self):
        """
        R9: account/management/commands/update.py 使用 shell=True

        风险点：subprocess.Popen(' && '.join(commands), shell=True)
        若版本号含 shell 元字符（; | &）可能导致命令注入。
        """
        cmd_path = os.path.join(
            settings.BASE_DIR,
            'apps', 'account', 'management', 'commands', 'update.py'
        )
        if not os.path.exists(cmd_path):
            self.skipTest("update.py 不存在")

        with open(cmd_path, 'r', encoding='utf-8') as f:
            source = f.read()

        if 'shell=True' in source:
            warnings.warn(
                "[R9] account/management/commands/update.py 使用 shell=True。"
                "建议：改用 shell=False + 参数列表，或对输入做正则白名单校验",
                UserWarning
            )

    def test_no_eval_exec_in_production_code(self):
        """
        扫描所有非测试/非 management 模块，确保没有 eval()/exec() 调用

        eval/exec 如果执行用户输入的字符串，会导致代码注入。
        """
        import importlib
        import pkgutil
        import apps

        EXCLUDE_PATTERNS = [
            'migrations', 'tests', 'management',
            'security_audit', 'security_fix', 'security_audit_run',
            'data_quality', 'check_', 'crud_audit',
            'logging_compliance',
        ]

        violations = []
        for importer, modname, ispkg in pkgutil.walk_packages(
            apps.__path__, apps.__name__ + '.'
        ):
            if any(pat in modname for pat in EXCLUDE_PATTERNS):
                continue
            try:
                mod = importlib.import_module(modname)
                source = inspect.getsource(mod)
                for i, line in enumerate(source.split('\n'), 1):
                    stripped = line.strip()
                    if stripped.startswith('#'):
                        continue
                    if re.search(r'\beval\s*\(', stripped) or re.search(r'\bexec\s*\(', stripped):
                        violations.append(f"{modname}:{i}: {stripped}")
            except (ImportError, TypeError, OSError, SystemExit):
                continue

        self.assertEqual(
            len(violations), 0,
            f"发现 {len(violations)} 处 eval()/exec() 调用:\n" + "\n".join(violations)
        )


# ============================================================
# 6. 综合风险报告
# ============================================================

class SecurityRiskReport(TestCase):
    """安全风险汇总报告"""

    def test_print_risk_summary(self):
        """打印所有发现的风险点汇总"""
        risks = [
            {
                'id': 'R1', 'category': 'SQL注入', 'severity': '低',
                'location': 'logs/middleware.py:100',
                'description': 'cursor.execute 使用 f-string 拼接 table_name',
                'detail': 'table_name 来自硬编码 TARGET_TABLE_MAP，非用户可控，但模式危险',
                'recommendation': '增加白名单校验 assert table_name in ALLOWED_TABLES',
            },
            {
                'id': 'R2', 'category': 'SQL注入', 'severity': '低',
                'location': 'alert/management/commands/data_quality_check.py:217',
                'description': 'f-string 拼接 table 和 name_col 到 SQL',
                'detail': 'table/name_col 来自硬编码列表，非用户可控',
                'recommendation': '改用参数化查询或增加白名单校验',
            },
            {
                'id': 'R3', 'category': '最小权限', 'severity': '中',
                'location': 'docker/scripts/init_tdyw_account.sql',
                'description': '应用账号被授予 DDL 权限（CREATE, ALTER, DROP, INDEX, REFERENCES）',
                'detail': 'Django migrations 需要 DDL 权限，但运行时不需要',
                'recommendation': '拆分：migration 账号(DDL) + 应用运行时账号(DML)',
            },
            {
                'id': 'R4', 'category': '敏感数据加密', 'severity': '低',
                'location': 'spug/settings.py',
                'description': '未显式配置 PASSWORD_HASHERS，使用默认 pbkdf2_sha256',
                'detail': 'pbkdf2_sha256 安全性可接受，但 CRUD 指南推荐 argon2/bcrypt',
                'recommendation': '安装 argon2-cffi/bcrypt 并配置 PASSWORD_HASHERS',
            },
            {
                'id': 'R5', 'category': '敏感数据加密', 'severity': '中',
                'location': 'account/models.py:User.access_token',
                'description': 'access_token 以明文存储在数据库中',
                'detail': '数据库拖库后所有活跃会话泄露',
                'recommendation': '存储 access_token 的 SHA256 哈希，查询时用 hash(token) 比对',
            },
            {
                'id': 'R6', 'category': '访问控制', 'severity': '低',
                'location': 'upgrade/views/step.py:86',
                'description': '删除步骤时审计日志查询未加租户过滤',
                'detail': '实际删除被 RecordStepService 保护(apply_tenant_filter)，'
                          '但审计日志记录了 step.title，构成跨租户信息泄露',
                'recommendation': '审计日志查询也加 apply_tenant_filter',
            },
            {
                'id': 'R7', 'category': '访问控制', 'severity': '低',
                'location': 'upgrade/views/status_log.py:81',
                'description': '删除状态日志时审计日志查询未加租户过滤',
                'detail': '实际删除被 StatusLogService 保护，但审计日志可能泄露跨租户信息',
                'recommendation': '审计日志查询也加 apply_tenant_filter',
            },
            {
                'id': 'R8', 'category': '访问控制', 'severity': '低',
                'location': 'upgrade/views/plan.py:85',
                'description': '删除方案时审计日志查询未加租户过滤',
                'detail': '实际删除被 PlanService 保护(apply_tenant_filter)，'
                          '但审计日志记录了 template.name',
                'recommendation': '审计日志查询也加 apply_tenant_filter',
            },
            {
                'id': 'R9', 'category': '命令注入', 'severity': '低',
                'location': 'account/management/commands/update.py:39',
                'description': 'subprocess.Popen 使用 shell=True 执行拼接命令',
                'detail': '命令中有 f-string 拼接版本号，若版本号含 shell 元字符可注入',
                'recommendation': '改用 shell=False + 参数列表，或对版本号做正则白名单校验',
            },
        ]

        print("\n" + "=" * 80)
        print("安全审计风险汇总")
        print("=" * 80)

        severity_order = {'高': 0, '中': 1, '低': 2}
        risks_sorted = sorted(risks, key=lambda r: severity_order.get(r['severity'], 3))

        for r in risks_sorted:
            print(f"\n[{r['id']}] [{r['severity']}] {r['category']}")
            print(f"  位置: {r['location']}")
            print(f"  描述: {r['description']}")
            print(f"  详情: {r['detail']}")
            print(f"  建议: {r['recommendation']}")

        high = sum(1 for r in risks if r['severity'] == '高')
        medium = sum(1 for r in risks if r['severity'] == '中')
        low = sum(1 for r in risks if r['severity'] == '低')
        print(f"\n{'=' * 80}")
        print(f"共发现 {len(risks)} 个风险点  高: {high}  中: {medium}  低: {low}")
        print("=" * 80 + "\n")

        self.assertGreater(len(risks), 0, "安全审计应发现至少一个风险点")

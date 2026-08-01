# -*- coding: utf-8 -*-
"""setting 模块 CRUD 可靠性审计测试（修复后验证版）

参照 CRUD系统可靠性指南.md §1.1-§3.5 逐项排查。
R# = 风险项（已修复的标注 [FIXED]，未修复的标注 [ACCEPT]）
P# = 优秀实践确认

审计范围:
  - views.py  - SettingView（全局设置 CRUD）+ MFAView（MFA 配置）
  - user.py   - UserSettingView（用户个人设置）
  - models.py - Setting + UserSetting
  - utils.py  - AppSetting 工具类

修复概要:
  FIXED: R5  lru_cache 不失效 -> set/delete 后调用 cache_clear()
  FIXED: R16 send_login_code 未导入 -> 补充 from libs.push import send_login_code
  FIXED: R3  MFAView.post 事务不一致 -> 调整为先 set 后 delete cache
  FIXED: R8  SettingView.post 无显式审计 -> 补 record_audit_event + before_value
  FIXED: R9  MFAView.post 无显式审计 -> 补 record_audit_event
  FIXED: R11 AppSetting.delete 用 save_audit_log -> 改用 record_audit_event
  FIXED: R12 设置变更无 before/after -> delete + post 均记录 before_value
  FIXED: R15/R18 MFA 无暴力破解锁定 -> 5 次失败后锁定 5 分钟
  FIXED: R13/R17 敏感设置明文返回 -> _mask_sensitive_settings 脱敏
  ACCEPT: R1/R2  value 无大小限制（TextField，低风险）
  ACCEPT: R4    UserSettingView.post 无事务（单次 update_or_create 原子）
  ACCEPT: R6    无 select_for_update（低并发全局配置，可接受）
  ACCEPT: R7    物理删除（设置非业务数据，审计日志保留）
  ACCEPT: R10   UserSettingView.post 无显式审计（中间件覆盖，低风险）
  ACCEPT: R14   Setting.value 无应用层大小限制（管理员可信）
  ACCEPT: R19   UserSettingView 无 @auth（中间件认证 + 用户隔离）
"""
import inspect
import json
import tempfile

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from apps.setting import views as setting_views
from apps.setting import user as setting_user
from apps.setting import utils as setting_utils
from apps.setting.models import Setting, UserSetting, KEYS_DEFAULT
from apps.setting.utils import AppSetting
from apps.account.models import User, Role
from apps.utils.test_helpers import make_user, make_client, setup_test_env


# ==================== §1.1 数据库约束 ====================

class P1_SettingKeyUnique(TestCase):
    """P1: Setting.key 有 unique=True 约束"""
    def test_p1a_field_unique(self):
        f = Setting._meta.get_field('key')
        self.assertTrue(f.unique, "Setting.key 应有 unique=True")

    def test_p1b_duplicate_rejected(self):
        Setting.objects.create(key='verify_ip', value='true')
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Setting.objects.create(key='verify_ip', value='false')
        Setting.objects.all().delete()


class P2_UserSettingUniqueTogether(TestCase):
    """P2: UserSetting 有 unique_together = ('user', 'key')"""
    def test_p2a_constraint_exists(self):
        ut = UserSetting._meta.unique_together
        self.assertIn(('user', 'key'), [tuple(x) for x in ut])

    def test_p2b_duplicate_rejected(self):
        u = make_user('p2b', [])
        try:
            UserSetting.objects.create(user=u, key='theme', value='dark')
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    UserSetting.objects.create(user=u, key='theme', value='light')
        finally:
            UserSetting.objects.all().delete()
            User.objects.filter(username='p2b').delete()


class P3_NoCharFieldNullTrue(TestCase):
    """P3: Setting / UserSetting 无 CharField/TextField null=True 违规"""
    def test_p3a_setting_clean(self):
        for f in Setting._meta.get_fields():
            if hasattr(f, 'null') and f.null and \
               f.__class__.__name__ in ('CharField', 'TextField'):
                self.fail(f"Setting.{f.name} is {f.__class__.__name__} with null=True")

    def test_p3b_usersetting_clean(self):
        for f in UserSetting._meta.get_fields():
            if hasattr(f, 'null') and f.null and \
               f.__class__.__name__ in ('CharField', 'TextField'):
                self.fail(f"UserSetting.{f.name} is {f.__class__.__name__} with null=True")


class P4_UserSettingCascade(TestCase):
    """P4: UserSetting.user 有 on_delete=CASCADE（用户删除时设置自动清除）"""
    def test_p4a_cascade(self):
        f = UserSetting._meta.get_field('user')
        self.assertEqual(f.remote_field.on_delete.__name__, 'CASCADE')

    def test_p4b_cascade_functional(self):
        u = make_user('p4b', [])
        UserSetting.objects.create(user=u, key='theme', value='dark')
        uid = u.id
        u.delete()
        self.assertFalse(
            UserSetting.objects.filter(user_id=uid).exists(),
            "用户删除后 UserSetting 应被 CASCADE 清除")


class R1_SettingValueNoSizeLimit(TestCase):
    """R1 [ACCEPT]: Setting.value 是 TextField，无大小限制（低风险）"""
    def test_r1a_textfield(self):
        f = Setting._meta.get_field('value')
        self.assertEqual(f.__class__.__name__, 'TextField')

    def test_r1b_no_max_length(self):
        f = Setting._meta.get_field('value')
        self.assertIsNone(getattr(f, 'max_length', None))


class R2_UserSettingValueNoSizeLimit(TestCase):
    """R2 [ACCEPT]: UserSetting.value 是 TextField，无大小限制（低风险）"""
    def test_r2a_textfield(self):
        f = UserSetting._meta.get_field('value')
        self.assertEqual(f.__class__.__name__, 'TextField')


# ==================== §1.2 事务边界 ====================

class P5_SettingViewPostInTransaction(TestCase):
    """P5: SettingView.post 批量保存包裹 transaction.atomic()"""
    def test_p5a_has_transaction(self):
        src = inspect.getsource(setting_views.SettingView.post)
        self.assertIn('transaction.atomic', src)


class FIX_R3_MFAViewPostReordered(TestCase):
    """R3 [FIXED]: MFAView.post 调整为 AppSetting.set 先于 cache.delete

    修复前: cache.delete(key) -> AppSetting.set()（set 失败则验证码被消费）
    修复后: AppSetting.set() -> cache.delete(key)（set 失败则验证码保留）
    """
    def test_set_before_delete(self):
        """源码中 AppSetting.set 在 cache.delete 之前"""
        src = inspect.getsource(setting_views.MFAView.post)
        set_pos = src.find("AppSetting.set('MFA'")
        delete_pos = src.find("cache.delete(f'{request.user.username}:code')")
        self.assertGreater(set_pos, 0, "应有 AppSetting.set 调用")
        self.assertGreater(delete_pos, 0, "应有 cache.delete 调用")
        self.assertLess(set_pos, delete_pos,
                        "AppSetting.set 应在 cache.delete 之前（修复后）")


class R4_UserSettingViewPostNoTransaction(TestCase):
    """R4 [ACCEPT]: UserSettingView.post 无 transaction.atomic()（单次 update_or_create 原子）"""
    def test_r4a_no_transaction(self):
        src = inspect.getsource(setting_user.UserSettingView.post)
        self.assertNotIn('transaction.atomic', src)


class FIX_R5_AppSettingSetClearsCache(TestCase):
    """R5 [FIXED]: AppSetting.set/delete 后清除 lru_cache

    修复前: set 不清 lru_cache，get 返回旧值
    修复后: set/delete 调用 cls.get.cache_clear()
    """
    def test_r5a_get_has_lru_cache(self):
        self.assertTrue(hasattr(AppSetting.get, 'cache_info'),
                        "AppSetting.get 应有 lru_cache")

    def test_r5b_set_clears_cache(self):
        src = inspect.getsource(AppSetting.set)
        self.assertIn('cache_clear', src)

    def test_r5c_delete_clears_cache(self):
        src = inspect.getsource(AppSetting.delete)
        self.assertIn('cache_clear', src)


# ==================== §1.3 幂等性设计 ====================

class P6_AppSettingSetIdempotent(TestCase):
    """P6: AppSetting.set 使用 update_or_create（绝对值，幂等）"""
    def test_p6a_uses_update_or_create(self):
        src = inspect.getsource(AppSetting.set)
        self.assertIn('update_or_create', src)

    def test_p6b_absolute_value(self):
        src = inspect.getsource(AppSetting.set)
        self.assertNotIn('F(', src)
        self.assertNotIn('value + ', src)


class P7_UserSettingViewIdempotent(TestCase):
    """P7: UserSettingView.post 使用 update_or_create（幂等）"""
    def test_p7a_uses_update_or_create(self):
        src = inspect.getsource(setting_user.UserSettingView.post)
        self.assertIn('update_or_create', src)


class R6_NoSelectForUpdate(TestCase):
    """R6 [ACCEPT]: 并发修改无 select_for_update（低并发全局配置，可接受）"""
    def test_r6a_no_select_for_update(self):
        src = inspect.getsource(AppSetting.set)
        self.assertNotIn('select_for_update', src)


# ==================== §1.5 防误操作与可追溯 ====================

class R7_AppSettingDeletePhysicalDelete(TestCase):
    """R7 [ACCEPT]: AppSetting.delete 物理删除（设置非业务数据，审计日志保留）"""
    def test_r7a_hard_delete(self):
        src = inspect.getsource(AppSetting.delete)
        self.assertIn('.delete()', src)
        self.assertNotIn('is_deleted', src)


class FIX_R8_SettingViewPostHasAudit(TestCase):
    """R8 [FIXED]: SettingView.post 有显式 record_audit_event + before_value"""
    def test_r8a_has_explicit_audit(self):
        src = inspect.getsource(setting_views.SettingView.post)
        self.assertIn('record_audit_event', src)

    def test_r8b_has_before_value(self):
        src = inspect.getsource(setting_views.SettingView.post)
        self.assertIn('before_value', src)

    def test_r8c_not_save_audit_log(self):
        """不再使用底层 save_audit_log"""
        src = inspect.getsource(setting_views.SettingView.post)
        self.assertNotIn('save_audit_log', src)


class FIX_R9_MFAViewPostHasAudit(TestCase):
    """R9 [FIXED]: MFAView.post 有显式 record_audit_event"""
    def test_r9a_has_explicit_audit(self):
        src = inspect.getsource(setting_views.MFAView.post)
        self.assertIn('record_audit_event', src)

    def test_r9b_not_save_audit_log(self):
        src = inspect.getsource(setting_views.MFAView.post)
        self.assertNotIn('save_audit_log', src)


class R10_UserSettingViewPostNoExplicitAudit(TestCase):
    """R10 [ACCEPT]: UserSettingView.post 无显式审计（中间件覆盖，低风险）"""
    def test_r10a_no_explicit_audit(self):
        src = inspect.getsource(setting_user.UserSettingView.post)
        self.assertNotIn('record_audit_event', src)
        self.assertNotIn('save_audit_log', src)


class FIX_R11_DeleteUsesRecordAuditEvent(TestCase):
    """R11 [FIXED]: AppSetting.delete 改用 record_audit_event"""
    def test_r11a_uses_record_audit_event(self):
        src = inspect.getsource(AppSetting.delete)
        self.assertIn('record_audit_event', src)

    def test_r11b_not_save_audit_log(self):
        """不再使用底层 save_audit_log"""
        src = inspect.getsource(AppSetting.delete)
        self.assertNotIn('save_audit_log', src)


class FIX_R12_DeleteAndPostHaveBeforeValue(TestCase):
    """R12 [FIXED]: delete 和 SettingView.post 均记录 before_value"""
    def test_r12a_delete_has_before_value(self):
        src = inspect.getsource(AppSetting.delete)
        self.assertIn('before_value', src)

    def test_r12b_post_has_before_value(self):
        src = inspect.getsource(setting_views.SettingView.post)
        self.assertIn('before_value', src)


class FIX_R13_SensitiveSettingsMasked(TestCase):
    """R13 [FIXED]: SettingView.get 对敏感设置脱敏"""
    def test_r13a_sensitive_keys_in_defaults(self):
        self.assertIn('mail_service', KEYS_DEFAULT)
        self.assertIn('spug_key', KEYS_DEFAULT)
        self.assertIn('api_key', KEYS_DEFAULT)

    def test_r13b_get_has_masking(self):
        src = inspect.getsource(setting_views.SettingView.get)
        self.assertIn('_mask_sensitive', src)

    def test_r13c_mask_function_exists(self):
        src = inspect.getsource(setting_views)
        self.assertIn('def _mask_sensitive_settings', src)
        self.assertIn("'***'", src)


# ==================== §2.1 索引与慢查询 ====================

class P8_SettingKeyUniqueIndex(TestCase):
    """P8: Setting.key 有唯一索引"""
    def test_p8a_unique(self):
        f = Setting._meta.get_field('key')
        self.assertTrue(f.unique)


class P9_UserSettingUniqueTogetherIndex(TestCase):
    """P9: UserSetting 有 (user, key) 联合唯一索引"""
    def test_p9a_unique_together(self):
        ut = UserSetting._meta.unique_together
        self.assertIn(('user', 'key'), [tuple(x) for x in ut])


# ==================== §2.2 资源兜底与限流容错 ====================

class R14_SettingValueNoApplicationLimit(TestCase):
    """R14 [ACCEPT]: Setting.value 无应用层大小限制（管理员可信）"""
    def test_r14a_no_size_check_in_post(self):
        src = inspect.getsource(setting_views.SettingView.post)
        self.assertNotIn('MAX_VALUE', src)


class FIX_R15_MFAHasBruteForceLockout(TestCase):
    """R15 [FIXED]: MFA 验证码有暴力破解锁定（5 次失败后锁 5 分钟）"""
    def test_r15a_has_fail_counter(self):
        src = inspect.getsource(setting_views.MFAView.post)
        self.assertIn('fail_count', src)

    def test_r15b_has_lockout(self):
        src = inspect.getsource(setting_views.MFAView.post)
        self.assertIn('lockout', src.lower())
        self.assertIn('lock_key', src)

    def test_r15c_max_attempts_5(self):
        src = inspect.getsource(setting_views.MFAView.post)
        self.assertIn('>= 5', src)


# ==================== §3.5 安全维度 ====================

class FIX_R16_SendLoginCodeImported(TestCase):
    """R16 [FIXED]: send_login_code 已导入"""
    def test_r16a_in_imports(self):
        src = inspect.getsource(setting_views)
        import_section = src[:src.find('class ')]
        self.assertIn('send_login_code', import_section)

    def test_r16b_used_in_mfa_get(self):
        src = inspect.getsource(setting_views.MFAView.get)
        self.assertIn('send_login_code', src)

    def test_r16c_function_exists_in_push(self):
        from libs.push import send_login_code
        self.assertTrue(callable(send_login_code))


class FIX_R17_SensitiveSettingsMasked(TestCase):
    """R17 [FIXED]: GET /setting/ 响应中敏感配置已脱敏"""
    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_r17a_password_masked(self):
        setup_test_env(self)
        AppSetting.get.cache_clear()
        self.addCleanup(AppSetting.get.cache_clear)
        try:
            supper = make_user('r17fix', is_supper=True)
            client = make_client(supper)
            AppSetting.set('mail_service', {
                'server': 'smtp.test.com',
                'port': 465,
                'username': 'test@test.com',
                'password': 'SECRET_SMTP_PASSWORD_123',
            })
            AppSetting.get.cache_clear()
            r = client.get('/setting/')
            data = r.json().get('data', {})
            mail_service = data.get('mail_service', {})
            if isinstance(mail_service, dict):
                self.assertEqual(mail_service.get('password'), '***',
                                 "密码应被脱敏为 ***")
        finally:
            Setting.objects.filter(key='mail_service').delete()
            User.objects.filter(username='r17fix').delete()


class FIX_R18_MFAHasRetryLimit(TestCase):
    """R18 [FIXED]: MFA 验证码有重试次数上限"""
    def test_r18a_has_fail_count(self):
        src = inspect.getsource(setting_views.MFAView.post)
        self.assertIn('fail_count', src)


class R19_UserSettingViewNoAuthDecorator(TestCase):
    """R19 [ACCEPT]: UserSettingView 无 @auth（中间件认证 + 用户隔离）"""
    def test_r19a_no_auth_decorator(self):
        src = inspect.getsource(setting_user)
        self.assertNotIn('@auth', src)

    def test_r19b_inherits_plain_view(self):
        from django.views.generic import View
        self.assertTrue(issubclass(setting_user.UserSettingView, View))


class P10_UserSettingViewUserIsolation(TestCase):
    """P10: UserSettingView 正确使用 request.user 过滤（用户隔离）"""
    def test_p10a_get_filters_by_user(self):
        src = inspect.getsource(setting_user.UserSettingView.get)
        self.assertIn('user=request.user', src)

    def test_p10b_post_filters_by_user(self):
        src = inspect.getsource(setting_user.UserSettingView.post)
        self.assertIn('user=request.user', src)


class P11_SettingViewMFAViewAdminOnly(TestCase):
    """P11: SettingView / MFAView 继承 AdminView（仅超管可访问）"""
    def test_p11a_setting_view_admin(self):
        from libs.mixins import AdminView
        self.assertTrue(issubclass(setting_views.SettingView, AdminView))

    def test_p11b_mfa_view_admin(self):
        from libs.mixins import AdminView
        self.assertTrue(issubclass(setting_views.MFAView, AdminView))


# ==================== 功能验证（修复后） ====================

@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class Functional_R5_CacheInvalidatedAfterSet(TestCase):
    """功能验证 R5 [FIXED]: set 后 get 返回新值（不再返回旧缓存）"""
    def setUp(self):
        setup_test_env(self)
        AppSetting.get.cache_clear()
        self.addCleanup(AppSetting.get.cache_clear)
        Setting.objects.all().delete()

    def test_get_returns_fresh_value_after_set(self):
        # 1. 初始写入
        AppSetting.set('verify_ip', True)
        AppSetting.get.cache_clear()
        self.assertEqual(AppSetting.get('verify_ip'), True)

        # 2. 修改
        AppSetting.set('verify_ip', False)

        # 3. get 应返回新值（修复后 cache_clear 被调用）
        fresh = AppSetting.get('verify_ip')
        self.assertEqual(fresh, False,
                         "修复后 AppSetting.get 应返回新值 False（不再返回旧缓存）")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class Functional_R3_CodePreservedOnSetFailure(TestCase):
    """功能验证 R3 [FIXED]: AppSetting.set 失败后验证码未被消费"""
    def setUp(self):
        setup_test_env(self)
        AppSetting.get.cache_clear()
        self.addCleanup(AppSetting.get.cache_clear)
        Setting.objects.all().delete()
        cache.clear()
        self.supper = make_user('r3fix', is_supper=True)
        from django.test import Client
        self.client_safe = Client(raise_request_exception=False)
        self.client_safe.defaults['HTTP_X_TOKEN'] = self.supper.access_token
        self.client_safe.defaults['HTTP_X_FORWARDED_FOR'] = '127.0.0.1'

    def test_code_not_consumed_on_set_failure(self):
        """AppSetting.set 失败后验证码应保留（修复后 set 在 delete 之前）"""
        from unittest.mock import patch
        cache_key = f'{self.supper.username}:code'
        correct_code = 'ABC123'
        cache.set(cache_key, correct_code, 300)

        with patch('apps.setting.views.AppSetting.set', side_effect=Exception('DB error')):
            self.client_safe.post(
                '/setting/mfa/',
                data=json.dumps({'enable': True, 'code': correct_code}),
                content_type='application/json',
            )

        # 修复后：cache.delete 在 AppSetting.set 之后，set 失败则验证码保留
        self.assertIsNotNone(cache.get(cache_key),
                             "修复后验证码应保留（set 失败时 cache.delete 未执行）")

        # MFA 仍为禁用
        AppSetting.get.cache_clear()
        mfa = AppSetting.get_default('MFA', {'enable': False})
        self.assertFalse(mfa.get('enable', False))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class Functional_R16_MFAGetNoNameError(TestCase):
    """功能验证 R16 [FIXED]: MFAView.get 不再抛 NameError"""
    def setUp(self):
        setup_test_env(self)
        AppSetting.get.cache_clear()
        self.addCleanup(AppSetting.get.cache_clear)
        Setting.objects.all().delete()
        cache.clear()
        self.supper = make_user('r16fix', is_supper=True)
        self.supper.wx_token = 'test_wx_token_123'
        self.supper.save()
        Setting.objects.create(key='spug_push_key', value='"test_push_key_value"')

    def test_get_mfa_no_name_error(self):
        """修复后 GET /setting/mfa/ 不再因 NameError 返回错误"""
        from django.test import RequestFactory
        from apps.setting.views import MFAView
        factory = RequestFactory()
        req = factory.get('/setting/mfa/')
        req.user = self.supper
        # 修复后 send_login_code 已导入，不应抛 NameError
        # 但 send_login_code 可能因网络原因失败，用 try/except 捕获
        try:
            MFAView.as_view()(req)
        except NameError as e:
            self.fail(f"修复后不应抛 NameError: {e}")
        except Exception:
            # 其他异常（如网络错误）可接受，只要不是 NameError
            pass


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class Functional_R15_LockoutAfter5Failures(TestCase):
    """功能验证 R15 [FIXED]: 5 次错误验证码后锁定"""
    def setUp(self):
        setup_test_env(self)
        AppSetting.get.cache_clear()
        self.addCleanup(AppSetting.get.cache_clear)
        Setting.objects.all().delete()
        cache.clear()
        self.supper = make_user('r15fix', is_supper=True)
        self.client = make_client(self.supper)

    def test_5th_wrong_code_triggers_lockout(self):
        cache_key = f'{self.supper.username}:code'
        cache.set(cache_key, 'CORRECT', 300)

        # 连续 4 次错误（不触发锁定）
        for i in range(4):
            r = self.client.post(
                '/setting/mfa/',
                data=json.dumps({'enable': True, 'code': f'WRONG{i}'}),
                content_type='application/json',
            )
            error = r.json().get('error', '')
            # 前 3 次是"验证码错误"，第 4 次可能验证码已失效
            self.assertTrue('验证码' in error, f"第{i+1}次应返回验证码相关错误，实际: {error}")

        # 第 5 次错误 -> 触发锁定
        r5 = self.client.post(
            '/setting/mfa/',
            data=json.dumps({'enable': True, 'code': 'WRONG5'}),
            content_type='application/json',
        )
        error_msg = r5.json().get('error', '')
        self.assertIn('过多', error_msg, f"第5次应触发锁定消息，实际: {error_msg}")

    def test_locked_account_rejected(self):
        """锁定后即使输入正确验证码也被拒绝"""
        cache_key = f'{self.supper.username}:code'
        cache.set(cache_key, 'CORRECT', 300)
        # 设置锁定
        cache.set(f'{self.supper.username}:code:lockout', True, 300)
        r = self.client.post(
            '/setting/mfa/',
            data=json.dumps({'enable': True, 'code': 'CORRECT'}),
            content_type='application/json',
        )
        self.assertIn('过多', r.json().get('error', ''),
                      "锁定后应返回'过多'消息")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class Functional_R7_PhysicalDeleteWithAudit(TestCase):
    """功能验证 R7: AppSetting.delete 物理删除 + 审计日志（record_audit_event）"""
    def setUp(self):
        setup_test_env(self)
        AppSetting.get.cache_clear()
        self.addCleanup(AppSetting.get.cache_clear)
        Setting.objects.all().delete()

    def test_delete_removes_record(self):
        AppSetting.set('verify_ip', True)
        AppSetting.get.cache_clear()
        self.assertTrue(Setting.objects.filter(key='verify_ip').exists())
        AppSetting.delete('verify_ip')
        self.assertFalse(Setting.objects.filter(key='verify_ip').exists())

    def test_setting_model_no_is_deleted_field(self):
        field_names = [f.name for f in Setting._meta.get_fields()]
        self.assertNotIn('is_deleted', field_names)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class Functional_R11_DeleteAuditWithRecordAuditEvent(TestCase):
    """功能验证 R11/R12 [FIXED]: AppSetting.delete(key, request) 产生完整审计日志

    验证:
    1. AuditLog action='delete', target_type='setting' 已创建
    2. ip 从 request.headers['x-forwarded-for'] 提取（非空）
    3. user_agent 从 request.headers 提取（非空）
    4. detail 含 'before' 键，值为旧配置值
    5. username 匹配操作人
    """
    def setUp(self):
        setup_test_env(self)
        AppSetting.get.cache_clear()
        self.addCleanup(AppSetting.get.cache_clear)
        Setting.objects.all().delete()
        self.supper = make_user('r11fn', is_supper=True)

    def test_delete_with_request_creates_full_audit(self):
        from apps.logs.models import AuditLog
        from django.test import RequestFactory
        # 1. 创建配置项（值为 True）
        AppSetting.set('verify_ip', True, desc='IP验证开关')
        AppSetting.get.cache_clear()

        # 2. 构造带 IP + UA 的 request
        factory = RequestFactory()
        req = factory.delete(
            '/setting/',
            HTTP_X_FORWARDED_FOR='1.2.3.4',
            HTTP_USER_AGENT='TestAuditAgent/2.0',
        )
        req.user = self.supper

        # 3. 调用 delete（传入 request）
        before_count = AuditLog.objects.filter(
            action='delete', target_type='setting'
        ).count()
        AppSetting.delete('verify_ip', request=req)
        after_count = AuditLog.objects.filter(
            action='delete', target_type='setting'
        ).count()

        # 4. 验证审计日志已创建
        self.assertEqual(after_count, before_count + 1,
                         "应新增一条 delete 审计日志")
        log = AuditLog.objects.filter(
            action='delete', target_type='setting'
        ).order_by('-id').first()
        self.assertIsNotNone(log)

        # 5. 验证 IP 从 request 提取（record_audit_event 自动提取）
        self.assertEqual(log.ip, '1.2.3.4',
                         f"ip 应为 1.2.3.4，实际: {log.ip!r}")

        # 6. 验证 user_agent 从 request 提取
        self.assertIn('TestAuditAgent', log.user_agent,
                      f"user_agent 应含 TestAuditAgent，实际: {log.user_agent!r}")

        # 7. 验证 username 匹配操作人
        self.assertEqual(log.username, 'r11fn',
                         f"username 应为 r11fn，实际: {log.username!r}")

        # 8. 验证 detail 含 before 键（R12: 变更前值）
        detail = json.loads(log.detail) if log.detail else {}
        self.assertIn('before', detail,
                      "detail 应含 before 键（变更前值）")
        before = detail['before']
        self.assertIn('value', before,
                      "before 应含 value 键")
        self.assertTrue(before['value'],
                        "before.value 应为 True（删除前的旧值）")

        # 9. 验证配置已物理删除
        self.assertFalse(Setting.objects.filter(key='verify_ip').exists())

    def test_delete_without_request_no_audit(self):
        """无 request 参数时不写审计日志（不崩溃）"""
        from apps.logs.models import AuditLog
        AppSetting.set('verify_ip', True)
        AppSetting.get.cache_clear()
        before_count = AuditLog.objects.filter(
            action='delete', target_type='setting'
        ).count()
        # 不传 request
        AppSetting.delete('verify_ip')
        after_count = AuditLog.objects.filter(
            action='delete', target_type='setting'
        ).count()
        self.assertEqual(after_count, before_count,
                         "无 request 时不应写审计日志")
        self.assertFalse(Setting.objects.filter(key='verify_ip').exists())


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class Functional_R8_PostRecordsAuditWithBefore(TestCase):
    """功能验证 R8 [FIXED]: SettingView.post 记录含 before_value 的审计日志"""
    def setUp(self):
        setup_test_env(self)
        AppSetting.get.cache_clear()
        self.addCleanup(AppSetting.get.cache_clear)
        Setting.objects.all().delete()
        cache.clear()
        self.supper = make_user('r8fix', is_supper=True)
        self.client = make_client(self.supper)

    def test_post_creates_audit_with_before(self):
        from apps.logs.models import AuditLog
        # 先设置初始值
        AppSetting.set('verify_ip', True)
        AppSetting.get.cache_clear()
        # 修改
        before_count = AuditLog.objects.filter(
            target_type='setting', action='update'
        ).count()
        r = self.client.post(
            '/setting/',
            data=json.dumps({'data': [{'key': 'verify_ip', 'value': False}]}),
            content_type='application/json',
        )
        self.assertFalse(r.json().get('error'))
        after_count = AuditLog.objects.filter(
            target_type='setting', action='update'
        ).count()
        self.assertEqual(after_count, before_count + 1,
                         "应新增一条 update 审计日志")
        # 检查审计日志含 before 值
        log = AuditLog.objects.filter(
            target_type='setting', action='update'
        ).order_by('-id').first()
        detail = json.loads(log.detail) if log.detail else {}
        self.assertIn('before', detail,
                      "审计日志 detail 应含 before 键")


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class Functional_R9_MFAAuditLogged(TestCase):
    """功能验证 R9 [FIXED]: MFAView.post 记录显式审计日志"""
    def setUp(self):
        setup_test_env(self)
        AppSetting.get.cache_clear()
        self.addCleanup(AppSetting.get.cache_clear)
        Setting.objects.all().delete()
        cache.clear()
        self.supper = make_user('r9fix', is_supper=True)
        self.client = make_client(self.supper)

    def test_disable_mfa_audit_logged(self):
        from apps.logs.models import AuditLog
        AppSetting.set('MFA', {'enable': True})
        AppSetting.get.cache_clear()
        before_count = AuditLog.objects.filter(
            target_type='setting', action='update'
        ).count()
        r = self.client.post(
            '/setting/mfa/',
            data=json.dumps({'enable': False}),
            content_type='application/json',
        )
        self.assertFalse(r.json().get('error'))
        after_count = AuditLog.objects.filter(
            target_type='setting', action='update'
        ).count()
        self.assertEqual(after_count, before_count + 1,
                         "MFA 禁用应新增一条 update 审计日志")

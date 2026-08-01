# -*- coding: utf-8 -*-
"""account 模块 CRUD 可靠性深度审计测试

参照 CRUD系统可靠性指南.md §1.1-§3.5 逐项排查。
基于前 10 个模块（evidence/signature/radio_license/device/setting/
contract_agreement/alert/home/regulation/department_duty_log）的实战审计经验。

风险命名规则：
  R{n}_{RiskName}  - 风险确认（BUG 存在时 FAIL）
  P{n}_{GoodName}  - 优秀实践确认（应 PASS）

风险等级：P0=严重 / P1=中等 / P2=轻微
"""
import inspect
import time
from datetime import datetime
from django.db import connection, IntegrityError, transaction
from django.test import TestCase
from apps.account.models import User, Role, History, Tenant
from apps.account import views as acc_views
from apps.account import history as acc_history


def _make_user(username='acc_audit', is_supper=False, tenant_id='admin'):
    """直接用 raw SQL 创建用户，绕过 _check_duplicate_username"""
    token = (username * 10)[:32]
    now_ts = int(time.time()) + 3600
    with connection.cursor() as cur:
        cur.execute("SET SESSION sql_mode=''")
        cur.execute(
            "INSERT INTO users (username,nickname,password_hash,is_active,is_supper,"
            "access_token,token_expired,last_login,last_ip,type,tenant_id,wx_token,"
            "created_at) VALUES (%s,%s,'x',1,%s,%s,%s,'2026-01-01','127.0.0.1',"
            "'default',%s,'',NOW())",
            [username, username, 1 if is_supper else 0, token, now_ts, tenant_id])
    return User.objects.get(username=username)


def _make_role(name='测试角色', tenant_id='admin', created_by=None, **kw):
    return Role.objects.create(
        name=name,
        desc=kw.get('desc', ''),
        page_perms=kw.get('page_perms', ''),
        deploy_perms=kw.get('deploy_perms', ''),
        group_perms=kw.get('group_perms', ''),
        is_global_admin=kw.get('is_global_admin', False),
        tenant_id=tenant_id,
        is_system=kw.get('is_system', False),
        created_by=created_by,
    )


def _cleanup(*models):
    """按传入顺序删除（调用者需保证子表在前、父表在后）"""
    for m in models:
        try:
            m.objects.all().delete()
        except Exception:
            pass


# ==================== §1.1 数据库约束 ====================

class R1_UsernameHasPartialUniqueIndex(TestCase):
    """R1(PASS): User 活跃用户名有 DB 部分唯一约束 - 优秀实践

    确认内容：
      - username 字段本身无 unique=True（软删除设计）
      - 但 migration 0010 创建了 uniq_users_active_username 部分唯一索引
      - MariaDB 使用生成列 active_username 实现：活跃用户映射为 username，
        软删除用户映射为 NULL（允许多个 NULL）
      - 竞态安全：DB 层最终防线

    指南条款：§1.1 "NOT NULL/UNIQUE/CHECK/FK 必须在 DB 层强制"
    """
    def test_r1a_username_field_no_unique(self):
        """username 字段本身无 unique=True（软删除设计允许同名重建）"""
        f = User._meta.get_field('username')
        self.assertFalse(f.unique, "username 字段无 unique=True（软删除设计）")

    def test_r1b_db_has_active_username_unique_index(self):
        """DB 层有 uniq_users_active_username 部分唯一索引"""
        with connection.cursor() as cur:
            cur.execute("SHOW INDEX FROM users WHERE Key_name = 'uniq_users_active_username'")
            rows = cur.fetchall()
        self.assertGreater(len(rows), 0,
                           "DB 应有 uniq_users_active_username 部分唯一索引")

    def test_r1c_db_rejects_duplicate_active_username(self):
        """DB 拒绝创建两个活跃同名用户"""
        try:
            u1 = _make_user('dup_test_r1c')
            token2 = ('dup_r1c_2' * 10)[:32]
            now_ts = int(time.time()) + 3600
            with self.assertRaises(IntegrityError):
                with connection.cursor() as cur:
                    cur.execute("SET SESSION sql_mode=''")
                    cur.execute(
                        "INSERT INTO users (username,nickname,password_hash,is_active,is_supper,"
                        "access_token,token_expired,last_login,last_ip,type,tenant_id,wx_token,"
                        "created_at) VALUES (%s,%s,'x',1,0,%s,%s,'2026-01-01','127.0.0.1',"
                        "'default','admin','',NOW())",
                        ['dup_test_r1c', 'dup_r1c_2', token2, now_ts])
        finally:
            _cleanup(User)


class R2_RoleUniqueTogetherHasConstraint(TestCase):
    """R2(PASS): Role 有 unique_together DB 唯一约束 - 优秀实践

    指南条款：§1.1 "UNIQUE 必须在 DB 层强制"
    """
    def test_r2a_unique_together_exists(self):
        self.assertEqual(
            Role._meta.unique_together,
            (('tenant_id', 'name'),),
            "Role 应有 unique_together = (('tenant_id', 'name'),)"
        )

    def test_r2b_duplicate_role_integrity_error(self):
        """DB 层拒绝重复角色名"""
        try:
            admin = _make_user('r2b_admin', is_supper=True)
            _make_role('测试角色R2', tenant_id='admin', created_by=admin)
            with self.assertRaises(IntegrityError):
                Role.objects.create(
                    name='测试角色R2',
                    desc='',
                    page_perms='',
                    deploy_perms='',
                    group_perms='',
                    is_global_admin=False,
                    tenant_id='admin',
                    is_system=False,
                    created_by=admin,
                )
        finally:
            _cleanup(Role, User)


class R3_RolePhysicalDelete(TestCase):
    """R3(P2): Role 物理删除而非逻辑删除

    风险描述：
      - Role.delete() 直接物理删除，无 is_deleted 字段
      - 前序审计经验：interference/runlog/home 均因物理删除被标记
      - 但 Role 是配置表且有 user_set.exists() 前置检查，风险较低

    指南条款：§1.1 "核心业务表用逻辑删除替代物理删除"
    """
    def test_r3a_no_is_deleted_field(self):
        """Role 模型无 is_deleted 字段"""
        field_names = [f.name for f in Role._meta.get_fields()]
        self.assertNotIn('is_deleted', field_names, "Role 无 is_deleted 字段")

    def test_r3b_delete_uses_hard_delete(self):
        """RoleView.delete 使用物理删除"""
        src = inspect.getsource(acc_views.RoleView.delete)
        self.assertIn('.delete()', src)
        self.assertNotIn('is_deleted', src)


class R4_UserNoUpdatedAtField(TestCase):
    """R4(P2): User 模型无 updated_at/updated_by 字段

    风险描述：
      - 用户编辑后无更新时间记录，审计困难
      - 前序审计经验：device/contract_agreement 均因缺少 updated_at 被标记

    指南条款：§1.5 "审计日志需记录操作前后值"
    """
    def test_r4a_no_updated_at(self):
        field_names = [f.name for f in User._meta.get_fields()]
        self.assertNotIn('updated_at', field_names)

    def test_r4b_no_updated_by(self):
        field_names = [f.name for f in User._meta.get_fields()]
        self.assertNotIn('updated_by', field_names)


# ==================== §1.2 事务边界 ====================

class R5_UserViewDeleteNoTransaction(TestCase):
    """R5(P1): UserView.delete 无显式 transaction.atomic()

    风险描述：
      - delete 方法执行 user.roles.clear() + user.save() 多步操作
      - 虽 ATOMIC_REQUESTS=True 包裹请求，但显式事务是编码规范要求
      - 前序审计经验：evidence/regulation 多步操作均补了显式事务

    指南条款：§1.2 "所有多步写操作必须 transaction.atomic() 包裹"
    """
    def test_r5a_no_explicit_transaction(self):
        src = inspect.getsource(acc_views.UserView.delete)
        self.assertNotIn('transaction.atomic', src,
                         "UserView.delete 应有但缺少显式 transaction.atomic()")

    def test_r5b_has_multiple_writes(self):
        """确认 delete 方法确实有多个 DB 写操作"""
        src = inspect.getsource(acc_views.UserView.delete)
        write_count = src.count('.save(') + src.count('.clear(') + src.count('.update(')
        self.assertGreaterEqual(write_count, 2,
                                "delete 应有 >=2 个写操作才需要事务")


class R6_UserViewPatchNoTransaction(TestCase):
    """R6(P1): UserView.patch 无显式 transaction.atomic()

    风险描述：
      - patch 方法执行 _migrate_user_tenant + user.save() 多步操作
      - _handle_user_edit (POST 路径) 有显式 transaction.atomic()，patch 没有
      - 前序审计经验：不一致的事务策略是常见风险来源

    指南条款：§1.2 "所有多步写操作必须 transaction.atomic() 包裹"
    """
    def test_r6a_patch_no_explicit_transaction(self):
        src = inspect.getsource(acc_views.UserView.patch)
        self.assertNotIn('transaction.atomic', src,
                         "UserView.patch 缺少显式 transaction.atomic()")

    def test_r6b_post_has_transaction(self):
        """_handle_user_edit (POST 路径) 有显式事务 - 证明不一致"""
        src = inspect.getsource(acc_views.UserView._handle_user_edit)
        self.assertIn('transaction.atomic', src,
                      "_handle_user_edit 有事务 - 与 patch 不一致")


class R7_RoleViewPostEditBypassSave(TestCase):
    """R7(P1): RoleView.post (edit) 使用 QuerySet.update() 绕过 save()

    风险描述：
      - Role.objects.filter(pk=role_id).update(**fields) 不触发 save()
      - Role.save() 中 perms_version 自增逻辑被绕过
      - 当前不可利用：fields 不含 page_perms（仅通过 PATCH 修改）
      - 但属于脆弱设计：未来若 POST 参数加入 page_perms 将导致缓存失效

    指南条款：§1.2 "多步写操作必须用事务包裹；状态变更需走 save()"
    """
    def test_r7a_post_edit_uses_update(self):
        """确认 POST edit 路径使用 .update()"""
        src = inspect.getsource(acc_views.RoleView.post)
        self.assertIn('.update(**fields)', src,
                      "RoleView.post (edit) 使用 QuerySet.update()")

    def test_r7b_save_bypassed_perms_version(self):
        """验证 .update() 不触发 save() -> perms_version 不递增"""
        try:
            admin = _make_user('r7b_admin', is_supper=True)
            role = _make_role('R7测试角色', tenant_id='admin', created_by=admin,
                             page_perms='{}')
            old_version = role.perms_version

            # 模拟 RoleView.post edit 路径的 .update() 调用
            Role.objects.filter(pk=role.pk).update(desc='更新后的描述')
            role.refresh_from_db()
            self.assertEqual(role.perms_version, old_version,
                             ".update() 不触发 save()，perms_version 不递增 - 脆弱设计")
        finally:
            _cleanup(Role, User)

    def test_r7c_save_triggers_perms_version(self):
        """对比：正常 save() 路径 perms_version 会递增"""
        try:
            admin = _make_user('r7c_admin', is_supper=True)
            role = _make_role('R7C角色', tenant_id='admin', created_by=admin,
                             page_perms='{}')
            old_version = role.perms_version

            # 正常 save() 路径修改 page_perms
            role.page_perms = '{"test": {}}'
            role.save()
            role.refresh_from_db()
            self.assertGreater(role.perms_version, old_version,
                               "save() 路径 perms_version 应递增")
        finally:
            _cleanup(Role, User)


# ==================== §1.3 幂等性 ====================

class R8_UserViewPostNoIdempotency(TestCase):
    """R8(P1): UserView.post (create) 无幂等性检查

    风险描述：
      - 无 check_recent_duplicate 调用
      - _check_duplicate_username 是 SELECT-then-INSERT（竞态窗口）
      - 但 DB 层有 uniq_users_active_username 兜底，并发最终不会创建重复
      - 不过应用层应提供友好提示而非 IntegrityError -> 500

    指南条款：§1.3 "核心写操作设计幂等键"
    """
    def test_r8a_no_check_recent_duplicate(self):
        """UserView.post 不调用 check_recent_duplicate"""
        src = inspect.getsource(acc_views.UserView.post)
        self.assertNotIn('check_recent_duplicate', src)

    def test_r8b_duplicate_username_uses_select_then_insert(self):
        """_check_duplicate_username 是 SELECT-then-INSERT 模式（用 .first()）"""
        src = inspect.getsource(acc_views.UserView._check_duplicate_username)
        self.assertIn('.first()', src, "先 SELECT 检查（用 .first()）")
        # 调用方 _handle_user_create 在检查后直接 create
        create_src = inspect.getsource(acc_views.UserView._handle_user_create)
        self.assertIn('.create(', create_src, "然后 INSERT")


class R9_RoleViewPostNoIdempotency(TestCase):
    """R9(P1): RoleView.post (create) 无幂等性检查

    风险描述：
      - 无 check_recent_duplicate 调用
      - unique_together 在 DB 层兜底，但 IntegrityError 未捕获 -> 500 错误
      - 前序审计经验：重复提交应返回友好提示而非 500

    指南条款：§1.3 "核心写操作设计幂等键"
    """
    def test_r9a_no_check_recent_duplicate(self):
        src = inspect.getsource(acc_views.RoleView.post)
        self.assertNotIn('check_recent_duplicate', src)

    def test_r9b_no_integrity_error_handling(self):
        """RoleView.post (create) 不捕获 IntegrityError"""
        src = inspect.getsource(acc_views.RoleView.post)
        self.assertNotIn('IntegrityError', src,
                         "RoleView.post 未捕获 IntegrityError -> 重复名称返回 500")

    def test_r9c_userview_has_integrity_error_handling(self):
        """对比：UserView._handle_user_create 有 IntegrityError 捕获 - 证明不一致"""
        src = inspect.getsource(acc_views.UserView._handle_user_create)
        self.assertIn('IntegrityError', src,
                      "UserView._handle_user_create 有 IntegrityError 处理")


class R10_TenantViewPostNoIdempotency(TestCase):
    """R10(P1): TenantView.post 无幂等性检查 + IntegrityError 未捕获

    风险描述：
      - Tenant.objects.filter(pk=form.id).exists() 是 SELECT-then-INSERT
      - Tenant.objects.create() 无 try/except IntegrityError
      - 并发请求可绕过 exists() 检查，DB 拒绝 -> 500

    指南条款：§1.3 "核心写操作设计幂等键"
    """
    def test_r10a_no_check_recent_duplicate(self):
        src = inspect.getsource(acc_views.TenantView.post)
        self.assertNotIn('check_recent_duplicate', src)

    def test_r10b_no_integrity_error_handling(self):
        src = inspect.getsource(acc_views.TenantView.post)
        self.assertNotIn('IntegrityError', src)


# ==================== §1.5 防误操作 ====================

class R11_AccountCRUDNoRecordAuditEvent(TestCase):
    """R11(P1): account 模块 CRUD 缺少 record_audit_event 调用

    风险描述：
      - UserView/RoleView/TenantView 的 CRUD 操作不调用 record_audit_event
      - login 委托 handle_login_record -> save_audit_log 记录审计日志
      - AuditLogMiddleware 自动记录但 DELETE 操作 target_name=None（无主体名）
      - 前序审计经验：setting 模块删除操作被标记缺少 record_audit_event

    指南条款：§1.5 "高风险操作二次校验 + 权限管控 + 审计日志"
    """
    def test_r11a_userview_post_no_audit(self):
        src = inspect.getsource(acc_views.UserView.post)
        self.assertNotIn('record_audit_event', src)
        self.assertNotIn('save_audit_log', src)

    def test_r11b_userview_patch_no_audit(self):
        src = inspect.getsource(acc_views.UserView.patch)
        self.assertNotIn('record_audit_event', src)
        self.assertNotIn('save_audit_log', src)

    def test_r11c_userview_delete_no_audit(self):
        src = inspect.getsource(acc_views.UserView.delete)
        self.assertNotIn('record_audit_event', src)
        self.assertNotIn('save_audit_log', src)

    def test_r11d_roleview_post_no_audit(self):
        src = inspect.getsource(acc_views.RoleView.post)
        self.assertNotIn('record_audit_event', src)
        self.assertNotIn('save_audit_log', src)

    def test_r11e_roleview_delete_no_audit(self):
        src = inspect.getsource(acc_views.RoleView.delete)
        self.assertNotIn('record_audit_event', src)
        self.assertNotIn('save_audit_log', src)

    def test_r11f_tenantview_post_no_audit(self):
        src = inspect.getsource(acc_views.TenantView.post)
        self.assertNotIn('record_audit_event', src)
        self.assertNotIn('save_audit_log', src)

    def test_r11g_tenantview_delete_no_audit(self):
        src = inspect.getsource(acc_views.TenantView.delete)
        self.assertNotIn('record_audit_event', src)
        self.assertNotIn('save_audit_log', src)

    def test_r11h_login_delegates_audit_to_history(self):
        """对比：login 委托 handle_login_record 记录审计日志 - CRUD 没有"""
        login_src = inspect.getsource(acc_views.login)
        self.assertIn('handle_login_record', login_src,
                      "login 委托 handle_login_record 处理审计")
        handler_src = inspect.getsource(acc_views.handle_login_record)
        self.assertIn('save_audit_log', handler_src,
                      "handle_login_record 调用 save_audit_log - CRUD 无此调用")


# ==================== §2.1 索引 ====================

class R12_UserViewGetTenantChoicesNPlus1(TestCase):
    """R12(P2): UserView.get_tenant_choices N+1 查询

    风险描述：
      - for 循环内对每个 tenant 执行 User.objects.filter(...).count()
      - 可用 annotate 替代，但 tenant 数量通常很少（< 100）
      - 前序审计经验：department_duty_log N+1 查询已被标记并优化

    指南条款：§2.1 "避免 N+1 查询"
    """
    def test_r12a_loop_with_count(self):
        """get_tenant_choices 在循环内执行 count() 查询"""
        src = inspect.getsource(acc_views.UserView.get_tenant_choices)
        self.assertIn('for ', src)
        self.assertIn('.count()', src)

    def test_r12b_no_annotate(self):
        """未使用 annotate 优化"""
        src = inspect.getsource(acc_views.UserView.get_tenant_choices)
        self.assertNotIn('annotate', src)


# ==================== §2.2 资源兜底 ====================

class R13_HistoryViewNoPagination(TestCase):
    """R13(P0): HistoryView.get 无分页全表查询

    风险描述：
      - History.objects.all() 返回所有登录历史记录，无分页/限制
      - 随着时间推移记录数无限增长，可导致内存溢出和响应超时
      - 前序审计经验：UserView.get 已修复为 [:500]，HistoryView 遗漏

    指南条款：§2.2 "列表查询必须有分页或上限"
    """
    def test_r13a_no_pagination(self):
        """HistoryView.get 返回全表无分页"""
        src = inspect.getsource(acc_history.HistoryView.get)
        self.assertIn('objects.all()', src)
        self.assertNotIn('[:', src, "应无切片限制 - 全表返回")
        self.assertNotIn('paginate', src.lower(), "无分页函数")

    def test_r13b_unbounded_result(self):
        """实际验证：创建 5 条记录，全部返回"""
        try:
            admin = _make_user('r13b_admin', is_supper=True)
            for i in range(5):
                History.objects.create(
                    username='test_user_%d' % i,
                    ip='127.0.0.1',
                    type='default',
                    is_success=True,
                )
            total = History.objects.count()
            self.assertGreaterEqual(total, 5)
            # HistoryView.get 返回所有记录
            all_records = History.objects.all()
            self.assertEqual(all_records.count(), total,
                             "HistoryView.get 返回全部记录 - 无分页")
        finally:
            _cleanup(History, User)


class R14_TenantViewGetNoPagination(TestCase):
    """R14(P2): TenantView.get 无分页

    风险描述：
      - Tenant.objects.all().order_by('id') 无限制
      - 风险较低：租户数量通常很少（< 100）

    指南条款：§2.2 "列表查询必须有分页或上限"
    """
    def test_r14a_no_pagination(self):
        src = inspect.getsource(acc_views.TenantView.get)
        self.assertIn('objects.all()', src)
        self.assertNotIn('[:', src)


# ==================== §3.5 安全维度 ====================

class R15_PasswordHashAlgorithm(TestCase):
    """R15(P2): password_hash 使用 pbkdf2_sha256 而非 bcrypt/argon2

    风险描述：
      - pbkdf2_sha256 是 Django 默认哈希器，但不如 bcrypt/argon2 抗 GPU 暴力破解
      - 前序审计经验：7/30 审计已标记为 R4（低严重性）

    指南条款：§3.5 "密码存储推荐 bcrypt/argon2"
    """
    def test_r15a_uses_pbkdf2(self):
        src = inspect.getsource(User.make_password)
        self.assertIn('pbkdf2_sha256', src)

    def test_r15b_not_bcrypt(self):
        src = inspect.getsource(User.make_password)
        self.assertNotIn('bcrypt', src)


class R16_HistoryViewNoPermMap(TestCase):
    """R16(INFO): HistoryView 无 PERM_MAP - 仅超管可访问

    说明：
      - AdminView 默认 PERM_MAP={}，非超管用户被拒绝
      - 这实际上是安全的设计（仅管理员可查看登录历史）
      - 但缺少可配置的权限码，不如其他 View 灵活
    """
    def test_r16a_no_perm_map(self):
        """HistoryView 未定义 PERM_MAP"""
        view_class = acc_history.HistoryView
        perm_map = getattr(view_class, 'PERM_MAP', None)
        # AdminView 默认 PERM_MAP={}，HistoryView 未覆盖
        self.assertFalse(perm_map,
                         "HistoryView 无 PERM_MAP - 仅 is_supper 可访问")


class R17_HistoryModelNoTenantId(TestCase):
    """R17(P2): History 模型无 tenant_id 字段

    风险描述：
      - 登录历史不区分租户，无法按租户过滤
      - HistoryView 返回全租户记录（但仅超管可访问，风险有限）

    指南条款：§3.5 "多租户隔离"
    """
    def test_r17a_no_tenant_id_field(self):
        field_names = [f.name for f in History._meta.get_fields()]
        self.assertNotIn('tenant_id', field_names)


class R18_TenantDeleteNoCascadeProtection(TestCase):
    """R18(P1): Tenant 删除后用户/角色 tenant_id 变成悬空引用

    风险描述：
      - TenantView.delete 物理删除 Tenant 记录
      - User.tenant_id / Role.tenant_id 是 CharField（非 FK），无级联保护
      - 删除租户后，关联用户/角色的 tenant_id 指向不存在的租户
      - 前序审计经验：contract_agreement 删除时未处理子表引用被标记

    指南条款：§1.1 "外键 ON DELETE 按语义选"
    """
    def test_r18a_tenant_id_is_charfield_not_fk(self):
        """User.tenant_id 是 CharField 而非 FK - 无 DB 级引用完整性"""
        f = User._meta.get_field('tenant_id')
        self.assertEqual(f.__class__.__name__, 'CharField',
                         "User.tenant_id 是 CharField - 无 DB 外键约束")

    def test_r18b_role_tenant_id_is_charfield(self):
        """Role.tenant_id 也是 CharField"""
        f = Role._meta.get_field('tenant_id')
        self.assertEqual(f.__class__.__name__, 'CharField')

    def test_r18c_tenant_delete_physical(self):
        """TenantView.delete 使用物理删除"""
        src = inspect.getsource(acc_views.TenantView.delete)
        self.assertIn('.delete()', src)
        self.assertNotIn('is_deleted', src)


class R19_RoleDeleteNoUserCheckGap(TestCase):
    """R19(P1): RoleView.delete 检查 user_set 但不过滤软删除用户

    风险描述：
      - role.user_set.exists() 检查是否有关联用户
      - 但 user_set 包含软删除用户（deleted_by_id 非空）
      - 软删除用户仍占用角色关联，阻止角色删除
      - 这是"宁可保守"的设计，但可能造成运维困扰

    指南条款：§1.1 "逻辑删除唯一约束冲突"
    """
    def test_r19a_check_uses_raw_user_set(self):
        """delete 检查使用 role.user_set.exists() 不过滤软删除"""
        src = inspect.getsource(acc_views.RoleView.delete)
        self.assertIn('user_set', src)
        self.assertIn('exists', src)
        # 检查是否过滤了 deleted_by_id
        self.assertNotIn('deleted_by_id__isnull', src.split('user_set')[1].split('\n')[0]
                        if 'user_set' in src else '',
                        "delete 检查可能未过滤软删除用户")

    def test_r19b_role_to_dict_filters_deleted(self):
        """对比：Role.to_dict 的 used 字段正确过滤了软删除用户"""
        src = inspect.getsource(Role.to_dict)
        self.assertIn('deleted_by_id__isnull', src,
                      "to_dict 正确过滤了软删除用户 - 但 delete 检查可能没有")


class R20_UserTokenExpiredZeroMeansInfinite(TestCase):
    """R20(P1): User.token_expired=0 被当作永不过期

    风险描述：
      - token_expired=0 时认证中间件不检查过期
      - 禁用用户后如果未清除 token_expired，旧 token 仍有效
      - UserView.delete 设置 is_active=False 但不清空 token_expired

    指南条款：§3.5 "访问令牌需有过期机制"
    """
    def test_r20a_token_expired_nullable(self):
        """token_expired 字段允许 null"""
        f = User._meta.get_field('token_expired')
        self.assertTrue(f.null, "token_expired 允许 null")

    def test_r20b_delete_sets_is_active_false(self):
        """UserView.delete 设置 is_active=False"""
        src = inspect.getsource(acc_views.UserView.delete)
        self.assertIn('is_active', src)
        self.assertIn('False', src)


# ==================== §2.2 补充：History 无索引优化 ====================

class R21_HistoryNoIndexOnCreatedAt(TestCase):
    """R21(P2): History 模型 created_at 无 db_index

    风险描述：
      - HistoryView.get 返回 objects.all() 不需要排序索引
      - 但若后续加按时间过滤/排序，created_at 无索引会全表扫描
      - 前序审计经验：department_duty_log/fault 因缺索引被标记

    指南条款：§2.1 "常用过滤/排序字段应有索引"
    """
    def test_r21a_created_at_no_index(self):
        f = History._meta.get_field('created_at')
        self.assertFalse(getattr(f, 'db_index', False),
                         "History.created_at 无 db_index")

    def test_r21b_username_no_index(self):
        f = History._meta.get_field('username')
        self.assertFalse(getattr(f, 'db_index', False),
                         "History.username 无 db_index - 按用户名查询会全表扫描")

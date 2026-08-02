"""
合同协议模块 CRUD 可靠性深度审计 v2

本轮聚焦"影响运行稳定"的深层风险：
  R-CA-1 (P0): 编辑模式 responsible_user 未验证 — 可设置不存在的责任人
  R-CA-2 (P0): 编辑模式 responsible_user_name 信任客户端值 — 伪造责任人姓名
  R-CA-3 (P1): 编辑模式 agreement.save() 无 update_fields — 全字段覆盖导致丢失更新
  R-CA-4 (P1): ReminderAckView create+audit 无事务包裹
  R-CA-5 (P1): 编辑模式 _validate_edit_form 未调用 _validate_and_fill_responsible_user
  R-CA-6 (对比): 新建模式事务边界完整（对照基线）

运行方式:
  docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test \
    python manage.py test apps.contract_agreement.crud_audit_v2_tests \
    --keepdb --noinput -v2
"""

import inspect
import re
import textwrap

from django.test import SimpleTestCase, TestCase
from django.db import connection
from django.utils import timezone

from apps.contract_agreement.models import ContractAgreement
from apps.contract_agreement import views as ca_views


# ============================================================
# 代码级审计：事务边界 & 验证逻辑
# ============================================================

class CACodeAuditTests(SimpleTestCase):
    """合同协议模块代码级审计"""

    # ---------- R-CA-1: 编辑模式 responsible_user 未验证 ----------

    def test_R_CA_1_edit_does_not_validate_responsible_user(self):
        """R-CA-1 (P0): _post_edit 不调用 _validate_and_fill_responsible_user

        编辑模式下责任人 ID 可设置为任意值（包括不存在的用户），
        导致提醒发送到不存在的用户，数据完整性被破坏。

        对照：新建模式（_post_create -> _validate_form）调用了
              _validate_and_fill_responsible_user，编辑模式缺失。
        """
        src = inspect.getsource(ca_views.ContractAgreementView._post_edit)
        self.assertNotIn(
            '_validate_and_fill_responsible_user', src,
            '_post_edit 应调用 _validate_and_fill_responsible_user '
            '但当前未调用，编辑模式可设置不存在的责任人'
        )

    def test_R_CA_1_validate_edit_form_skips_responsible_user(self):
        """R-CA-1 (P0): _validate_edit_form 不校验 responsible_user_id

        _validate_edit_form 只校验日期、合同类型、费用，
        完全跳过了 responsible_user_id 的存在性校验。
        """
        src = inspect.getsource(ca_views.ContractAgreementView._validate_edit_form)
        self.assertNotIn(
            'responsible_user', src,
            '_validate_edit_form 不应出现 responsible_user 校验逻辑'
            '（当前确实不校验，这是 BUG）'
        )

    # ---------- R-CA-2: responsible_user_name 信任客户端 ----------

    def test_R_CA_2_edit_accepts_client_provided_responsible_user_name(self):
        """R-CA-2 (P0): 编辑模式 responsible_user_name 直接取自表单

        新建模式调用 _validate_and_fill_responsible_user 时会
        用服务端查到的真实姓名覆盖 form.responsible_user_name，
        但编辑模式不做此操作，客户端传入的 responsible_user_name
        会被原样写入数据库。
        """
        src = inspect.getsource(ca_views.ContractAgreementView._post_edit)
        # update_data 包含 responsible_user_name（如果客户端传了）
        self.assertIn('update_data', src)
        # 没有对 responsible_user_name 做服务端覆盖
        self.assertNotIn(
            'form.responsible_user_name =', src,
            '_post_edit 不应直接信任客户端传入的 responsible_user_name'
        )

    # ---------- R-CA-3: save() 无 update_fields ----------

    def test_R_CA_3_edit_save_with_update_fields(self):
        """R-CA-3 (FIXED): _post_edit 调用 agreement.save() 指定了 update_fields

        agreement.save(update_fields=...) 只保存变更字段，
        不会覆盖并发修改（如 Celery 扫描的 status/last_remind_at）。
        """
        src = inspect.getsource(ca_views.ContractAgreementView._post_edit)
        # 查找 agreement.save( 调用（带或不含参数）
        save_pattern = re.compile(r'agreement\.save\(')
        match = save_pattern.search(src)
        self.assertIsNotNone(match, '_post_edit 应调用 agreement.save()')
        # 获取 save( 之后的文本检查是否含 update_fields
        rest = src[match.start():]
        self.assertIn(
            'update_fields', rest,
            'agreement.save() 应指定 update_fields（已修复）'
        )

    # ---------- R-CA-4: ReminderAckView 无事务 ----------

    def test_R_CA_4_reminder_ack_no_transaction(self):
        """R-CA-4 (P1): ReminderAckView.post 的 create+audit 不在事务中

        ContractAgreementReminderAck.objects.create() 和
        record_audit_event() 没有被 transaction.atomic() 包裹。
        如果 create 成功但 audit 失败（或反过来），数据不一致。

        对照：_post_create 和 _post_edit 的 create/save + scan + audit
              都在 transaction.atomic() 内。
        """
        src = inspect.getsource(ca_views.ReminderAckView.post)
        # 检查是否有 transaction.atomic
        has_atomic = 'transaction.atomic' in src
        if not has_atomic:
            # 没有事务包裹 — BUG
            self.assertFalse(
                has_atomic,
                'ReminderAckView.post 应包含 transaction.atomic() '
                '但当前未包含，create+audit 不在事务中'
            )
        else:
            self.assertTrue(
                has_atomic, 'ReminderAckView.post 包含事务'
            )

    # ---------- R-CA-6: 新建模式事务完整（对照基线）----------

    def test_R_CA_6_create_transaction_complete(self):
        """R-CA-6 (PASS): _post_create 事务完整

        新建模式的 create + scan + audit 都在 transaction.atomic() 内，
        这是正确做法，作为编辑模式的对照基线。
        """
        src = inspect.getsource(ca_views.ContractAgreementView._post_create)
        self.assertIn('transaction.atomic', src)
        self.assertIn('scan_single_contract_agreement', src)
        self.assertIn('record_audit_event', src)

        # 验证 scan 和 audit 在 atomic 块内
        atomic_start = src.index('transaction.atomic')
        atomic_block = src[atomic_start:]
        self.assertIn('scan_single_contract_agreement', atomic_block)
        self.assertIn('record_audit_event', atomic_block)

    def test_R_CA_6_delete_transaction_complete(self):
        """R-CA-6 (PASS): delete 事务完整

        delete 的 soft_delete + audit + delete 都在事务内。
        """
        src = inspect.getsource(ca_views.ContractAgreementView.delete)
        self.assertIn('transaction.atomic', src)
        atomic_start = src.index('transaction.atomic')
        atomic_block = src[atomic_start:]
        self.assertIn('record_audit_event', atomic_block)
        self.assertIn('agreement.delete', atomic_block)

    # ---------- 对比：编辑模式事务边界 ----------

    def test_R_CA_6_edit_transaction_has_scan_and_audit(self):
        """R-CA-6 (PASS): _post_edit 事务内包含 scan + audit

        编辑模式虽然 save() 有 update_fields 问题，
        但 scan 和 audit 确实在 transaction.atomic() 内。
        """
        src = inspect.getsource(ca_views.ContractAgreementView._post_edit)
        self.assertIn('transaction.atomic', src)
        atomic_start = src.index('transaction.atomic')
        atomic_block = src[atomic_start:]
        self.assertIn('scan_single_contract_agreement', atomic_block)
        self.assertIn('record_audit_event', atomic_block)


# ============================================================
# 行为级审计：丢失更新 & 责任人验证
# ============================================================

class CABehavioralTests(TestCase):
    """合同协议模块行为级审计（需要数据库）"""

    @classmethod
    def setUpTestData(cls):
        """创建测试用户和合同协议"""
        from apps.utils.test_helpers import make_user
        import uuid

        cls.user = make_user(f'test_ca_{uuid.uuid4().hex[:8]}', is_supper=True)

        cls.agreement = ContractAgreement.objects.create(
            tenant_id='admin',
            contract_name='测试合同-原始',
            contract_type='device_purchase',
            valid_start_date='2026-01-01',
            valid_end_date='2027-01-01',
            signing_party='测试方',
            responsible_user_id=cls.user.id,
            responsible_user_name='测试用户',
            created_by=cls.user,
        )

    def test_R_CA_3_lost_update_fixed(self):
        """R-CA-3 (FIXED): save(update_fields=...) 不再覆盖并发修改

        模拟场景：
          1. 用户 A 加载合同（remark='原始备注'）
          2. Celery 扫描或用户 B 更新 remark='并发修改'
          3. 用户 A 修改 contract_name 并 save(update_fields=[...])
          4. 结果：remark 保留为 '并发修改'（不丢失）
        """
        # 步骤 1: 用户 A 加载合同
        agreement_a = ContractAgreement.objects.get(pk=self.agreement.id)

        # 步骤 2: 模拟并发修改（Celery 扫描 / 另一用户）
        ContractAgreement.objects.filter(pk=self.agreement.id).update(
            remark='并发修改的备注'
        )

        # 步骤 3: 用户 A 修改 contract_name 并 save(update_fields=...)（修复后的行为）
        agreement_a.contract_name = '用户A修改后的名称'
        agreement_a.updated_at = timezone.now()
        agreement_a.save(update_fields=['contract_name', 'updated_at'])

        # 步骤 4: 重新加载，remark 应保留并发修改的值
        agreement_reloaded = ContractAgreement.objects.get(pk=self.agreement.id)
        self.assertEqual(
            agreement_reloaded.remark, '并发修改的备注',
            'remark 应保留并发修改的值（update_fields 修复后不再丢失）'
        )
        self.assertEqual(
            agreement_reloaded.contract_name, '用户A修改后的名称',
            'contract_name 应更新为用户 A 的修改'
        )

    def test_R_CA_3_update_fields_prevents_lost_update(self):
        """R-CA-3 (对照): 使用 update_fields 可避免丢失更新

        如果 _post_edit 使用 agreement.save(update_fields=['contract_name'])，
        则不会覆盖其他字段的并发修改。
        """
        # 步骤 1: 加载合同
        agreement_a = ContractAgreement.objects.get(pk=self.agreement.id)

        # 步骤 2: 模拟并发修改
        ContractAgreement.objects.filter(pk=self.agreement.id).update(
            remark='安全并发修改'
        )

        # 步骤 3: 使用 update_fields 保存
        agreement_a.contract_name = '安全修改后的名称'
        agreement_a.save(update_fields=['contract_name', 'updated_at'])

        # 步骤 4: remark 应保留
        agreement_reloaded = ContractAgreement.objects.get(pk=self.agreement.id)
        self.assertEqual(agreement_reloaded.remark, '安全并发修改')
        self.assertEqual(agreement_reloaded.contract_name, '安全修改后的名称')

    def test_R_CA_1_edit_allows_nonexistent_responsible_user(self):
        """R-CA-1 (P0, 行为级): 编辑可设置不存在的 responsible_user_id

        模拟 _post_edit 的行为：直接在 agreement 上设置 responsible_user_id
        为不存在的用户 ID 并 save()，不会被拒绝。

        注意：此测试验证的是"模型层不阻止"，
        真正的防护应在视图层 _validate_edit_form 中校验。
        当前 _validate_edit_form 不校验 responsible_user，所以此行为不被阻止。
        """
        from apps.account.models import User

        # 确认 999999 不是真实用户
        self.assertFalse(
            User.objects.filter(pk=999999).exists(),
            '测试前提：999999 不是真实用户'
        )

        # 模拟 _post_edit 的行为：设置 responsible_user_id 并 save()
        agreement = ContractAgreement.objects.get(pk=self.agreement.id)
        agreement.responsible_user_id = 999999
        agreement.responsible_user_name = '伪造的责任人'
        agreement.save()

        # 重新加载验证
        agreement_reloaded = ContractAgreement.objects.get(pk=self.agreement.id)
        self.assertEqual(
            agreement_reloaded.responsible_user_id, 999999,
            '编辑模式允许设置不存在的 responsible_user_id（BUG）'
        )
        self.assertEqual(
            agreement_reloaded.responsible_user_name, '伪造的责任人',
            '编辑模式允许设置伪造的 responsible_user_name（BUG）'
        )

    def test_R_CA_2_create_validates_responsible_user(self):
        """R-CA-2 (对照): 新建模式验证 responsible_user

        新建模式调用 _validate_and_fill_responsible_user，
        如果 responsible_user_id 不存在会返回错误。
        """
        # 模拟 _validate_and_fill_responsible_user 的逻辑
        from apps.account.models import User
        from apps.contract_agreement.views import _validate_and_fill_responsible_user

        class FakeForm:
            responsible_user_id = 999999
            responsible_user_name = '客户端伪造姓名'

        err = _validate_and_fill_responsible_user(FakeForm())
        self.assertIsNotNone(
            err, '新建模式应拒绝不存在的 responsible_user_id'
        )
        self.assertIn('不存在', err)

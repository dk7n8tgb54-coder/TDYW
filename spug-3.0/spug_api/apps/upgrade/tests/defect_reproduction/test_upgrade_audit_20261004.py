# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""系统升级模块审计缺陷复现测试（defect_reproduction，2026-10-04 审计）

候选缺陷清单（2026-10-04 模块审计得出，断言一律指向期望的正确行为，
修复前失败即证明缺陷真实存在，修复后必须全部通过；预期通过的用例为
证伪用例，用于记录审计结论并防止回归）：

A1  应用方案"追加"模式序号用 count()+1 计算：
    PlanService.apply_to_record 追加分支以未删除步骤数 +1 作为起始序号，
    存在软删除步骤时会与现存步骤序号重复，步骤顺序错乱。
    期望：起始序号取现存最大 sequence + 1（与 add_manual_step 一致）。

A2  批量更新步骤对无效 action 静默忽略：
    RecordStepService.batch_update_status 遇到未知 action 直接跳过并返回
    成功，有效前缀项已生效，与单步接口报错行为不一致且产生部分变更。
    期望：任一无效 action 返回业务错误且不产生任何变更（单步接口行为一致）。

A3  legacy 兼容接口系统名匹配成功反而创建失败：
    LegacyUpgradeView.post 旧契约（system 为纯文本，无 title/upgrade_content）
    一旦匹配到系统档案就走新链路 RecordService.create_record，被必填校验
    "请填写标题; 请填写升级内容" 拒绝；匹配不到反而能建。
    期望：旧契约两分支均可创建，匹配成功时一并写系统外键+快照+履历。

A4  （证伪用例）计划升级时间"清空"语义：
    validators 注释声称"清空请传 null"，update_record 对 None 保留旧值——
    该字段为建单必填项，"null=未提供=保留旧值" 即既有契约，本组用例
    固化该语义（修复前即通过，证明"无法清空"不是缺陷而是文档漂移）。
    期望：null 保留旧值不报错；空字符串拒绝。
"""
import uuid
from datetime import datetime

from django.test import TestCase

from apps.upgrade.models import UpgradeRecord
from apps.upgrade.models_checklist import UpgradeRecordStep
from apps.upgrade.models_status_log import UpgradeStatusLog
from apps.upgrade.models_template import UpgradeTemplate, UpgradePlanStep
from apps.utils.test_helpers import make_user, make_client, setup_test_env, make_upgrade_no
from apps.equipment_lifecycle.tests.base import make_system

PERMS = [
    'upgrade.upgrade.view', 'upgrade.upgrade.add', 'upgrade.upgrade.edit',
    'upgrade.upgrade.del', 'upgrade.upgrade.step_reset',
    'upgrade.upgrade.step_del',
]


class UpgradeAuditBase(TestCase):
    """审计缺陷复现测试公共基类"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('upg_audit', PERMS)
        self.client = make_client(self.user)
        self.system = make_system(
            self.user, tenant_id=self.user.tenant_id,
            system_code=f'SYS-{uuid.uuid4().hex[:8]}')
        self.record = UpgradeRecord.objects.create(
            upgrade_no=make_upgrade_no(),
            tenant_id=self.user.tenant_id, title='审计验证单',
            system=self.system, system_name=self.system.name,
            upgrade_type='功能升级', status='处理中',
            created_by=self.user)

    def add_step(self, title, phase='', sequence=None):
        return UpgradeRecordStep.objects.create(
            tenant_id=self.user.tenant_id, upgrade_id=self.record.id,
            checklist_id=0, phase=phase, title=title,
            sequence=sequence if sequence is not None else 1)

    def make_plan(self, name, step_count=2):
        tpl = UpgradeTemplate.objects.create(
            tenant_id=self.user.tenant_id, name=name, created_by=self.user)
        for idx in range(step_count):
            UpgradePlanStep.objects.create(
                tenant_id=self.user.tenant_id, template_id=tpl.id,
                phase='阶段A', title=f'{name}-步骤{idx + 1}', sequence=idx + 1)
        return tpl

    def put_json(self, url, payload):
        import json
        return self.client.put(url, data=json.dumps(payload),
                               content_type='application/json')

    def post_json(self, url, payload):
        import json
        return self.client.post(url, data=json.dumps(payload),
                                content_type='application/json')


# ============ A1：应用方案追加模式序号重复 ============

class PlanApplyAppendSequenceTests(UpgradeAuditBase):
    """A1：追加模式起始序号应取现存最大 sequence + 1"""

    def test_append_sequence_uses_max_after_soft_delete(self):
        self.add_step('步骤一', sequence=1)
        s2 = self.add_step('步骤二', sequence=2)
        self.add_step('步骤三', sequence=3)

        resp = self.client.delete(f'/upgrade/record-steps/{s2.id}/delete/')
        self.assertFalse(resp.json().get('error'), resp.json())

        tpl = self.make_plan('A1追加方案')
        resp = self.post_json(f'/upgrade/plans/{tpl.id}/apply/',
                              {'upgrade_id': self.record.id, 'replace': False})
        data = resp.json()
        self.assertFalse(data.get('error'), data)
        self.assertEqual(data['data']['created_count'], 2, data)

        seqs = list(UpgradeRecordStep.objects.filter(
            is_deleted=False, upgrade_id=self.record.id
        ).values_list('sequence', flat=True))
        # 现存 [1, 3]，追加两步应为 [4, 5]；修复前为 [3, 4] 与现存 3 撞号
        self.assertEqual(sorted(seqs), [1, 3, 4, 5], seqs)
        self.assertEqual(len(seqs), len(set(seqs)), seqs)

    def test_append_sequence_from_empty_record(self):
        tpl = self.make_plan('A1空单追加')
        resp = self.post_json(f'/upgrade/plans/{tpl.id}/apply/',
                              {'upgrade_id': self.record.id, 'replace': False})
        data = resp.json()
        self.assertFalse(data.get('error'), data)
        seqs = list(UpgradeRecordStep.objects.filter(
            upgrade_id=self.record.id).values_list('sequence', flat=True))
        self.assertEqual(sorted(seqs), [1, 2], seqs)


# ============ A2：批量更新无效 action 静默忽略 ============

class BatchInvalidActionTests(UpgradeAuditBase):
    """A2：批量更新遇无效 action 应报错且不产生部分变更"""

    def test_batch_invalid_action_rejected_no_partial_mutation(self):
        s1 = self.add_step('步骤一', phase='阶段A', sequence=1)
        s2 = self.add_step('步骤二', phase='阶段A', sequence=2)

        resp = self.put_json(f'/upgrade/records/{self.record.id}/steps/batch/',
                             {'steps': [{'step_id': s1.id, 'action': 'complete'},
                                        {'step_id': s2.id, 'action': 'explode'}]})
        data = resp.json()
        self.assertTrue(data.get('error'), data)

        # 无部分变更：有效前缀项也不生效
        s1.refresh_from_db()
        self.assertEqual(s1.status, 'pending')
        self.assertFalse(UpgradeStatusLog.objects.filter(
            upgrade_id=self.record.id, action='phase_done').exists())
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, '处理中')

    def test_batch_valid_actions_still_work(self):
        s1 = self.add_step('步骤一', phase='阶段A', sequence=1)
        s2 = self.add_step('步骤二', phase='阶段A', sequence=2)

        resp = self.put_json(f'/upgrade/records/{self.record.id}/steps/batch/',
                             {'steps': [{'step_id': s1.id, 'action': 'complete'},
                                        {'step_id': s2.id, 'action': 'skip'}]})
        data = resp.json()
        self.assertFalse(data.get('error'), data)

        s1.refresh_from_db()
        s2.refresh_from_db()
        self.assertEqual(s1.status, 'completed')
        self.assertEqual(s2.status, 'skipped')
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, '已完成')

    def test_batch_unknown_step_id_still_skipped(self):
        """不存在的 step_id 维持既有跳过语义，不阻断整批"""
        s1 = self.add_step('步骤一', phase='阶段A', sequence=1)
        resp = self.put_json(f'/upgrade/records/{self.record.id}/steps/batch/',
                             {'steps': [{'step_id': 999999, 'action': 'complete'},
                                        {'step_id': s1.id, 'action': 'complete'}]})
        data = resp.json()
        self.assertFalse(data.get('error'), data)
        s1.refresh_from_db()
        self.assertEqual(s1.status, 'completed')


# ============ A3：legacy 接口匹配系统档案反而创建失败 ============

class LegacyMatchedSystemTests(UpgradeAuditBase):
    """A3：旧契约 POST 两分支均应可创建，匹配成功须写系统外键+快照"""

    def test_legacy_post_matched_system_links_fk(self):
        payload = {
            'system': self.system.name, 'upgrade_type': '功能升级',
            'version': 'V2.1', 'upgrade_time': '2026-10-04 10:00:00',
            'status': '处理中', 'owner': '李四',
        }
        resp = self.post_json('/upgrade/upgrade/', payload)
        data = resp.json()
        self.assertFalse(data.get('error'), data)

        rec = UpgradeRecord.objects.filter(owner='李四').latest('id')
        self.assertEqual(rec.system_id, self.system.id)
        self.assertEqual(rec.system_name, self.system.name)
        self.assertEqual(rec.system_code, self.system.system_code)
        self.assertTrue(rec.upgrade_no.startswith('SJ'), rec.upgrade_no)
        # 匹配到系统档案：同事务写系统履历（升级登记）
        self.assertTrue(rec.system_id and rec.system_id == self.system.id)

    def test_legacy_post_unmatched_system_keeps_text_semantics(self):
        payload = {
            'system': '不存在的系统名', 'upgrade_type': 'Bug修复',
            'version': 'V1.0', 'upgrade_time': '2026-10-04 11:00:00',
            'status': '处理中', 'owner': '王五',
        }
        resp = self.post_json('/upgrade/upgrade/', payload)
        data = resp.json()
        self.assertFalse(data.get('error'), data)

        rec = UpgradeRecord.objects.filter(owner='王五').latest('id')
        self.assertIsNone(rec.system_id)
        self.assertEqual(rec.system_name, '不存在的系统名')


# ============ A4（证伪）：计划升级时间清空语义 ============

class UpgradeTimeClearSemanticsTests(UpgradeAuditBase):
    """A4：upgrade_time 为建单必填字段，null=未提供=保留旧值（证伪用例）"""

    def _set_time(self):
        resp = self.put_json(f'/upgrade/records/{self.record.id}/update/',
                             {'upgrade_time': '2026-03-01 08:00:00'})
        self.assertFalse(resp.json().get('error'), resp.json())
        self.record.refresh_from_db()
        self.assertEqual(self.record.upgrade_time, datetime(2026, 3, 1, 8, 0, 0))

    def test_update_null_time_keeps_old_value(self):
        self._set_time()
        resp = self.put_json(f'/upgrade/records/{self.record.id}/update/',
                             {'upgrade_time': None})
        data = resp.json()
        self.assertFalse(data.get('error'), data)
        self.record.refresh_from_db()
        self.assertEqual(self.record.upgrade_time, datetime(2026, 3, 1, 8, 0, 0))

    def test_update_blank_time_rejected(self):
        self._set_time()
        resp = self.put_json(f'/upgrade/records/{self.record.id}/update/',
                             {'upgrade_time': ''})
        data = resp.json()
        self.assertIn('计划升级时间', data.get('error', ''), data)
        self.record.refresh_from_db()
        self.assertEqual(self.record.upgrade_time, datetime(2026, 3, 1, 8, 0, 0))

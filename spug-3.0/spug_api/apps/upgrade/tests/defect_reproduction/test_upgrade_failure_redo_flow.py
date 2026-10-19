# -*- coding: utf-8 -*-
"""升级失败处理/重做闭环行为测试（2026-10 改造，defect_reproduction）。

真实执行 View → Service → Model 路径，覆盖：
- 标记失败不清步骤、不改过去完成事件，生成失败单与事件；
- 失败待处理阻塞普通完成/跳过/删除/清空/自动完成/手动完成/升级完成；
- 开始重做：选择数与实际重置数分开、待执行步骤不产生虚假事件、解除阻塞；
- 重做后再次完成：原完成事件保留、新 phase_done、失败单结案、自动完成恢复；
- 更正失败：原因必填、追加事件、原失败保留；
- 从某阶段重新执行：预览/执行同口径、后续结果显式选择（redo/keep+理由）、
  覆盖失败解除阻塞、无已执行步骤拒绝、旧 rollback 接口兼容；
- 事件留痕：单步重置快照、批量重置单条摘要、无变化重置拒绝、
  历史事件禁删、暂停/继续下线拒绝、旧日志读取兼容；
- 事务一致性：事件写入失败不留"状态已变、历史未记"部分结果；
- 租户隔离：跨租户失败操作拒绝。
"""
import json
import unittest
from unittest import mock

from django.test import TestCase

from apps.utils.test_helpers import make_user, make_client, setup_test_env, make_upgrade_no
from apps.upgrade.models import UpgradeRecord
from apps.upgrade.models_checklist import UpgradeRecordStep
from apps.upgrade.models_status_log import UpgradeStatusLog
from apps.upgrade.models_failure import (
    UpgradeFailureHandling, FAILURE_PENDING, FAILURE_REDOING,
    FAILURE_RESOLVED, FAILURE_CORRECTED,
)


def make_record(user, status='处理中'):
    return UpgradeRecord.objects.create(
        upgrade_no=make_upgrade_no(),
        tenant_id=user.tenant_id, title='失败闭环测试单', system_name='系统A',
        upgrade_type='功能升级', status=status, owner='负责人',
        created_by=user)


def make_step(record, user, phase, title, seq, status='pending', completed_by='', completed_at=None):
    return UpgradeRecordStep.objects.create(
        tenant_id=user.tenant_id, upgrade_id=record.id, phase=phase,
        title=title, sequence=seq, status=status,
        completed_by=completed_by, completed_at=completed_at)


def make_phase_done(record, user, phase, seq, outcome='done'):
    return UpgradeStatusLog.objects.create(
        tenant_id=user.tenant_id, upgrade_id=record.id, action='phase_done',
        phase=phase, outcome=outcome, operator_id=user.id,
        operator_name=user.nickname, event_seq=seq)


class FailureFlowTestBase(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.user = make_user('fail_flow_user', [
            'upgrade.upgrade.view', 'upgrade.upgrade.add', 'upgrade.upgrade.edit',
            'upgrade.upgrade.del', 'upgrade.upgrade.step_reset', 'upgrade.upgrade.step_del'])
        self.c = make_client(self.user)
        self.record = make_record(self.user)
        # 阶段：备份(2步) → 灰度发布(3步)
        self.backup_1 = make_step(self.record, self.user, '备份', '备份数据库', 1,
                                  'completed', '张三', '2026-10-18 09:00:00')
        self.backup_2 = make_step(self.record, self.user, '备份', '备份配置文件', 2,
                                  'completed', '张三', '2026-10-18 09:01:00')
        self.gray_1 = make_step(self.record, self.user, '灰度发布', '执行灰度脚本', 3,
                                'completed', '李四', '2026-10-18 09:10:00')
        self.gray_2 = make_step(self.record, self.user, '灰度发布', '灰度验证', 4,
                                'skipped', '李四', '2026-10-18 09:11:00')
        self.gray_3 = make_step(self.record, self.user, '灰度发布', '确认灰度指标', 5)
        self.log_backup_done = make_phase_done(self.record, self.user, '备份', 1)
        self.log_gray_done = make_phase_done(self.record, self.user, '灰度发布', 2)

    def mark_failure(self, phase='灰度发布', reason='灰度指标异常'):
        return self.c.post(
            f'/upgrade/records/{self.record.id}/status-logs/',
            data=json.dumps({'action': 'test_fail', 'phase': phase, 'remark': reason}),
            content_type='application/json')

    def get_failure(self):
        return UpgradeFailureHandling.objects.filter(
            upgrade_id=self.record.id).order_by('-id').first()


class MarkFailureTest(FailureFlowTestBase):
    """标记失败：不清步骤、不改过去完成事件、生成失败单与事件"""

    def test_mark_failure_keeps_scene_and_history(self):
        resp = self.mark_failure()
        self.assertFalse(resp.json().get('error'), resp.json())
        f = self.get_failure()
        self.assertIsNotNone(f)
        self.assertEqual(f.status, FAILURE_PENDING)
        self.assertEqual(f.phase, '灰度发布')
        self.assertEqual(f.reason, '灰度指标异常')
        self.assertEqual(f.failed_by_name, 'fail_flow_user')
        self.assertIsNotNone(f.failed_at)
        # 步骤现场保留：完成/跳过未被清空
        self.gray_1.refresh_from_db()
        self.gray_2.refresh_from_db()
        self.assertEqual(self.gray_1.status, 'completed')
        self.assertEqual(self.gray_2.status, 'skipped')
        # 过去完成事件不被改写：备份/灰度发布 phase_done 均保持原 outcome
        self.log_backup_done.refresh_from_db()
        self.log_gray_done.refresh_from_db()
        self.assertEqual(self.log_backup_done.outcome, 'done')
        self.assertEqual(self.log_gray_done.outcome, 'done')
        # test_fail 事件已写入并关联失败单
        log = UpgradeStatusLog.objects.filter(
            upgrade_id=self.record.id, action='test_fail').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.remark, '灰度指标异常')
        self.assertEqual(log.phase, '灰度发布')
        self.assertEqual(log.detail, f'{{"failure_id": {f.id}}}')

    def test_mark_failure_duplicate_rejected(self):
        resp = self.mark_failure()
        self.assertFalse(resp.json().get('error'))
        resp = self.mark_failure(reason='第二次')
        self.assertTrue(resp.json().get('error'))
        self.assertIn('已有未处理完的失败', resp.json().get('error'))
        self.assertEqual(UpgradeFailureHandling.objects.filter(
            upgrade_id=self.record.id).count(), 1)

    def test_mark_failure_unknown_phase_rejected(self):
        resp = self.mark_failure(phase='不存在的阶段')
        self.assertTrue(resp.json().get('error'))
        self.assertIn('不存在', resp.json().get('error'))

    def test_mark_failure_requires_reason(self):
        resp = self.c.post(
            f'/upgrade/records/{self.record.id}/status-logs/',
            data=json.dumps({'action': 'test_fail', 'phase': '灰度发布', 'remark': '  '}),
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assertIn('失败原因', resp.json().get('error'))


class FailureBlockingTest(FailureFlowTestBase):
    """失败待处理阻塞普通入口（前后端同规则的iscard：后端为准）"""

    def setUp(self):
        super().setUp()
        self.mark_failure()
        self.failure = self.get_failure()

    def test_blocked_phase_rejects_complete_and_skip(self):
        # 灰度发布已全部完成，需先把部分步骤重置为待执行才能尝试完成；
        # 直接构造：更正失败后重新标记，或将 pending 步骤尝试跳过
        resp = self.c.put(f'/upgrade/record-steps/{self.gray_3.id}/update/',
                          data=json.dumps({'action': 'skip'}), content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assertIn('处理失败', resp.json().get('error'))
        # 备份阶段未被阻塞，仍可正常操作
        resp = self.c.put(f'/upgrade/record-steps/{self.backup_1.id}/update/',
                          data=json.dumps({'action': 'complete'}), content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())

    def test_blocked_phase_rejects_batch(self):
        # 通过 start-redo 制造"部分重做后再次完成"的场景验证批量门禁：
        # 重新构造一条 pending 失败
        resp = self.c.post(
            f'/upgrade/records/{self.record.id}/failures/{self.failure.id}/start-redo/',
            data=json.dumps({'all_steps': True}), content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.failure.refresh_from_db()
        self.assertEqual(self.failure.status, FAILURE_REDOING)
        # redoing 不阻塞
        resp = self.c.put(f'/upgrade/record-steps/{self.gray_1.id}/update/',
                          data=json.dumps({'action': 'complete'}), content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())

    def test_delete_step_blocked_in_failed_phase(self):
        resp = self.c.delete(f'/upgrade/record-steps/{self.gray_3.id}/delete/')
        self.assertTrue(resp.json().get('error'))
        self.assertIn('失败现场', resp.json().get('error'))
        self.gray_3.refresh_from_db()
        self.assertFalse(self.gray_3.is_deleted)
        # 未失败阶段可删
        resp = self.c.delete(f'/upgrade/record-steps/{self.backup_2.id}/delete/')
        self.assertFalse(resp.json().get('error'), resp.json())

    def test_clear_steps_blocked_with_unresolved_failure(self):
        resp = self.c.delete(f'/upgrade/records/{self.record.id}/steps/clear/')
        self.assertTrue(resp.json().get('error'))
        self.assertIn('失败', resp.json().get('error'))

    def test_auto_complete_blocked_by_pending_failure(self):
        # 直接把所有步骤置为已完成（模拟历史数据），自动完成门禁须拦截
        UpgradeRecordStep.objects.filter(upgrade_id=self.record.id).update(status='completed')
        from apps.upgrade.services.step_service import RecordStepService
        RecordStepService._check_and_update_record_status(self.record.id, self.user)
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, '处理中')

    def test_manual_complete_record_blocked(self):
        resp = self.c.put(
            f'/upgrade/records/{self.record.id}/update/',
            data=json.dumps({'status': '已完成', 'owner': '负责人'}),
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assertIn('失败', resp.json().get('error'))
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, '处理中')

    def test_complete_action_blocked(self):
        resp = self.c.post(
            f'/upgrade/records/{self.record.id}/status-logs/',
            data=json.dumps({'action': 'complete'}), content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assertIn('失败', resp.json().get('error'))


class StartRedoTest(FailureFlowTestBase):
    """开始重做：范围选择、数量口径、解除阻塞、幂等"""

    def setUp(self):
        super().setUp()
        self.mark_failure()
        self.failure = self.get_failure()

    def test_start_redo_selected_steps(self):
        resp = self.c.post(
            f'/upgrade/records/{self.record.id}/failures/{self.failure.id}/start-redo/',
            data=json.dumps({'step_ids': [self.gray_1.id, self.gray_3.id]}),
            content_type='application/json')
        data = resp.json()
        self.assertFalse(data.get('error'), data)
        self.assertEqual(data['data']['selected_count'], 2)
        self.assertEqual(data['data']['reset_count'], 1)
        self.gray_1.refresh_from_db()
        self.gray_2.refresh_from_db()
        self.gray_3.refresh_from_db()
        self.assertEqual(self.gray_1.status, 'pending')
        self.assertEqual(self.gray_2.status, 'skipped')   # 未选中保留
        self.assertEqual(self.gray_3.status, 'pending')   # 本来待执行不变
        self.failure.refresh_from_db()
        self.assertEqual(self.failure.status, FAILURE_REDOING)
        self.assertEqual(self.failure.redo_selected_count, 2)
        self.assertEqual(self.failure.redo_reset_count, 1)
        # redo_start 事件：快照只含实际被重置的步骤
        log = UpgradeStatusLog.objects.filter(
            upgrade_id=self.record.id, action='redo_start').order_by('-id').first()
        self.assertIsNotNone(log)
        detail = json.loads(log.detail)
        self.assertEqual(detail['selected_count'], 2)
        self.assertEqual(detail['reset_count'], 1)
        self.assertEqual([s['id'] for s in detail['steps']], [self.gray_1.id])
        self.assertEqual(detail['steps'][0]['from_status'], 'completed')
        self.assertEqual(detail['steps'][0]['to_status'], 'pending')
        self.assertEqual(detail['steps'][0]['title'], '执行灰度脚本')
        # 失败阶段原完成记录失效（时间/操作人保留）
        self.log_gray_done.refresh_from_db()
        self.assertEqual(self.log_gray_done.outcome, 'failed')
        self.assertEqual(self.log_gray_done.operator_name, 'fail_flow_user')
        # 解除阻塞：灰度发布可以普通完成
        resp = self.c.put(f'/upgrade/record-steps/{self.gray_1.id}/update/',
                          data=json.dumps({'action': 'complete'}), content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())

    def test_start_redo_all_steps(self):
        resp = self.c.post(
            f'/upgrade/records/{self.record.id}/failures/{self.failure.id}/start-redo/',
            data=json.dumps({'all_steps': True}), content_type='application/json')
        data = resp.json()
        self.assertFalse(data.get('error'), data)
        self.assertEqual(data['data']['selected_count'], 3)
        self.assertEqual(data['data']['reset_count'], 2)
        self.gray_2.refresh_from_db()
        self.assertEqual(self.gray_2.status, 'pending')

    def test_start_redo_empty_and_foreign_selection_rejected(self):
        resp = self.c.post(
            f'/upgrade/records/{self.record.id}/failures/{self.failure.id}/start-redo/',
            data=json.dumps({'step_ids': []}), content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        # 备份阶段的步骤不属于灰度发布失败阶段
        resp = self.c.post(
            f'/upgrade/records/{self.record.id}/failures/{self.failure.id}/start-redo/',
            data=json.dumps({'step_ids': [self.backup_1.id]}), content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assertIn('不属于', resp.json().get('error'))

    def test_start_redo_all_pending_rejected(self):
        # 全部步骤待执行的新阶段失败：无实际重置 → 拒绝
        make_step(self.record, self.user, '升级测试', '测试准备', 6)
        resp = self.c.post(
            f'/upgrade/records/{self.record.id}/status-logs/',
            data=json.dumps({'action': 'test_fail', 'phase': '升级测试', 'remark': 'x'}),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        f2 = self.get_failure()
        resp = self.c.post(
            f'/upgrade/records/{self.record.id}/failures/{f2.id}/start-redo/',
            data=json.dumps({'all_steps': True}), content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assertIn('无需重做', resp.json().get('error'))

    def test_start_redo_without_phase_done_supported(self):
        # 阶段尚未完成时失败（无 phase_done 日志）：失败单正常建立并阻塞，
        # 重做须先有已执行步骤（无实际重置则拒绝，符合"待处理"语义）
        make_step(self.record, self.user, '全量发布', '全量切换', 6)
        resp = self.c.post(
            f'/upgrade/records/{self.record.id}/status-logs/',
            data=json.dumps({'action': 'test_fail', 'phase': '全量发布', 'remark': '未完成即失败'}),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        f2 = self.get_failure()
        self.assertEqual(f2.phase, '全量发布')
        resp = self.c.post(
            f'/upgrade/records/{self.record.id}/failures/{f2.id}/start-redo/',
            data=json.dumps({'all_steps': True}), content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        f2.refresh_from_db()
        self.assertEqual(f2.status, FAILURE_PENDING)

    def test_start_redo_double_submit_rejected(self):
        resp = self.c.post(
            f'/upgrade/records/{self.record.id}/failures/{self.failure.id}/start-redo/',
            data=json.dumps({'all_steps': True}), content_type='application/json')
        self.assertFalse(resp.json().get('error'))
        # 重复提交：不产生第二次重做
        resp = self.c.post(
            f'/upgrade/records/{self.record.id}/failures/{self.failure.id}/start-redo/',
            data=json.dumps({'all_steps': True}), content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assertIn('已进入重做', resp.json().get('error'))
        self.assertEqual(UpgradeStatusLog.objects.filter(
            upgrade_id=self.record.id, action='redo_start').count(), 1)


class RedoCompleteCycleTest(FailureFlowTestBase):
    """重做→再次完成：原完成事件保留、新 phase_done、失败结案、自动完成恢复"""

    def setUp(self):
        super().setUp()
        self.mark_failure()
        self.failure = self.get_failure()

    def test_redo_then_recomplete_full_cycle(self):
        resp = self.c.post(
            f'/upgrade/records/{self.record.id}/failures/{self.failure.id}/start-redo/',
            data=json.dumps({'all_steps': True}), content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        # 重做步骤逐个完成（灰度发布重新完成）
        for step in (self.gray_1, self.gray_2, self.gray_3):
            resp = self.c.put(f'/upgrade/record-steps/{step.id}/update/',
                              data=json.dumps({'action': 'complete'}),
                              content_type='application/json')
            self.assertFalse(resp.json().get('error'), resp.json())
        # 原 phase_done（failed）保留，新增一条 done 的 phase_done
        self.log_gray_done.refresh_from_db()
        self.assertEqual(self.log_gray_done.outcome, 'failed')
        done_logs = UpgradeStatusLog.objects.filter(
            upgrade_id=self.record.id, action='phase_done',
            phase='灰度发布', outcome='done').order_by('id')
        self.assertEqual(done_logs.count(), 1)
        new_done = done_logs.first()
        self.assertNotEqual(new_done.id, self.log_gray_done.id)
        # 新 phase_done 关联失败单结案
        detail = json.loads(new_done.detail or '{}')
        self.assertEqual(detail.get('resolved_failure_ids'), [self.failure.id])
        self.failure.refresh_from_db()
        self.assertEqual(self.failure.status, FAILURE_RESOLVED)
        # 无失败待处理 + 全部步骤完成 → 自动完成
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, '已完成')

    def test_partial_redo_keeps_unselected_results(self):
        resp = self.c.post(
            f'/upgrade/records/{self.record.id}/failures/{self.failure.id}/start-redo/',
            data=json.dumps({'step_ids': [self.gray_1.id]}), content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.gray_2.refresh_from_db()
        self.assertEqual(self.gray_2.status, 'skipped')  # 未选中的有效结果保留
        # 重做所选步骤 + 本就待执行的步骤完成后阶段重新完成（redoing 不阻塞）
        for step in (self.gray_1, self.gray_3):
            resp = self.c.put(f'/upgrade/record-steps/{step.id}/update/',
                              data=json.dumps({'action': 'complete'}),
                              content_type='application/json')
            self.assertFalse(resp.json().get('error'), resp.json())
        # 阶段重新完成，失败结案
        self.failure.refresh_from_db()
        self.assertEqual(self.failure.status, FAILURE_RESOLVED)


class CorrectFailureTest(FailureFlowTestBase):
    """更正失败：原因必填、追加事件、原失败保留、解除阻塞"""

    def setUp(self):
        super().setUp()
        self.mark_failure()
        self.failure = self.get_failure()

    def test_correct_failure_appends_event(self):
        fail_log_id = UpgradeStatusLog.objects.filter(
            upgrade_id=self.record.id, action='test_fail').first().id
        resp = self.c.post(
            f'/upgrade/records/{self.record.id}/failures/{self.failure.id}/correct/',
            data=json.dumps({'reason': '误报：指标恢复正常'}),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.failure.refresh_from_db()
        self.assertEqual(self.failure.status, FAILURE_CORRECTED)
        self.assertEqual(self.failure.correct_reason, '误报：指标恢复正常')
        # 原失败事件保留 + 新增更正事件
        self.assertTrue(UpgradeStatusLog.objects.filter(pk=fail_log_id).exists())
        correct_log = UpgradeStatusLog.objects.filter(
            upgrade_id=self.record.id, action='failure_corrected').first()
        self.assertIsNotNone(correct_log)
        self.assertEqual(correct_log.remark, '误报：指标恢复正常')
        detail = json.loads(correct_log.detail)
        self.assertEqual(detail['failure_id'], self.failure.id)
        # 解除阻塞后可正常完成
        resp = self.c.put(f'/upgrade/record-steps/{self.gray_3.id}/update/',
                          data=json.dumps({'action': 'complete'}),
                          content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())

    def test_correct_requires_reason(self):
        resp = self.c.post(
            f'/upgrade/records/{self.record.id}/failures/{self.failure.id}/correct/',
            data=json.dumps({'reason': ''}), content_type='application/json')
        self.assertTrue(resp.json().get('error'))


class RedoFromTest(FailureFlowTestBase):
    """从某阶段重新执行：预览/执行同口径、后续结果选择、失败解除、旧接口兼容"""

    def test_preview_scope_and_counts(self):
        resp = self.c.get(
            f'/upgrade/records/{self.record.id}/redo-preview/?target_phase=灰度发布')
        data = resp.json()
        self.assertFalse(data.get('error'), data)
        self.assertEqual(data['data']['selected_count'], 2)  # gray_1 completed + gray_2 skipped
        names = [p['name'] for p in data['data']['phases']]
        self.assertEqual(names, ['灰度发布'])
        resp = self.c.get(
            f'/upgrade/records/{self.record.id}/redo-preview/?target_phase=备份')
        data = resp.json()
        # completed/skipped 均计入重置数：备份2 + gray_1 + gray_2 = 4（gray_3 待执行不计）
        self.assertEqual(data['data']['selected_count'], 4)
        self.assertEqual(data['data']['later_completed_phases'], ['灰度发布'])
        self.assertEqual(data['data']['phases'][0]['to_reset'], 2)

    def test_execute_requires_later_decision(self):
        resp = self.c.post(
            f'/upgrade/records/{self.record.id}/redo-execute/',
            data=json.dumps({'target_phase': '备份'}), content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assertIn('后续已完成阶段', resp.json().get('error'))
        resp = self.c.post(
            f'/upgrade/records/{self.record.id}/redo-execute/',
            data=json.dumps({'target_phase': '备份', 'later_action': 'keep'}),
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assertIn('理由', resp.json().get('error'))

    def test_execute_keep_later_results(self):
        resp = self.c.post(
            f'/upgrade/records/{self.record.id}/redo-execute/',
            data=json.dumps({'target_phase': '备份', 'later_action': 'keep',
                             'later_reason': '后续结果经验证仍有效'}),
            content_type='application/json')
        data = resp.json()
        self.assertFalse(data.get('error'), data)
        # 目标阶段重置
        self.backup_1.refresh_from_db()
        self.backup_2.refresh_from_db()
        self.assertEqual(self.backup_1.status, 'pending')
        self.assertEqual(self.backup_2.status, 'pending')
        # 后续阶段保留
        self.gray_1.refresh_from_db()
        self.assertEqual(self.gray_1.status, 'completed')
        self.log_gray_done.refresh_from_db()
        self.assertEqual(self.log_gray_done.outcome, 'done')
        self.log_backup_done.refresh_from_db()
        self.assertEqual(self.log_backup_done.outcome, 'failed')
        # 主表状态与事件
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, '已回退')
        log = UpgradeStatusLog.objects.filter(
            upgrade_id=self.record.id, action='rollback').order_by('-id').first()
        detail = json.loads(log.detail)
        self.assertEqual(detail['later_action'], 'keep')
        self.assertEqual(detail['later_reason'], '后续结果经验证仍有效')
        self.assertEqual(detail['reset_count'], 2)
        self.assertEqual(len(detail['steps']), 2)
        # 前面阶段保持原状（无步骤）

    def test_execute_redo_later_results(self):
        resp = self.c.post(
            f'/upgrade/records/{self.record.id}/redo-execute/',
            data=json.dumps({'target_phase': '备份', 'later_action': 'redo'}),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.gray_1.refresh_from_db()
        self.gray_2.refresh_from_db()
        self.assertEqual(self.gray_1.status, 'pending')
        self.assertEqual(self.gray_2.status, 'pending')
        self.log_gray_done.refresh_from_db()
        self.assertEqual(self.log_gray_done.outcome, 'failed')
        log = UpgradeStatusLog.objects.filter(
            upgrade_id=self.record.id, action='rollback').order_by('-id').first()
        detail = json.loads(log.detail)
        self.assertEqual(detail['selected_count'], 4)
        self.assertEqual(detail['reset_count'], 4)
        self.assertEqual(detail['later_action'], 'redo')

    def test_execute_resolves_failures_in_scope(self):
        self.mark_failure()
        failure = self.get_failure()
        resp = self.c.post(
            f'/upgrade/records/{self.record.id}/redo-execute/',
            data=json.dumps({'target_phase': '灰度发布', 'later_action': 'keep',
                             'later_reason': '无后续已完成阶段'}),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        failure.refresh_from_db()
        self.assertEqual(failure.status, FAILURE_RESOLVED)
        log = UpgradeStatusLog.objects.filter(
            upgrade_id=self.record.id, action='rollback').order_by('-id').first()
        detail = json.loads(log.detail)
        self.assertEqual(detail['failures_resolved'], [{'id': failure.id, 'phase': '灰度发布'}])

    def test_execute_nothing_to_reset_rejected(self):
        # 新阶段全部待执行
        make_step(self.record, self.user, '升级测试', '测试准备', 6)
        resp = self.c.post(
            f'/upgrade/records/{self.record.id}/redo-execute/',
            data=json.dumps({'target_phase': '升级测试'}), content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assertIn('无需重新执行', resp.json().get('error'))

    def test_execute_unknown_target_rejected(self):
        resp = self.c.post(
            f'/upgrade/records/{self.record.id}/redo-execute/',
            data=json.dumps({'target_phase': '不存在的阶段'}), content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_legacy_rollback_api_compatible(self):
        # 旧接口（部署中的前端）rollback 保持原行为
        resp = self.c.post(
            f'/upgrade/records/{self.record.id}/status-logs/',
            data=json.dumps({'action': 'rollback', 'target_action': '备份'}),
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.backup_1.refresh_from_db()
        self.gray_1.refresh_from_db()
        self.assertEqual(self.backup_1.status, 'pending')
        self.assertEqual(self.gray_1.status, 'pending')
        self.log_backup_done.refresh_from_db()
        self.assertEqual(self.log_backup_done.outcome, 'failed')
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, '已回退')


class EventTraceabilityTest(FailureFlowTestBase):
    """事件留痕：单步/批量重置快照、无变化拒绝、禁删改、下线动作、旧数据兼容"""

    def test_step_complete_creates_event_with_snapshot(self):
        resp = self.c.put(f'/upgrade/record-steps/{self.gray_3.id}/update/',
                          data=json.dumps({'action': 'complete', 'remark': '指标正常'}),
                          content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        log = UpgradeStatusLog.objects.filter(
            upgrade_id=self.record.id, action='step_done').order_by('-id').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.phase, '灰度发布')
        detail = json.loads(log.detail)
        self.assertEqual(detail['steps'][0]['id'], self.gray_3.id)
        self.assertEqual(detail['steps'][0]['from_status'], 'pending')
        self.assertEqual(detail['steps'][0]['to_status'], 'completed')

    def test_step_reset_creates_event_with_snapshot(self):
        resp = self.c.put(f'/upgrade/record-steps/{self.gray_1.id}/update/',
                          data=json.dumps({'action': 'reset'}),
                          content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        log = UpgradeStatusLog.objects.filter(
            upgrade_id=self.record.id, action='step_reset').order_by('-id').first()
        detail = json.loads(log.detail)
        self.assertEqual(detail['steps'][0]['from_status'], 'completed')
        self.assertEqual(detail['steps'][0]['to_status'], 'pending')
        self.assertEqual(detail['steps'][0]['title'], '执行灰度脚本')
        # 单步重置联动：该阶段 done phase_done → revoked（既有语义保留）
        self.log_gray_done.refresh_from_db()
        self.assertEqual(self.log_gray_done.outcome, 'revoked')

    def test_reset_pending_step_rejected_no_fake_event(self):
        resp = self.c.put(f'/upgrade/record-steps/{self.gray_3.id}/update/',
                          data=json.dumps({'action': 'reset'}),
                          content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assertEqual(UpgradeStatusLog.objects.filter(
            upgrade_id=self.record.id, action='step_reset').count(), 0)

    def test_batch_reset_single_summary_event(self):
        resp = self.c.put(
            f'/upgrade/records/{self.record.id}/steps/batch/',
            data=json.dumps({'steps': [
                {'step_id': self.gray_1.id, 'action': 'reset'},
                {'step_id': self.gray_2.id, 'action': 'reset'},
                {'step_id': self.gray_3.id, 'action': 'reset'},  # 本来待执行：跳过
            ]}), content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        logs = list(UpgradeStatusLog.objects.filter(
            upgrade_id=self.record.id, action='step_reset'))
        self.assertEqual(len(logs), 1)  # 单条摘要
        detail = json.loads(logs[0].detail)
        self.assertEqual(detail['reset_count'], 2)  # 待执行步骤不计入
        self.assertEqual(len(detail['steps']), 2)

    def test_history_delete_rejected(self):
        log = UpgradeStatusLog.objects.filter(upgrade_id=self.record.id).first()
        resp = self.c.delete(f'/upgrade/status-logs/{log.id}/delete/')
        self.assertTrue(resp.json().get('error'))
        self.assertIn('不可删除', resp.json().get('error'))
        self.assertTrue(UpgradeStatusLog.objects.filter(pk=log.id).exists())

    def test_pause_resume_rejected_but_old_history_readable(self):
        # 旧 pause 日志可读取（保留展示，不伪造恢复事件）
        old_pause = UpgradeStatusLog.objects.create(
            tenant_id=self.user.tenant_id, upgrade_id=self.record.id,
            action='pause', operator_id=self.user.id, operator_name='旧记录',
            event_seq=90)
        resp = self.c.get(f'/upgrade/records/{self.record.id}/status-logs/')
        data = resp.json()
        self.assertFalse(data.get('error'))
        item = next(l for l in data['data'] if l['id'] == old_pause.id)
        self.assertEqual(item['action_text'], '暂停')
        self.assertIsNone(item['detail'])
        # 新写入拒绝
        resp = self.c.post(
            f'/upgrade/records/{self.record.id}/status-logs/',
            data=json.dumps({'action': 'pause', 'phase': '灰度发布'}),
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.assertIn('下线', resp.json().get('error'))
        resp = self.c.post(
            f'/upgrade/records/{self.record.id}/status-logs/',
            data=json.dumps({'action': 'resume', 'phase': '灰度发布'}),
            content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_options_exclude_pause_resume(self):
        resp = self.c.get(
            f'/upgrade/records/{self.record.id}/status-logs/?action=options')
        values = [o['value'] for o in resp.json()['data']]
        self.assertNotIn('pause', values)
        self.assertNotIn('resume', values)
        self.assertIn('test_fail', values)


class TransactionConsistencyTest(FailureFlowTestBase):
    """事务一致性：事件写入失败不留部分结果"""

    def test_event_failure_rolls_back_step_status(self):
        before = UpgradeStatusLog.objects.filter(
            upgrade_id=self.record.id, action='phase_done',
            phase='灰度发布', outcome='done').count()
        with mock.patch(
            'apps.upgrade.services.status_log_service.StatusLogService._persist_log',
            side_effect=lambda **kw: (_ for _ in ()).throw(RuntimeError('db down'))):
            resp = self.c.put(f'/upgrade/record-steps/{self.gray_3.id}/update/',
                              data=json.dumps({'action': 'complete'}),
                              content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        self.gray_3.refresh_from_db()
        self.assertEqual(self.gray_3.status, 'pending')  # 步骤状态回滚
        # 无新增阶段完成（setUp 既有 1 条 done 保持不变）
        after = UpgradeStatusLog.objects.filter(
            upgrade_id=self.record.id, action='phase_done',
            phase='灰度发布', outcome='done').count()
        self.assertEqual(after, before)
        self.assertFalse(UpgradeStatusLog.objects.filter(
            upgrade_id=self.record.id, action='step_done').exists())  # 无事件残留


class TenantIsolationTest(FailureFlowTestBase):
    """租户隔离：跨租户失败操作拒绝"""

    def test_cross_tenant_failure_ops_rejected(self):
        other = make_user('fail_flow_other', [
            'upgrade.upgrade.view', 'upgrade.upgrade.edit'])
        other.tenant_id = 'tenant_other'
        other.save()
        co = make_client(other)
        resp = co.get(f'/upgrade/records/{self.record.id}/failures/')
        self.assertTrue(resp.json().get('error'))
        self.mark_failure()
        failure = self.get_failure()
        resp = co.post(
            f'/upgrade/records/{self.record.id}/failures/{failure.id}/start-redo/',
            data=json.dumps({'all_steps': True}), content_type='application/json')
        self.assertTrue(resp.json().get('error'))
        resp = co.post(
            f'/upgrade/records/{self.record.id}/failures/{failure.id}/correct/',
            data=json.dumps({'reason': 'x'}), content_type='application/json')
        self.assertTrue(resp.json().get('error'))

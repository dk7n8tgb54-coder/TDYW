# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""协作任务模块异常测试

覆盖创建/编辑/催办/退回各入口的参数校验与业务错误分支：
- 标题（缺失/空白/超长/边界 200 字）
- 截止时间（缺失/空串/非法格式/纯日期格式放行）
- 材料清单（缺参/非 JSON/元素非字典/名称空白/名称超长/说明截断）
- 交付对象（空对象/非法 user_id/停用与已删除账号）
- 退回原因（缺失/超长/边界 500 字）、催办（缺参/跨任务分派/已结束任务）
- 校验失败一律不产生数据库写入
"""
import json

from django.utils import timezone

from apps.account.models import User
from apps.coop_task.models import CoopTask, CoopTaskAssignment, CoopTaskDelivery

from apps.coop_task.tests.test_coop_task import (
    CoopTaskFlowTestsBase, _make_user,
)


class TaskCreateValidationTests(CoopTaskFlowTestsBase):
    """创建任务：标题 / 截止时间 / 材料 / 交付对象校验"""

    def _post(self, payload):
        return self.initiator_client.post(
            '/coop-task/tasks/', payload, content_type='application/json')

    def test_title_missing_and_blank_rejected(self):
        """标题缺失与纯空白均被拒绝，且不落库"""
        payload = self._create_payload()
        del payload['title']
        self.assertIn('请输入任务标题', self._post(payload).json().get('error', ''))
        payload = self._create_payload()
        payload['title'] = '   '
        self.assertIn('请输入任务标题', self._post(payload).json().get('error', ''))
        self.assertEqual(CoopTask.objects.count(), 0)

    def test_title_over_max_rejected(self):
        payload = self._create_payload()
        payload['title'] = '标' * 201
        self.assertIn('200', self._post(payload).json().get('error', ''))
        self.assertEqual(CoopTask.objects.count(), 0)

    def test_title_exactly_200_accepted(self):
        """边界：200 字标题合法"""
        payload = self._create_payload()
        payload['title'] = '标' * 200
        resp = self._post(payload)
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertEqual(CoopTask.objects.get(pk=resp.json()['data']['id']).title, '标' * 200)

    def test_deadline_missing_or_blank_rejected(self):
        """截止时间缺失与空串在参数层被拒绝"""
        for payload in (self._create_payload(),):
            del payload['deadline']
            self.assertIn('截止时间', self._post(payload).json().get('error', ''))
        payload = self._create_payload()
        payload['deadline'] = ''
        self.assertIn('截止时间', self._post(payload).json().get('error', ''))
        self.assertEqual(CoopTask.objects.count(), 0)

    def test_deadline_bad_formats_rejected(self):
        for bad in ('2026/09/30', '2026-13-01 08:00', '2026-09-30 25:00', 'not-a-date'):
            payload = self._create_payload()
            payload['deadline'] = bad
            self.assertIn('截止时间格式错误', self._post(payload).json().get('error', ''), bad)
        self.assertEqual(CoopTask.objects.count(), 0)

    def test_deadline_date_only_accepted(self):
        """回归：纯日期 'YYYY-MM-DD' 是支持的第三种格式"""
        payload = self._create_payload()
        payload['deadline'] = '2026-09-30'
        resp = self._post(payload)
        self.assertFalse(resp.json().get('error'), resp.json())
        task = CoopTask.objects.get(pk=resp.json()['data']['id'])
        self.assertEqual(task.deadline.strftime('%Y-%m-%d %H:%M:%S'), '2026-09-30 00:00:00')

    def test_items_empty_and_malformed_rejected(self):
        """items 缺参/空串/非法 JSON 均在参数层被拒绝"""
        payload = self._create_payload()
        del payload['items']
        self.assertIn('材料', self._post(payload).json().get('error', ''))
        payload = self._create_payload()
        payload['items'] = ''
        self.assertIn('材料', self._post(payload).json().get('error', ''))
        payload = self._create_payload()
        payload['items'] = 'not-a-json-array'
        self.assertIn('材料', self._post(payload).json().get('error', ''))
        self.assertEqual(CoopTask.objects.count(), 0)

    def test_items_invalid_entries_rejected(self):
        """材料元素非字典/名称空白/名称超长均被拒绝"""
        cases = [
            (['不是字典'], '格式不正确'),
            ([{'name': ''}], '名称不能为空'),
            ([{'name': '  '}], '名称不能为空'),
            ([{'name': '材' * 201}], '名称过长'),
        ]
        for items, keyword in cases:
            payload = self._create_payload()
            payload['items'] = items
            self.assertIn(keyword, self._post(payload).json().get('error', ''), items)
        self.assertEqual(CoopTask.objects.count(), 0)

    def test_items_remark_over_500_truncated(self):
        """说明超过 500 字截断保存而非拒绝"""
        payload = self._create_payload()
        payload['items'] = [{'name': '正常材料', 'remark': '要求' * 300}]
        resp = self._post(payload)
        self.assertFalse(resp.json().get('error'), resp.json())
        item = CoopTask.objects.get(pk=resp.json()['data']['id']).items.first()
        self.assertEqual(len(item.remark), 500)

    def test_targets_invalid_entries_rejected(self):
        """交付对象：空串/缺 tenant_id 与 user_id/非法 user_id 均被拒绝"""
        cases = [
            ([''], '格式不正确'),
            ([{'contact_user_name': '李四'}], '格式不正确'),
            ([{'tenant_id': '   '}], '格式不正确'),
            ([{'user_id': 'abc'}], '格式不正确'),
        ]
        for targets, keyword in cases:
            payload = self._create_payload()
            payload['targets'] = targets
            self.assertIn(keyword, self._post(payload).json().get('error', ''), targets)
        self.assertEqual(CoopTask.objects.count(), 0)

    def test_targets_inactive_user_rejected(self):
        """已停用账号不能作为交付对象"""
        inactive = _make_user('val_inactive', tenant_id=str(self.tenant_b.id), is_active=False)
        payload = self._create_payload()
        payload['targets'] = [{'user_id': inactive.id}]
        self.assertIn('不存在或已停用', self._post(payload).json().get('error', ''))
        self.assertEqual(CoopTask.objects.count(), 0)

    def test_targets_deleted_user_rejected(self):
        """已删除账号不能作为交付对象"""
        user = _make_user('val_deleted', tenant_id=str(self.tenant_b.id))
        user.deleted_at = timezone.now()
        user.save(update_fields=['deleted_at'])
        payload = self._create_payload()
        payload['targets'] = [{'user_id': user.id}]
        self.assertIn('不存在或已停用', self._post(payload).json().get('error', ''))
        self.assertEqual(CoopTask.objects.count(), 0)


class TaskEditValidationTests(CoopTaskFlowTestsBase):
    """编辑任务：非法输入 / 不存在 / 已结束任务"""

    def setUp(self):
        data = self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        self.task_id = data['id']

    def _edit(self, payload, task_id=None):
        return self.initiator_client.post(
            f'/coop-task/tasks/{task_id or self.task_id}/', payload,
            content_type='application/json')

    def test_edit_blank_title_rejected(self):
        resp = self._edit({'title': '  ', 'deadline': '2026-10-15 09:00'})
        self.assertIn('请输入任务标题', resp.json().get('error', ''))
        self.assertEqual(CoopTask.objects.get(pk=self.task_id).title, '征集5月工作台账')

    def test_edit_title_over_max_rejected(self):
        resp = self._edit({'title': '标' * 201, 'deadline': '2026-10-15 09:00'})
        self.assertIn('200', resp.json().get('error', ''))
        self.assertEqual(CoopTask.objects.get(pk=self.task_id).title, '征集5月工作台账')

    def test_edit_bad_deadline_rejected(self):
        resp = self._edit({'title': '新标题', 'deadline': '2026/09/30'})
        self.assertIn('截止时间格式错误', resp.json().get('error', ''))
        self.assertEqual(CoopTask.objects.get(pk=self.task_id).title, '征集5月工作台账')

    def test_edit_missing_field_rejected(self):
        """缺标题参数在参数层被拒绝"""
        resp = self._edit({'deadline': '2026-10-15 09:00'})
        self.assertIn('请输入任务标题', resp.json().get('error', ''))

    def test_edit_nonexistent_task_rejected(self):
        resp = self._edit({'title': 'x', 'deadline': '2026-10-15 09:00'}, task_id=999999)
        self.assertIn('任务不存在', resp.json().get('error', ''))

    def test_edit_completed_task_rejected(self):
        """已完成任务不允许编辑"""
        for delivery in CoopTaskDelivery.objects.filter(assignment__task_id=self.task_id):
            self.deliverer_b_client.post(f'/coop-task/deliveries/{delivery.id}/submit/')
            self.initiator_client.post(f'/coop-task/deliveries/{delivery.id}/accept/')
        resp = self._edit({'title': '再改', 'deadline': '2026-10-15 09:00'})
        self.assertIn('仅进行中的任务可以编辑', resp.json().get('error', ''))
        self.assertEqual(CoopTask.objects.get(pk=self.task_id).title, '征集5月工作台账')


class RejectValidationTests(CoopTaskFlowTestsBase):
    """退回原因校验"""

    def setUp(self):
        data = self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        self.task_id = data['id']
        self.delivery = CoopTaskDelivery.objects.filter(assignment__task_id=self.task_id).first()
        self.deliverer_b_client.post(f'/coop-task/deliveries/{self.delivery.id}/submit/')

    def _reject(self, payload, delivery_id=None):
        return self.initiator_client.post(
            f'/coop-task/deliveries/{delivery_id or self.delivery.id}/reject/', payload,
            content_type='application/json')

    def test_reason_missing_rejected(self):
        resp = self._reject({})
        self.assertIn('请填写退回原因', resp.json().get('error', ''))
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, 'submitted')

    def test_reason_over_max_rejected(self):
        resp = self._reject({'reason': '退' * 501})
        self.assertIn('500', resp.json().get('error', ''))
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, 'submitted')

    def test_reason_exactly_500_accepted(self):
        """边界：500 字退回原因合法落库"""
        resp = self._reject({'reason': '退' * 500})
        self.assertFalse(resp.json().get('error'), resp.json())
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, 'rejected')
        self.assertEqual(len(self.delivery.reject_reason), 500)


class UrgeValidationTests(CoopTaskFlowTestsBase):
    """催办参数校验"""

    def setUp(self):
        data = self._create_task()
        self.task_id = data['id']
        self.assignment_b = CoopTaskAssignment.objects.get(
            task_id=self.task_id, target_tenant_id=str(self.tenant_b.id))

    def _urge(self, payload, task_id=None):
        return self.initiator_client.post(
            f'/coop-task/tasks/{task_id or self.task_id}/urge/', payload,
            content_type='application/json')

    def test_assignment_id_missing_rejected(self):
        resp = self._urge({})
        self.assertIn('请指定催办科室', resp.json().get('error', ''))
        self.assignment_b.refresh_from_db()
        self.assertEqual(self.assignment_b.urge_count, 0)

    def test_assignment_from_other_task_rejected(self):
        """催办其他任务的分派被拒绝"""
        other = self._create_task()
        other_assignment = CoopTaskAssignment.objects.get(
            task_id=other['id'], target_tenant_id=str(self.tenant_b.id))
        resp = self._urge({'assignment_id': other_assignment.id})
        self.assertIn('分派记录不存在', resp.json().get('error', ''))
        other_assignment.refresh_from_db()
        self.assertEqual(other_assignment.urge_count, 0)

    def test_urge_voided_task_rejected(self):
        self.initiator_client.post(f'/coop-task/tasks/{self.task_id}/void/')
        resp = self._urge({'assignment_id': self.assignment_b.id})
        self.assertIn('任务已结束，无需催办', resp.json().get('error', ''))
        self.assignment_b.refresh_from_db()
        self.assertEqual(self.assignment_b.urge_count, 0)

    def test_urge_nonexistent_assignment_rejected(self):
        resp = self._urge({'assignment_id': 999999})
        self.assertIn('分派记录不存在', resp.json().get('error', ''))

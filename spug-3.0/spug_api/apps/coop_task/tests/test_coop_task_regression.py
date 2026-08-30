# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""协作任务模块回归测试

固化关键业务不变量，防止后续重构破坏：
- compute_assignment_status 聚合优先级真值表（全待交付 > 有退回 > 全部验收 > 无待交付 > 部分交付）
- 任务列表进度汇总、分页/关键字/状态过滤
- 收件箱排序（新任务在前）与作废/软删除任务过滤；交付明细按材料排序
- 角标随任务作废/删除归零；催办未读不统计已作废任务
- 逾期标记：过期进行中任务标记、完成任务不再标记
- 自动完成任务需全部科室全部材料验收通过
- 旧格式（纯租户ID字符串）交付对象兼容
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.coop_task.models import (
    CoopTask, CoopTaskAssignment, CoopTaskDelivery,
    compute_assignment_status,
    ASSIGNMENT_PENDING, ASSIGNMENT_PARTIAL, ASSIGNMENT_SUBMITTED,
    ASSIGNMENT_REJECTED, ASSIGNMENT_ACCEPTED,
)

from apps.coop_task.tests.test_coop_task import CoopTaskFlowTestsBase


class AssignmentStatusTruthTableTests(TestCase):
    """compute_assignment_status 聚合优先级回归真值表"""

    def test_truth_table(self):
        cases = [
            # (total, accepted, rejected, pending, expected)
            (0, 0, 0, 0, ASSIGNMENT_PENDING),      # 无明细视为待交付
            (3, 0, 0, 3, ASSIGNMENT_PENDING),      # 全部待交付
            (3, 0, 1, 1, ASSIGNMENT_REJECTED),     # 有退回优先于待交付
            (3, 2, 1, 0, ASSIGNMENT_REJECTED),     # 有退回优先于其余已提交
            (3, 3, 0, 0, ASSIGNMENT_ACCEPTED),     # 全部验收
            (3, 0, 0, 0, ASSIGNMENT_SUBMITTED),    # 无待交付且未全验收 => 待验收
            (3, 1, 0, 1, ASSIGNMENT_PARTIAL),      # 部分验收仍有待交付
            (3, 1, 0, 2, ASSIGNMENT_PARTIAL),      # 部分提交
        ]
        for total, accepted, rejected, pending, expected in cases:
            self.assertEqual(
                compute_assignment_status(total, accepted, rejected, pending),
                expected,
                (total, accepted, rejected, pending))


class TaskListRegressionTests(CoopTaskFlowTestsBase):
    """任务列表：进度汇总 / 分页 / 过滤"""

    def test_progress_aggregation_sums_across_assignments(self):
        """进度 = 全部科室交付明细的汇总计数"""
        data = self._create_task()
        assignment_b = CoopTaskAssignment.objects.get(
            task_id=data['id'], target_tenant_id=str(self.tenant_b.id))
        deliveries = list(CoopTaskDelivery.objects.filter(
            assignment_id=assignment_b.id).order_by('id'))
        self.deliverer_b_client.post(f'/coop-task/deliveries/{deliveries[0].id}/submit/')
        self.initiator_client.post(f'/coop-task/deliveries/{deliveries[0].id}/accept/')
        self.deliverer_b_client.post(f'/coop-task/deliveries/{deliveries[1].id}/submit/')
        resp = self.initiator_client.get('/coop-task/tasks/')
        row = [x for x in resp.json()['data']['results'] if x['id'] == data['id']][0]
        self.assertEqual(row['progress'], {
            'total': 4, 'accepted': 1, 'submitted': 1, 'rejected': 0, 'pending': 2})

    def test_pagination_and_filters(self):
        ids = [self._create_task()['id'] for _ in range(3)]
        resp = self.initiator_client.get('/coop-task/tasks/?page_size=2&page=1')
        body = resp.json()['data']
        self.assertEqual(body['total'], 3)
        self.assertEqual(len(body['results']), 2)
        resp = self.initiator_client.get('/coop-task/tasks/?page_size=2&page=2')
        self.assertEqual(len(resp.json()['data']['results']), 1)
        # 关键字命中标题
        keyword = '征集5月工作台账'
        resp = self.initiator_client.get(f'/coop-task/tasks/?keyword={keyword}')
        self.assertEqual(resp.json()['data']['total'], 3)
        # 状态过滤
        resp = self.initiator_client.get('/coop-task/tasks/?status=in_progress')
        self.assertEqual(resp.json()['data']['total'], 3)
        resp = self.initiator_client.get('/coop-task/tasks/?status=completed')
        self.assertEqual(resp.json()['data']['total'], 0)
        self.assertTrue(CoopTask.objects.filter(pk=ids[0]).exists())

    def test_deleted_task_excluded_from_own_list(self):
        data = self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        self.initiator_client.delete(f"/coop-task/tasks/{data['id']}/")
        resp = self.initiator_client.get('/coop-task/tasks/')
        self.assertEqual(resp.json()['data']['results'], [])
        resp = self.initiator_client.get(f"/coop-task/tasks/{data['id']}/")
        self.assertTrue(resp.json().get('error'))

    def test_legacy_string_targets_accepted(self):
        """回归：旧格式纯租户ID字符串交付对象仍可用"""
        payload = self._create_payload()
        payload['targets'] = [str(self.tenant_b.id)]
        resp = self.initiator_client.post(
            '/coop-task/tasks/', payload, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        assignment = CoopTaskAssignment.objects.get(task_id=resp.json()['data']['id'])
        self.assertEqual(assignment.target_tenant_id, str(self.tenant_b.id))
        self.assertEqual(assignment.contact_user_id, None)
        self.assertEqual(CoopTaskDelivery.objects.filter(
            assignment=assignment).count(), 2)


class InboxRegressionTests(CoopTaskFlowTestsBase):
    """收件箱：排序 / 过滤 / 详情顺序"""

    def _make_single_target_task(self):
        return self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])

    def test_inbox_order_newest_first_and_exclusions(self):
        first = self._make_single_target_task()
        second = self._make_single_target_task()
        resp = self.deliverer_b_client.get('/coop-task/inbox/')
        ids = [x['task_id'] for x in resp.json()['data']]
        self.assertEqual(ids, [second['id'], first['id']])
        # 作废最新任务后只剩旧任务
        self.initiator_client.post(f"/coop-task/tasks/{second['id']}/void/")
        resp = self.deliverer_b_client.get('/coop-task/inbox/')
        self.assertEqual(
            [x['task_id'] for x in resp.json()['data']], [first['id']])
        # 软删除旧任务后收件箱清空
        self.initiator_client.delete(f"/coop-task/tasks/{first['id']}/")
        resp = self.deliverer_b_client.get('/coop-task/inbox/')
        self.assertEqual(resp.json()['data'], [])

    def test_inbox_detail_orders_deliveries_by_item_sort_order(self):
        """回归：详情交付明细按材料排序号排列，材料名/说明正确冗余"""
        data = self._make_single_target_task()
        assignment = CoopTaskAssignment.objects.get(task_id=data['id'])
        resp = self.deliverer_b_client.get(f'/coop-task/inbox/{assignment.id}/')
        items = resp.json()['data']['items']
        self.assertEqual([x['item_name'] for x in items], ['工作总结', '设备台账'])
        self.assertEqual(items[0]['item_remark'], 'Word格式')
        self.assertEqual(items[1]['item_remark'], 'Excel格式')


class BadgeRegressionTests(CoopTaskFlowTestsBase):
    """角标随任务状态变化"""

    def test_badge_zero_after_void_and_delete(self):
        data = self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        task_id = data['id']
        assignment = CoopTaskAssignment.objects.get(task_id=task_id)
        delivery = CoopTaskDelivery.objects.filter(assignment_id=assignment.id).first()

        # 初始：交付方待处理 1
        badge = self.deliverer_b_client.get('/coop-task/badge/').json()['data']
        self.assertEqual(badge['inbox_pending'], 1)
        # 催办后交付方未读 1，发起方待验收 0
        self.initiator_client.post(
            f'/coop-task/tasks/{task_id}/urge/',
            {'assignment_id': assignment.id}, content_type='application/json')
        badge = self.deliverer_b_client.get('/coop-task/badge/').json()['data']
        self.assertEqual(badge['urge_unread'], 1)
        # 交付方提交后：发起方待验收 1
        self.deliverer_b_client.post(f'/coop-task/deliveries/{delivery.id}/submit/')
        badge = self.initiator_client.get('/coop-task/badge/').json()['data']
        self.assertEqual(badge['accept_pending'], 1)
        # 作废后：双方归零（含催办未读）
        self.initiator_client.post(f'/coop-task/tasks/{task_id}/void/')
        badge = self.deliverer_b_client.get('/coop-task/badge/').json()['data']
        self.assertEqual(badge, {'count': 0, 'inbox_pending': 0,
                                 'accept_pending': 0, 'urge_unread': 0})
        badge = self.initiator_client.get('/coop-task/badge/').json()['data']
        self.assertEqual(badge['accept_pending'], 0)

        # 软删除同样使发起方待验收归零（先重置任务状态不可行，用另一任务验证删除路径）
        data2 = self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        delivery2 = CoopTaskDelivery.objects.filter(
            assignment__task_id=data2['id']).first()
        self.deliverer_b_client.post(f'/coop-task/deliveries/{delivery2.id}/submit/')
        self.assertEqual(
            self.initiator_client.get('/coop-task/badge/').json()['data']['accept_pending'], 1)
        self.initiator_client.delete(f"/coop-task/tasks/{data2['id']}/")
        self.assertEqual(
            self.initiator_client.get('/coop-task/badge/').json()['data']['accept_pending'], 0)


class CompletionRegressionTests(CoopTaskFlowTestsBase):
    """自动完成条件与逾期标记"""

    def test_completion_requires_all_assignments(self):
        """只完成一个科室的全部材料不触发任务完成"""
        data = self._create_task()
        assignment_b = CoopTaskAssignment.objects.get(
            task_id=data['id'], target_tenant_id=str(self.tenant_b.id))
        for delivery in CoopTaskDelivery.objects.filter(assignment_id=assignment_b.id):
            self.deliverer_b_client.post(f'/coop-task/deliveries/{delivery.id}/submit/')
            self.initiator_client.post(f'/coop-task/deliveries/{delivery.id}/accept/')
        task = CoopTask.objects.get(pk=data['id'])
        self.assertEqual(task.status, 'in_progress')
        self.assertIsNone(task.completed_at)
        # 另一科室完成后才触发
        assignment_c = CoopTaskAssignment.objects.get(
            task_id=data['id'], target_tenant_id=str(self.tenant_c.id))
        for delivery in CoopTaskDelivery.objects.filter(assignment_id=assignment_c.id):
            self.deliverer_c_client.post(f'/coop-task/deliveries/{delivery.id}/submit/')
            self.initiator_client.post(f'/coop-task/deliveries/{delivery.id}/accept/')
        task = CoopTask.objects.get(pk=data['id'])
        self.assertEqual(task.status, 'completed')
        self.assertIsNotNone(task.completed_at)

    def test_overdue_flag_lifecycle(self):
        """过期进行中任务标记逾期；完成任务后不再标记"""
        past_payload = self._create_payload()
        past_payload['deadline'] = (
            (timezone.now() - timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S'))
        past_payload['targets'] = [
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}]
        resp = self.initiator_client.post(
            '/coop-task/tasks/', past_payload, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        task_id = resp.json()['data']['id']
        row = self.initiator_client.get('/coop-task/tasks/').json()['data']['results'][0]
        self.assertTrue(row['is_overdue'])
        assignment = CoopTaskAssignment.objects.get(
            task_id=task_id, target_tenant_id=str(self.tenant_b.id))
        inbox = self.deliverer_b_client.get('/coop-task/inbox/').json()['data'][0]
        self.assertTrue(inbox['is_overdue'])
        # 全部验收后不再标记逾期
        for delivery in CoopTaskDelivery.objects.filter(assignment_id=assignment.id):
            self.deliverer_b_client.post(f'/coop-task/deliveries/{delivery.id}/submit/')
            self.initiator_client.post(f'/coop-task/deliveries/{delivery.id}/accept/')
        row = [x for x in self.initiator_client.get(
            '/coop-task/tasks/').json()['data']['results'] if x['id'] == task_id][0]
        self.assertFalse(row['is_overdue'])

    def test_future_deadline_not_overdue(self):
        payload = self._create_payload()
        payload['deadline'] = (
            (timezone.now() + timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S'))
        self.initiator_client.post(
            '/coop-task/tasks/', payload, content_type='application/json')
        row = self.initiator_client.get('/coop-task/tasks/').json()['data']['results'][0]
        self.assertFalse(row['is_overdue'])


class AggregateStatusJourneyTests(CoopTaskFlowTestsBase):
    """单科室聚合状态随交付状态机流转：pending→partial→submitted→rejected→submitted→accepted"""

    def test_aggregate_status_journey(self):
        data = self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        assignment_id = CoopTaskAssignment.objects.get(task_id=data['id']).id
        deliveries = list(CoopTaskDelivery.objects.filter(
            assignment_id=assignment_id).order_by('id'))

        def current_status():
            resp = self.deliverer_b_client.get(f'/coop-task/inbox/{assignment_id}/')
            return resp.json()['data']['aggregate_status']

        self.assertEqual(current_status(), 'pending')
        self.deliverer_b_client.post(f'/coop-task/deliveries/{deliveries[0].id}/submit/')
        self.assertEqual(current_status(), 'partial')
        self.deliverer_b_client.post(f'/coop-task/deliveries/{deliveries[1].id}/submit/')
        self.assertEqual(current_status(), 'submitted')
        self.initiator_client.post(
            f'/coop-task/deliveries/{deliveries[0].id}/reject/',
            {'reason': '重交'}, content_type='application/json')
        self.assertEqual(current_status(), 'rejected')
        self.deliverer_b_client.post(f'/coop-task/deliveries/{deliveries[0].id}/submit/')
        self.assertEqual(current_status(), 'submitted')
        for delivery in deliveries:
            self.initiator_client.post(f'/coop-task/deliveries/{delivery.id}/accept/')
        self.assertEqual(current_status(), 'accepted')
        # 发起方详情页同一聚合口径
        detail = self.initiator_client.get(f"/coop-task/tasks/{data['id']}/").json()['data']
        row = [a for a in detail['assignments'] if a['id'] == assignment_id][0]
        self.assertEqual(row['aggregate_status'], 'accepted')

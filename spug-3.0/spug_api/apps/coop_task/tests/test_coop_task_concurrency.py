# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""协作任务模块并发安全测试

用"检查点注入"确定性复现并发窗口：视图在状态校验之后调用 timezone.now()，
在该检查点把数据库改成并发请求已先行提交的状态，再让视图继续完成写入。
相比双线程竞争，这种方式在真实 HTTP 代码路径上 100% 复现竞态，结果可断言。

- 提交 vs 验收：提交不得把已验收明细覆盖回待验收
- 提交 vs 作废：作废后的任务不得再写入提交状态
- 催办 vs 催办：计数必须数据库原子累加，不得丢失并发更新
"""
from unittest.mock import patch

from django.db.models import F
from django.utils import timezone

from apps.coop_task import views as coop_views
from apps.coop_task.models import CoopTask, CoopTaskAssignment, CoopTaskDelivery
from apps.logs.models import AuditLog

from apps.coop_task.tests.test_coop_task import CoopTaskFlowTestsBase


def _inject_at_now_checkpoint(action):
    """在视图调用 timezone.now() 的检查点注入一次并发数据库副作用

    action 收到未打补丁的 real_now，用于并发侧的时间戳。
    """
    real_now = timezone.now
    state = {'injected': False}

    def fake_now():
        if not state['injected']:
            state['injected'] = True
            action(real_now)
        return real_now()

    return patch.object(coop_views.timezone, 'now', fake_now)


class SubmitConcurrencyTests(CoopTaskFlowTestsBase):
    """交付提交的并发防护"""

    def setUp(self):
        data = self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        self.task_id = data['id']
        self.delivery = CoopTaskDelivery.objects.filter(
            assignment__task_id=self.task_id).first()

    def test_concurrent_accept_not_overwritten_by_submit(self):
        """并发窗口内明细已被验收时，提交必须失败且不得把已验收覆盖回待验收"""
        def concurrent_accept(real_now):
            CoopTaskDelivery.objects.filter(pk=self.delivery.pk).update(
                status='accepted', accepted_at=real_now(),
                accepted_by_id=self.initiator.id, accepted_by_name='initiator')

        with _inject_at_now_checkpoint(concurrent_accept):
            resp = self.deliverer_b_client.post(
                f'/coop-task/deliveries/{self.delivery.id}/submit/')
        self.assertTrue(resp.json().get('error'), resp.json())
        self.assertIn('已验收', resp.json().get('error', ''))
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, 'accepted')

    def test_concurrent_void_blocks_submit(self):
        """并发窗口内任务被作废时，提交必须失败且明细保持待交付"""
        def concurrent_void(real_now):
            CoopTask.objects.filter(pk=self.task_id).update(
                status='voided', updated_at=real_now())

        with _inject_at_now_checkpoint(concurrent_void):
            resp = self.deliverer_b_client.post(
                f'/coop-task/deliveries/{self.delivery.id}/submit/')
        self.assertTrue(resp.json().get('error'), resp.json())
        self.assertIn('任务已结束', resp.json().get('error', ''))
        self.delivery.refresh_from_db()
        self.assertEqual(self.delivery.status, 'pending')
        self.assertEqual(CoopTask.objects.get(pk=self.task_id).status, 'voided')


class UrgeConcurrencyTests(CoopTaskFlowTestsBase):
    """催办计数的原子累加"""

    def test_concurrent_urge_count_not_lost(self):
        """并发窗口内另一请求已催办时，计数应累加为 2 而非覆盖为 1"""
        data = self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        assignment = CoopTaskAssignment.objects.get(task_id=data['id'])

        def concurrent_urge(real_now):
            CoopTaskAssignment.objects.filter(pk=assignment.pk).update(
                urge_count=F('urge_count') + 1, last_urged_at=real_now())

        with _inject_at_now_checkpoint(concurrent_urge):
            resp = self.initiator_client.post(
                f"/coop-task/tasks/{data['id']}/urge/",
                {'assignment_id': assignment.id}, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        assignment.refresh_from_db()
        self.assertEqual(assignment.urge_count, 2)


class UrgeStateRaceTests(CoopTaskFlowTestsBase):
    """催办状态检查与递增之间的并发窗口（TOCTOU）

    视图先校验任务进行中，再递增 urge_count 并记录成功审计；
    若校验后、递增前任务被并发作废或软删除，必须放弃递增与成功审计。
    """

    def setUp(self):
        data = self._create_task(targets=[
            {'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        self.task_id = data['id']
        self.assignment = CoopTaskAssignment.objects.get(task_id=self.task_id)

    def _urge(self):
        return self.initiator_client.post(
            f'/coop-task/tasks/{self.task_id}/urge/',
            {'assignment_id': self.assignment.id}, content_type='application/json')

    def _success_urge_audits(self):
        return AuditLog.objects.filter(
            action='update', target_type='coop_task',
            target_id=str(self.task_id), is_success=True).count()

    def test_concurrent_void_blocks_urge(self):
        """并发窗口内任务被作废时，催办不得递增计数、不得记录成功审计"""
        def concurrent_void(real_now):
            CoopTask.objects.filter(pk=self.task_id).update(
                status='voided', updated_at=real_now())

        with _inject_at_now_checkpoint(concurrent_void):
            resp = self._urge()
        self.assertTrue(resp.json().get('error'), resp.json())
        self.assertIn('任务已结束', resp.json().get('error', ''))
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.urge_count, 0)
        self.assertEqual(self.assignment.last_urged_at, None)
        self.assertEqual(self._success_urge_audits(), 0)

    def test_concurrent_soft_delete_blocks_urge(self):
        """并发窗口内任务被软删除时，催办不得递增计数、不得记录成功审计"""
        def concurrent_delete(real_now):
            CoopTask.objects.filter(pk=self.task_id).update(
                is_deleted=True, deleted_at=real_now(),
                deleted_by_id=self.initiator.id)

        with _inject_at_now_checkpoint(concurrent_delete):
            resp = self._urge()
        self.assertTrue(resp.json().get('error'), resp.json())
        self.assertIn('任务不存在', resp.json().get('error', ''))
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.urge_count, 0)
        self.assertEqual(self.assignment.last_urged_at, None)
        self.assertEqual(self._success_urge_audits(), 0)

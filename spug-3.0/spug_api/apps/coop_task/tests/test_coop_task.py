# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""协作任务模块测试

覆盖：创建任务矩阵预生成、CRUD 权限、交付状态机（提交/验收/退回/重交/自动完成）、
跨科室租户隔离、附件可见性与上传方归属、催办与未读、badge、
操作审计联动（record_audit_event 落库且与中间件不重复）。
"""
import json
import tempfile
import time

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client, override_settings

from apps.account.models import User, Role, Tenant
from apps.logs.models import AuditLog
from apps.evidence.models import EvidenceAttachment

from apps.coop_task.models import (
    CoopTask, CoopTaskItem, CoopTaskAssignment, CoopTaskDelivery,
    TASK_STATUS_IN_PROGRESS, TASK_STATUS_COMPLETED, TASK_STATUS_VOIDED,
)


# ============================================================
# 测试辅助
# ============================================================

def _make_user(username, is_supper=False, tenant_id='default', is_active=True):
    token = (username * 10)[:32]
    return User.objects.create(
        username=username, nickname=username, password_hash='x',
        is_active=is_active, is_supper=is_supper, access_token=token,
        token_expired=int(time.time()) + 3600, last_login='2026-01-01',
        # last_ip 置空以匹配测试请求（无 X-Real-IP 头），绕开 IP 绑定校验
        last_ip='', type='default', tenant_id=tenant_id,
    )


def _grant_perms(user, perms):
    """perms: list of (module, page, [perm_keys])"""
    perm_dict = {}
    for module, page, keys in perms:
        perm_dict.setdefault(module, {}).setdefault(page, []).extend(keys)
    role = Role.objects.create(
        name=f'role_{user.username}',
        page_perms=json.dumps(perm_dict),
        created_by=user,
    )
    user.roles.add(role)
    user.set_perms_cache()
    return role


def _make_client(user):
    client = Client()
    client.defaults['HTTP_X_TOKEN'] = user.access_token
    return client


def _coop_perms(*keys):
    return [('coop', 'task', list(keys))]


def _make_tenant(tid, name):
    """Tenant.id 为 CharField 主键，需显式指定"""
    return Tenant.objects.create(id=tid, name=name)


CREATE_PAYLOAD = {
    'title': '征集5月工作台账',
    'description': '请各科室按模板整理',
    'deadline': '2026-09-30 18:00:00',
    'items': [
        {'name': '工作总结', 'remark': 'Word格式'},
        {'name': '设备台账', 'remark': 'Excel格式'},
    ],
    'targets': [
        {'tenant_id': None, 'contact_user_name': '李四'},  # 由 setUp 填充
        {'tenant_id': None, 'contact_user_name': ''},
    ],
}


class CoopTaskFlowTestsBase(TestCase):
    """公共夹具：三个科室 + 发起方 + 无关方 + 超管"""

    @classmethod
    def setUpTestData(cls):
        cls.tenant_a = _make_tenant('t_a', '一科')
        cls.tenant_b = _make_tenant('t_b', '二科')
        cls.tenant_c = _make_tenant('t_c', '三科')
        cls.tenant_x = _make_tenant('t_x', '无关科')

        cls.initiator = _make_user('initiator', tenant_id=str(cls.tenant_a.id))
        _grant_perms(cls.initiator, _coop_perms('view', 'add', 'edit', 'delete', 'accept'))
        cls.deliverer_b = _make_user('deliverer_b', tenant_id=str(cls.tenant_b.id))
        _grant_perms(cls.deliverer_b, _coop_perms('view', 'submit'))
        cls.deliverer_c = _make_user('deliverer_c', tenant_id=str(cls.tenant_c.id))
        _grant_perms(cls.deliverer_c, _coop_perms('view', 'submit'))
        cls.outsider = _make_user('outsider', tenant_id=str(cls.tenant_x.id))
        _grant_perms(cls.outsider, _coop_perms('view', 'submit'))
        cls.plain = _make_user('plain', tenant_id=str(cls.tenant_x.id))
        cls.supper = _make_user('supper', is_supper=True, tenant_id=str(cls.tenant_a.id))

        cls.initiator_client = _make_client(cls.initiator)
        cls.deliverer_b_client = _make_client(cls.deliverer_b)
        cls.deliverer_c_client = _make_client(cls.deliverer_c)
        cls.outsider_client = _make_client(cls.outsider)
        cls.plain_client = _make_client(cls.plain)
        cls.supper_client = _make_client(cls.supper)

    def _create_payload(self):
        payload = json.loads(json.dumps(CREATE_PAYLOAD))
        payload['targets'][0]['tenant_id'] = str(self.tenant_b.id)
        payload['targets'][1]['tenant_id'] = str(self.tenant_c.id)
        return payload

    def _create_task(self, targets=None):
        """以发起方身份创建任务，返回响应中的任务数据"""
        payload = self._create_payload()
        if targets is not None:
            payload['targets'] = targets
        resp = self.initiator_client.post(
            '/coop-task/tasks/', payload, content_type='application/json')
        body = resp.json()
        assert not body.get('error'), body
        return body['data']

    def _get_detail(self, task_id):
        resp = self.initiator_client.get(f'/coop-task/tasks/{task_id}/')
        return resp.json()


# ============================================================
# 创建与权限
# ============================================================

class TaskCreateTests(CoopTaskFlowTestsBase):

    def test_create_generates_full_matrix(self):
        """创建任务后 items/assignments/deliveries 矩阵完整预生成"""
        data = self._create_task()
        self.assertFalse(data.get('error'), data)
        task = CoopTask.objects.get(pk=data['id'])
        self.assertEqual(task.tenant_id, str(self.tenant_a.id))
        self.assertEqual(task.status, TASK_STATUS_IN_PROGRESS)
        self.assertEqual(CoopTaskItem.objects.filter(task=task).count(), 2)
        assignments = CoopTaskAssignment.objects.filter(task=task)
        self.assertEqual(assignments.count(), 2)
        for assignment in assignments:
            self.assertEqual(
                CoopTaskDelivery.objects.filter(assignment=assignment).count(), 2)
        self.assertTrue(CoopTaskAssignment.objects.filter(
            task=task, target_tenant_id=str(self.tenant_b.id),
            target_tenant_name='二科', contact_user_name='李四').exists())

    def test_create_validation_errors(self):
        """缺材料/缺科室/重复科室/不存在科室/坏截止时间均被拒绝"""
        cases = [
            ({**self._create_payload(), 'items': []}, '材料'),
            ({**self._create_payload(), 'targets': []}, '交付科室'),
            ({**self._create_payload(), 'deadline': 'bad-date'}, '截止时间'),
        ]
        for payload, keyword in cases:
            resp = self.initiator_client.post(
                '/coop-task/tasks/', payload, content_type='application/json')
            self.assertTrue(resp.json().get('error'), payload)
            self.assertIn(keyword, resp.json()['error'])
        payload = self._create_payload()
        payload['targets'][1]['tenant_id'] = payload['targets'][0]['tenant_id']
        resp = self.initiator_client.post(
            '/coop-task/tasks/', payload, content_type='application/json')
        self.assertIn('重复', resp.json().get('error', ''))
        payload = self._create_payload()
        payload['targets'][1]['tenant_id'] = '999999'
        resp = self.initiator_client.post(
            '/coop-task/tasks/', payload, content_type='application/json')
        self.assertIn('不存在', resp.json().get('error', ''))
        self.assertEqual(CoopTask.objects.count(), 0)

    def test_permission_denied_without_perm(self):
        """无任何权限的用户不能访问；仅有 view 权限不能创建"""
        resp = self.plain_client.get('/coop-task/tasks/')
        self.assertEqual(resp.json().get('error'), '权限拒绝')
        resp = self.plain_client.post(
            '/coop-task/tasks/', self._create_payload(), content_type='application/json')
        self.assertEqual(resp.json().get('error'), '权限拒绝')
        resp = self.deliverer_b_client.post(
            '/coop-task/tasks/', self._create_payload(), content_type='application/json')
        self.assertEqual(resp.json().get('error'), '权限拒绝')
        self.assertEqual(CoopTask.objects.count(), 0)

    def test_departments_list(self):
        """可选交付对象返回科室账号（人名 + 租户映射），超管不作为分发对象"""
        resp = self.initiator_client.get('/coop-task/departments/')
        by_id = {x['id']: x for x in resp.json()['data']}
        row = by_id[self.deliverer_b.id]
        self.assertEqual(row['name'], 'deliverer_b')
        self.assertEqual(row['tenant_id'], str(self.tenant_b.id))
        self.assertEqual(row['tenant_name'], '二科')
        self.assertNotIn(self.supper.id, by_id)

    def test_create_by_user_id_maps_to_tenant(self):
        """按账号分发：user_id 映射回租户，账号ID/人名快照落库，列表展示人名"""
        data = self._create_task(targets=[
            {'user_id': self.deliverer_b.id},
            {'user_id': self.deliverer_c.id},
        ])
        assignment = CoopTaskAssignment.objects.get(
            task_id=data['id'], target_tenant_id=str(self.tenant_b.id))
        self.assertEqual(assignment.contact_user_id, self.deliverer_b.id)
        self.assertEqual(assignment.contact_user_name, 'deliverer_b')
        self.assertEqual(assignment.target_tenant_name, '二科')
        resp = self.initiator_client.get('/coop-task/tasks/')
        row = [x for x in resp.json()['data']['results'] if x['id'] == data['id']][0]
        self.assertIn('deliverer_b', row['target_tenants'])

    def test_create_user_targets_same_tenant_rejected(self):
        """同一科室的多个账号不能同时作为交付对象"""
        payload = self._create_payload()
        payload['targets'] = [
            {'user_id': self.outsider.id},
            {'user_id': self.plain.id},  # outsider 与 plain 同属 t_x
        ]
        resp = self.initiator_client.post(
            '/coop-task/tasks/', payload, content_type='application/json')
        self.assertIn('重复', resp.json().get('error', ''))
        self.assertEqual(CoopTask.objects.count(), 0)

    def test_create_user_target_unknown_rejected(self):
        payload = self._create_payload()
        payload['targets'] = [{'user_id': 999999}]
        resp = self.initiator_client.post(
            '/coop-task/tasks/', payload, content_type='application/json')
        self.assertIn('不存在', resp.json().get('error', ''))
        self.assertEqual(CoopTask.objects.count(), 0)


# ============================================================
# 交付状态机
# ============================================================

@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class DeliveryFlowTests(CoopTaskFlowTestsBase):

    def setUp(self):
        data = self._create_task(targets=[{'tenant_id': str(self.tenant_b.id), 'contact_user_name': '李四'}])
        self.task_id = data['id']
        self.assignment_id = CoopTaskAssignment.objects.get(task_id=self.task_id).id
        self.deliveries = list(
            CoopTaskDelivery.objects.filter(assignment_id=self.assignment_id).order_by('id'))
        self.first_delivery = self.deliveries[0]

    def _upload(self, delivery_id, filename='总结.pdf', content=b'%PDF-1.4 test'):
        file = SimpleUploadedFile(filename, content)
        return self.deliverer_b_client.post(
            f'/coop-task/deliveries/{delivery_id}/attachments/', {'file': file})

    def test_submit_then_accept_completes_task(self):
        """全部材料验收通过后任务自动完成"""
        self._upload(self.first_delivery.id)
        resp = self.deliverer_b_client.post(
            f'/coop-task/deliveries/{self.first_delivery.id}/submit/')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.first_delivery.refresh_from_db()
        self.assertEqual(self.first_delivery.status, 'submitted')
        self.assertEqual(self.first_delivery.submitter_id, self.deliverer_b.id)

        # 第二份材料也要提交后才能逐份验收完成
        for delivery in self.deliveries:
            if delivery.status == 'pending':
                self.deliverer_b_client.post(f'/coop-task/deliveries/{delivery.id}/submit/')
        for delivery in self.deliveries:
            resp = self.initiator_client.post(f'/coop-task/deliveries/{delivery.id}/accept/')
            self.assertFalse(resp.json().get('error'), resp.json())
        task = CoopTask.objects.get(pk=self.task_id)
        self.assertEqual(task.status, TASK_STATUS_COMPLETED)
        self.assertIsNotNone(task.completed_at)

    def test_reject_then_resubmit(self):
        """退回后可重新提交，退回原因保存"""
        self._upload(self.first_delivery.id)
        self.deliverer_b_client.post(f'/coop-task/deliveries/{self.first_delivery.id}/submit/')
        resp = self.initiator_client.post(
            f'/coop-task/deliveries/{self.first_delivery.id}/reject/',
            {'reason': '格式不对，重交'}, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.first_delivery.refresh_from_db()
        self.assertEqual(self.first_delivery.status, 'rejected')
        self.assertEqual(self.first_delivery.reject_reason, '格式不对，重交')
        # 重新提交 -> 待验收
        resp = self.deliverer_b_client.post(
            f'/coop-task/deliveries/{self.first_delivery.id}/submit/')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.first_delivery.refresh_from_db()
        self.assertEqual(self.first_delivery.status, 'submitted')

    def test_cannot_accept_pending_delivery(self):
        """仅待验收状态可验收"""
        resp = self.initiator_client.post(f'/coop-task/deliveries/{self.first_delivery.id}/accept/')
        self.assertTrue(resp.json().get('error'))

    def test_reject_requires_reason(self):
        self.deliverer_b_client.post(f'/coop-task/deliveries/{self.first_delivery.id}/submit/')
        resp = self.initiator_client.post(
            f'/coop-task/deliveries/{self.first_delivery.id}/reject/',
            {'reason': '  '}, content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_void_task_blocks_submit(self):
        resp = self.initiator_client.post(f'/coop-task/tasks/{self.task_id}/void/')
        self.assertFalse(resp.json().get('error'), resp.json())
        task = CoopTask.objects.get(pk=self.task_id)
        self.assertEqual(task.status, TASK_STATUS_VOIDED)
        resp = self.deliverer_b_client.post(
            f'/coop-task/deliveries/{self.first_delivery.id}/submit/')
        self.assertTrue(resp.json().get('error'))

    def test_delete_attachment_hard_deletes(self):
        """交付方删除附件为物理删除：数据库记录随文件一并移除"""
        self._upload(self.first_delivery.id)
        att = EvidenceAttachment.objects.get(
            module='coop_task', object_type='delivery', object_id=str(self.first_delivery.id))
        resp = self.deliverer_b_client.delete(f'/coop-task/attachments/?id={att.id}')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertFalse(EvidenceAttachment.objects.filter(pk=att.id).exists())

    def test_edit_task_updates_deadline(self):
        resp = self.initiator_client.post(
            f'/coop-task/tasks/{self.task_id}/',
            {'title': '征集5月工作台账', 'description': '改说明',
             'deadline': '2026-10-15 09:00'}, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        task = CoopTask.objects.get(pk=self.task_id)
        self.assertEqual(task.deadline.strftime('%Y-%m-%d %H:%M'), '2026-10-15 09:00')

    def test_delete_task_soft_deletes(self):
        resp = self.initiator_client.delete(f'/coop-task/tasks/{self.task_id}/')
        self.assertFalse(resp.json().get('error'), resp.json())
        # 软删除后被默认管理器过滤，需用 all_with_deleted 验证标记
        task = CoopTask.objects.all_with_deleted().get(pk=self.task_id)
        self.assertTrue(task.is_deleted)
        resp = self.initiator_client.get(f'/coop-task/tasks/{self.task_id}/')
        self.assertTrue(resp.json().get('error'))


# ============================================================
# 跨科室租户隔离
# ============================================================

@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class TenantIsolationTests(CoopTaskFlowTestsBase):

    def setUp(self):
        data = self._create_task()
        self.task_id = data['id']
        self.assignment_b = CoopTaskAssignment.objects.get(
            task_id=self.task_id, target_tenant_id=str(self.tenant_b.id))
        self.assignment_c = CoopTaskAssignment.objects.get(
            task_id=self.task_id, target_tenant_id=str(self.tenant_c.id))
        self.delivery_b = CoopTaskDelivery.objects.filter(
            assignment_id=self.assignment_b.id).first()

    def test_inbox_only_shows_own_tenant(self):
        resp = self.deliverer_b_client.get('/coop-task/inbox/')
        records = resp.json()['data']
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['task_id'], self.task_id)
        # 无关科室看不到
        resp = self.outsider_client.get('/coop-task/inbox/')
        self.assertEqual(resp.json()['data'], [])

    def test_deliverer_cannot_access_other_assignment(self):
        resp = self.deliverer_c_client.get(f'/coop-task/inbox/{self.assignment_b.id}/')
        self.assertTrue(resp.json().get('error'))
        resp = self.outsider_client.get(f'/coop-task/inbox/{self.assignment_b.id}/')
        self.assertTrue(resp.json().get('error'))

    def test_deliverer_cannot_submit_other_delivery(self):
        resp = self.deliverer_c_client.post(
            f'/coop-task/deliveries/{self.delivery_b.id}/submit/')
        self.assertTrue(resp.json().get('error'))
        self.delivery_b.refresh_from_db()
        self.assertEqual(self.delivery_b.status, 'pending')

    def test_other_initiator_cannot_accept(self):
        other_initiator = _make_user('other_init', tenant_id=str(self.tenant_x.id))
        _grant_perms(other_initiator, _coop_perms('view', 'add', 'edit', 'delete', 'accept'))
        client = _make_client(other_initiator)
        self.deliverer_b_client.post(f'/coop-task/deliveries/{self.delivery_b.id}/submit/')
        resp = client.post(f'/coop-task/deliveries/{self.delivery_b.id}/accept/')
        self.assertTrue(resp.json().get('error'))
        self.delivery_b.refresh_from_db()
        self.assertEqual(self.delivery_b.status, 'submitted')

    def test_task_list_scoped_by_tenant(self):
        resp = self.initiator_client.get('/coop-task/tasks/')
        ids = [x['id'] for x in resp.json()['data']['results']]
        self.assertIn(self.task_id, ids)
        # 其他科室的管理账号看不到该任务
        other_initiator = _make_user('other_init2', tenant_id=str(self.tenant_x.id))
        _grant_perms(other_initiator, _coop_perms('view'))
        resp = _make_client(other_initiator).get('/coop-task/tasks/')
        self.assertEqual(resp.json()['data']['results'], [])
        # 超管可见
        resp = self.supper_client.get('/coop-task/tasks/')
        ids = [x['id'] for x in resp.json()['data']['results']]
        self.assertIn(self.task_id, ids)

    def test_attachment_visibility(self):
        """附件可见性：交付科室随时可读；发起科室提交后才可读；无关科室不可读"""
        file = SimpleUploadedFile('台账.pdf', b'%PDF-1.4 data')
        resp = self.deliverer_b_client.post(
            f'/coop-task/deliveries/{self.delivery_b.id}/attachments/', {'file': file})
        self.assertFalse(resp.json().get('error'), resp.json())
        att = EvidenceAttachment.objects.get(
            module='coop_task', object_type='delivery', object_id=str(self.delivery_b.id))
        # 附件归属上传方（交付科室）租户
        self.assertEqual(att.tenant_id, str(self.tenant_b.id))

        # 待交付（未提交）视为交付方草稿：发起科室不可读
        resp = self.initiator_client.get(
            f'/coop-task/deliveries/{self.delivery_b.id}/attachments/')
        self.assertTrue(resp.json().get('error'))
        # 交付科室本人随时可读
        resp = self.deliverer_b_client.get(
            f'/coop-task/deliveries/{self.delivery_b.id}/attachments/')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertEqual(len(resp.json()['data']), 1)

        # 提交后发起科室可读
        resp = self.deliverer_b_client.post(
            f'/coop-task/deliveries/{self.delivery_b.id}/submit/')
        self.assertFalse(resp.json().get('error'), resp.json())
        resp = self.initiator_client.get(
            f'/coop-task/deliveries/{self.delivery_b.id}/attachments/')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertEqual(len(resp.json()['data']), 1)

        # 退回后发起科室仍可读（供对照整改）
        resp = self.initiator_client.post(
            f'/coop-task/deliveries/{self.delivery_b.id}/reject/',
            {'reason': '格式不对，重交'}, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        resp = self.initiator_client.get(
            f'/coop-task/deliveries/{self.delivery_b.id}/attachments/')
        self.assertFalse(resp.json().get('error'), resp.json())

        # 无关科室不可读
        resp = self.deliverer_c_client.get(
            f'/coop-task/deliveries/{self.delivery_b.id}/attachments/')
        self.assertTrue(resp.json().get('error'))
        # 无关科室不能上传、不能删除
        resp = self.deliverer_c_client.post(
            f'/coop-task/deliveries/{self.delivery_b.id}/attachments/',
            {'file': SimpleUploadedFile('x.pdf', b'x')})
        self.assertTrue(resp.json().get('error'))
        resp = self.deliverer_c_client.delete(f'/coop-task/attachments/?id={att.id}')
        self.assertTrue(resp.json().get('error'))
        att.refresh_from_db()
        self.assertFalse(att.is_deleted)
        # 发起科室不能上传（附件写仅交付科室）
        resp = self.initiator_client.post(
            f'/coop-task/deliveries/{self.delivery_b.id}/attachments/',
            {'file': SimpleUploadedFile('y.pdf', b'y')})
        self.assertTrue(resp.json().get('error'))

    def test_task_detail_hides_pending_attachment_count(self):
        """任务详情：待交付材料附件计数对发起方归零，提交后恢复真实计数"""
        file = SimpleUploadedFile('台账.pdf', b'%PDF-1.4 data')
        resp = self.deliverer_b_client.post(
            f'/coop-task/deliveries/{self.delivery_b.id}/attachments/', {'file': file})
        self.assertFalse(resp.json().get('error'), resp.json())

        detail = self._get_detail(self.task_id)['data']
        assignment = [a for a in detail['assignments']
                      if a['target_tenant_id'] == str(self.tenant_b.id)][0]
        row = [d for d in assignment['deliveries'] if d['id'] == self.delivery_b.id][0]
        self.assertEqual(row['status'], 'pending')
        self.assertEqual(row['attachment_count'], 0)

        # 提交后发起方可见真实计数
        resp = self.deliverer_b_client.post(
            f'/coop-task/deliveries/{self.delivery_b.id}/submit/')
        self.assertFalse(resp.json().get('error'), resp.json())
        detail = self._get_detail(self.task_id)['data']
        assignment = [a for a in detail['assignments']
                      if a['target_tenant_id'] == str(self.tenant_b.id)][0]
        row = [d for d in assignment['deliveries'] if d['id'] == self.delivery_b.id][0]
        self.assertEqual(row['status'], 'submitted')
        self.assertEqual(row['attachment_count'], 1)

    def test_upload_allowed_then_blocked_after_accept(self):
        """验收通过后禁止再上传/删除附件"""
        self.deliverer_b_client.post(f'/coop-task/deliveries/{self.delivery_b.id}/submit/')
        self.initiator_client.post(f'/coop-task/deliveries/{self.delivery_b.id}/accept/')
        resp = self.deliverer_b_client.post(
            f'/coop-task/deliveries/{self.delivery_b.id}/attachments/',
            {'file': SimpleUploadedFile('z.pdf', b'z')})
        self.assertTrue(resp.json().get('error'))

    def test_template_upload_and_visibility(self):
        """材料模板：发起方上传，被分派交付科室可读可下载，无关科室不可读"""
        item_id = CoopTaskItem.objects.filter(task_id=self.task_id).first().id
        # 交付方不能上传模板（非发起科室）
        resp = self.deliverer_b_client.post(
            f'/coop-task/items/{item_id}/templates/',
            {'file': SimpleUploadedFile('t.docx', b'x')})
        self.assertTrue(resp.json().get('error'))
        # 发起方上传
        resp = self.initiator_client.post(
            f'/coop-task/items/{item_id}/templates/',
            {'file': SimpleUploadedFile('模板.docx', b'data')})
        self.assertFalse(resp.json().get('error'), resp.json())
        att = EvidenceAttachment.objects.get(
            module='coop_task', object_type='item_template')
        self.assertEqual(att.tenant_id, str(self.tenant_a.id))
        # 任务详情 payload 嵌入模板列表
        detail = self._get_detail(self.task_id)['data']
        item_view = [x for x in detail['items'] if x['id'] == item_id][0]
        self.assertEqual(item_view['templates'][0]['file_name'], '模板.docx')
        # 被分派交付科室可读列表、可下载
        resp = self.deliverer_b_client.get(f'/coop-task/items/{item_id}/templates/')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertEqual(len(resp.json()['data']), 1)
        resp = self.deliverer_b_client.get(f'/coop-task/attachments/{att.id}/download/')
        self.assertEqual(resp.status_code, 200)
        # 收件箱详情 payload 包含模板
        resp = self.deliverer_b_client.get(f'/coop-task/inbox/{self.assignment_b.id}/')
        self.assertTrue(any(
            x['templates'] for x in resp.json()['data']['items']))
        # 无关科室不可读
        resp = self.outsider_client.get(f'/coop-task/items/{item_id}/templates/')
        self.assertTrue(resp.json().get('error'))
        resp = self.outsider_client.get(f'/coop-task/attachments/{att.id}/download/')
        self.assertTrue(resp.json().get('error'))
        # 交付方不能删除模板
        resp = self.deliverer_b_client.delete(f'/coop-task/items/{item_id}/templates/?id={att.id}')
        self.assertTrue(resp.json().get('error'))
        # 发起方删除（物理删除：数据库记录随文件一并移除）
        resp = self.initiator_client.delete(f'/coop-task/items/{item_id}/templates/?id={att.id}')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertFalse(EvidenceAttachment.objects.filter(pk=att.id).exists())

    def test_template_blocked_after_void(self):
        """任务作废后禁止上传模板，下载仍可用"""
        item_id = CoopTaskItem.objects.filter(task_id=self.task_id).first().id
        resp = self.initiator_client.post(
            f'/coop-task/items/{item_id}/templates/',
            {'file': SimpleUploadedFile('模板.pdf', b'data')})
        self.assertFalse(resp.json().get('error'), resp.json())
        att_id = resp.json()['data']['id']
        self.initiator_client.post(f'/coop-task/tasks/{self.task_id}/void/')
        resp = self.initiator_client.post(
            f'/coop-task/items/{item_id}/templates/',
            {'file': SimpleUploadedFile('模板2.pdf', b'data')})
        self.assertIn('任务已结束', resp.json().get('error', ''))
        # 作废后已上传模板仍可下载
        resp = self.deliverer_b_client.get(f'/coop-task/attachments/{att_id}/download/')
        self.assertEqual(resp.status_code, 200)


# ============================================================
# 催办与角标
# ============================================================

class UrgeAndBadgeTests(CoopTaskFlowTestsBase):

    def setUp(self):
        data = self._create_task()
        self.task_id = data['id']
        self.assignment_b = CoopTaskAssignment.objects.get(
            task_id=self.task_id, target_tenant_id=str(self.tenant_b.id))

    def test_urge_increments_and_marks_unread(self):
        resp = self.initiator_client.post(
            f'/coop-task/tasks/{self.task_id}/urge/',
            {'assignment_id': self.assignment_b.id}, content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assignment_b.refresh_from_db()
        self.assertEqual(self.assignment_b.urge_count, 1)
        self.assertIsNotNone(self.assignment_b.last_urged_at)
        # 交付方列表出现催办未读
        resp = self.deliverer_b_client.get('/coop-task/inbox/')
        record = [x for x in resp.json()['data'] if x['id'] == self.assignment_b.id][0]
        self.assertTrue(record['has_unread_urge'])
        # 查看详情后未读消除
        self.deliverer_b_client.get(f'/coop-task/inbox/{self.assignment_b.id}/')
        self.assignment_b.refresh_from_db()
        self.assertFalse(self.assignment_b.has_unread_urge())

    def test_urge_requires_ownership(self):
        """非发起方不能催办"""
        resp = self.deliverer_b_client.post(
            f'/coop-task/tasks/{self.task_id}/urge/',
            {'assignment_id': self.assignment_b.id}, content_type='application/json')
        self.assertTrue(resp.json().get('error'))

    def test_badge_counts(self):
        """角标：交付方待处理 + 发起方待验收 + 催办未读"""
        # 初始：交付方有 1 个待处理任务
        resp = self.deliverer_b_client.get('/coop-task/badge/')
        badge = resp.json()['data']
        self.assertEqual(badge['inbox_pending'], 1)
        self.assertEqual(badge['accept_pending'], 0)
        # 发起方视角：无待验收
        resp = self.initiator_client.get('/coop-task/badge/')
        self.assertEqual(resp.json()['data']['accept_pending'], 0)
        # 交付方提交一份材料后：发起方待验收 1
        delivery = CoopTaskDelivery.objects.filter(
            assignment_id=self.assignment_b.id).first()
        self.deliverer_b_client.post(f'/coop-task/deliveries/{delivery.id}/submit/')
        resp = self.initiator_client.get('/coop-task/badge/')
        self.assertEqual(resp.json()['data']['accept_pending'], 1)
        # 催办后未读 1
        self.initiator_client.post(
            f'/coop-task/tasks/{self.task_id}/urge/',
            {'assignment_id': self.assignment_b.id}, content_type='application/json')
        resp = self.deliverer_b_client.get('/coop-task/badge/')
        self.assertEqual(resp.json()['data']['urge_unread'], 1)


# ============================================================
# 操作审计联动
# ============================================================

class AuditIntegrationTests(CoopTaskFlowTestsBase):

    def setUp(self):
        data = self._create_task()
        self.task_id = data['id']
        self.assignment_b = CoopTaskAssignment.objects.get(
            task_id=self.task_id, target_tenant_id=str(self.tenant_b.id))
        self.delivery_b = CoopTaskDelivery.objects.filter(
            assignment_id=self.assignment_b.id).first()

    def _audit_count(self, action, **filters):
        return AuditLog.objects.filter(
            action=action, target_type='coop_task', **filters).count()

    def test_create_recorded_once(self):
        """创建任务写一条 create 审计，且与中间件不重复"""
        self.assertEqual(self._audit_count('create', target_id=str(self.task_id)), 1)

    def test_update_deadline_recorded_with_before_after(self):
        resp = self.initiator_client.post(
            f'/coop-task/tasks/{self.task_id}/',
            {'title': '征集5月工作台账', 'deadline': '2026-10-15 09:00'},
            content_type='application/json')
        self.assertFalse(resp.json().get('error'), resp.json())
        logs = AuditLog.objects.filter(
            action='update', target_type='coop_task', target_id=str(self.task_id))
        self.assertEqual(logs.count(), 1)
        detail = json.loads(logs.first().detail)
        self.assertIn('before', detail)
        self.assertIn('after', detail)

    def test_submit_and_accept_recorded(self):
        """交付提交记 update、验收记 approve，均归属协作任务"""
        self.deliverer_b_client.post(f'/coop-task/deliveries/{self.delivery_b.id}/submit/')
        self.assertEqual(
            self._audit_count('update', target_id=str(self.task_id)), 1)
        self.initiator_client.post(f'/coop-task/deliveries/{self.delivery_b.id}/accept/')
        self.assertEqual(
            self._audit_count('approve', target_id=str(self.task_id)), 1)
        log = AuditLog.objects.get(
            action='approve', target_type='coop_task', target_id=str(self.task_id))
        detail = json.loads(log.detail)
        self.assertEqual(detail.get('result'), 'accepted')

    def test_urge_and_void_recorded(self):
        self.initiator_client.post(
            f'/coop-task/tasks/{self.task_id}/urge/',
            {'assignment_id': self.assignment_b.id}, content_type='application/json')
        log = AuditLog.objects.filter(
            action='update', target_type='coop_task', target_id=str(self.task_id)
        ).order_by('id').last()
        detail = json.loads(log.detail)
        self.assertEqual(detail.get('action'), 'urge')
        self.initiator_client.post(f'/coop-task/tasks/{self.task_id}/void/')
        log = AuditLog.objects.filter(
            action='update', target_type='coop_task', target_id=str(self.task_id)
        ).order_by('id').last()
        detail = json.loads(log.detail)
        self.assertEqual(detail.get('status'), 'voided')

    def test_delete_recorded(self):
        self.initiator_client.delete(f'/coop-task/tasks/{self.task_id}/')
        self.assertEqual(self._audit_count('delete', target_id=str(self.task_id)), 1)

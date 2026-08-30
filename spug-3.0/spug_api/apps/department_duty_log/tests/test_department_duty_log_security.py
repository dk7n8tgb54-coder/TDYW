# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""部门值班日志模块安全测试

覆盖所有权与注入防护，全部走真实 HTTP 路径并校验数据库状态未被篡改：
- 水平越权：他人草稿不可编辑/删除/签署/查看/读取签名图片
- 超管只读：可见他人草稿但不可编辑/删除/签署
- 幂等键安全：签署 request_id 跨用户冲突、跨记录重放被拒绝
- 输入注入：关键字 SQL 注入不生效；特殊字符内容完整往返
- 权限粒度：仅 view 用户所有写操作被拒绝；缺对应权限编码一律'权限拒绝'
- 导出安全：草稿内容不可经导出关键字触达；无 view 权限不可导出
"""
import json
from datetime import date
from urllib.parse import quote

from django.test import TestCase

from apps.setting.utils import AppSetting
from apps.signature.models import SignatureUsage
from apps.department_duty_log.models import DepartmentDutyLog

from apps.department_duty_log.tests.test_comprehensive import (
    _make_user, _make_client, _grant_perms, _make_record, _make_png_file,
)
from apps.department_duty_log.tests.test_department_duty_log_regression import (
    SignatureFlowBase,
)


def _full_perms(user):
    _grant_perms(user, [
        ('department_duty_log', 'department_duty_log',
         ['view', 'add', 'edit', 'del', 'sign', 'return', 'export']),
    ])


class OwnershipSecurityTests(TestCase):
    """水平越权：他人草稿即使攻击者持全量权限也不可操作"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.owner = _make_user('ddl_sec_owner', tenant_id='tenant_a')
        _full_perms(self.owner)
        self.attacker = _make_user('ddl_sec_attacker', tenant_id='tenant_b')
        _full_perms(self.attacker)
        self.client = _make_client(self.attacker)
        self.record = _make_record(self.owner)

    def test_attacker_cannot_edit_owner_draft(self):
        resp = self.client.put(
            f'/department-duty-log/records/{self.record.id}/',
            data=json.dumps({
                'duty_date': str(date.today()), 'weather': '晴',
                'duty_record': '篡改内容', 'remark': '', 'version': 1,
            }), content_type='application/json').json()
        self.assertIn('只能编辑本人草稿', resp.get('error', ''))
        self.record.refresh_from_db()
        self.assertEqual(self.record.duty_record, '值班正常')
        self.assertEqual(self.record.version, 1)

    def test_attacker_cannot_delete_owner_draft(self):
        resp = self.client.delete(
            f'/department-duty-log/records/{self.record.id}/').json()
        self.assertIn('只能删除本人草稿', resp.get('error', ''))
        self.record.refresh_from_db()
        self.assertIsNone(self.record.deleted_at)

    def test_attacker_cannot_sign_owner_draft(self):
        resp = self.client.post(
            f'/department-duty-log/records/{self.record.id}/sign/',
            data=json.dumps({'version': 1, 'confirm': True, 'request_id': 'sec-x'}),
            content_type='application/json').json()
        self.assertIn('只能签署本人草稿', resp.get('error', ''))
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'draft')
        self.assertIsNone(self.record.signature_usage_id)

    def test_attacker_cannot_view_owner_draft(self):
        resp = self.client.get(
            f'/department-duty-log/records/{self.record.id}/').json()
        self.assertIn('记录不存在', resp.get('error', ''))
        ids = [r['id'] for r in self.client.get(
            '/department-duty-log/records/').json()['data']['records']]
        self.assertNotIn(self.record.id, ids)

    def test_attacker_cannot_read_owner_draft_signature_image(self):
        resp = self.client.get(
            f'/department-duty-log/records/{self.record.id}/signature-image/')
        self.assertEqual(resp.status_code, 403)

    def test_supper_readonly_on_others_draft(self):
        """超管可见他人草稿但不可编辑/删除/签署"""
        supper = _make_user('ddl_sec_supper', is_supper=True, tenant_id='default')
        client = _make_client(supper)
        resp = client.get(
            f'/department-duty-log/records/{self.record.id}/').json()
        self.assertFalse(resp.get('error'), resp)
        resp = client.put(
            f'/department-duty-log/records/{self.record.id}/',
            data=json.dumps({
                'duty_date': str(date.today()), 'weather': '晴',
                'duty_record': '超管篡改', 'remark': '', 'version': 1,
            }), content_type='application/json').json()
        self.assertIn('只能编辑本人草稿', resp.get('error', ''))
        resp = client.delete(
            f'/department-duty-log/records/{self.record.id}/').json()
        self.assertIn('只能删除本人草稿', resp.get('error', ''))
        resp = client.post(
            f'/department-duty-log/records/{self.record.id}/sign/',
            data=json.dumps({'version': 1, 'confirm': True, 'request_id': 'sec-s'}),
            content_type='application/json').json()
        self.assertIn('只能签署本人草稿', resp.get('error', ''))
        self.record.refresh_from_db()
        self.assertEqual(self.record.status, 'draft')
        self.assertEqual(self.record.duty_record, '值班正常')


class ForgedFieldSecurityTests(SignatureFlowBase):
    """伪造字段与幂等键安全"""

    def _create_draft_for(self, user, client, duty_record):
        resp = client.post(
            '/department-duty-log/records/', data=json.dumps({
                'duty_date': str(date.today()),
                'weather': '晴',
                'duty_record': duty_record,
                'remark': '',
            }), content_type='application/json').json()
        self.assertFalse(resp.get('error'), resp)
        return DepartmentDutyLog.objects.get(pk=resp['data']['id'])

    def test_put_cannot_forge_status_or_owner(self):
        record = self._create_draft_for(
            self.signer, self.signer_client, '伪造字段测试')
        resp = self.signer_client.put(
            f'/department-duty-log/records/{record.id}/',
            data=json.dumps({
                'duty_date': str(date.today()), 'weather': '晴',
                'duty_record': '正常编辑', 'remark': '',
                'version': 1, 'status': 'signed', 'duty_person_id': 99999,
            }), content_type='application/json').json()
        self.assertIn('不允许提交的字段', resp.get('error', ''))
        record.refresh_from_db()
        self.assertEqual(record.status, 'draft')
        self.assertEqual(record.duty_person_id, self.signer.id)
        self.assertEqual(record.duty_record, '伪造字段测试')

    def test_sign_cannot_forge_signature_binding(self):
        record = self._create_draft_for(
            self.signer, self.signer_client, '签署伪造测试')
        resp = self.signer_client.post(
            f'/department-duty-log/records/{record.id}/sign/',
            data=json.dumps({
                'version': 1, 'confirm': True, 'request_id': 'sec-forge-1',
                'signature_usage_id': 123, 'signed_by_id': 999,
            }), content_type='application/json').json()
        self.assertIn('不允许提交的字段', resp.get('error', ''))
        record.refresh_from_db()
        self.assertEqual(record.status, 'draft')
        self.assertEqual(
            SignatureUsage.objects.filter(request_id='sec-forge-1').count(), 0)

    def test_request_id_cross_user_conflict(self):
        """同一租户内 request_id 被其他用户复用签署 → 幂等冲突拒绝"""
        record = self._create_draft_for(
            self.signer, self.signer_client, '幂等键属主记录')
        resp = self._sign(record, 'sec-req-shared', version=1)
        self.assertFalse(resp.json().get('error'), resp.json())

        attacker = _make_user('ddl_sec_req_user', tenant_id='tenant_a')
        _grant_perms(attacker, [
            ('department_duty_log', 'department_duty_log', ['view', 'add', 'sign']),
        ])
        attacker_client = _make_client(attacker)
        attack_record = self._create_draft_for(
            attacker, attacker_client, '幂等键攻击记录')

        resp = attacker_client.post(
            f'/department-duty-log/records/{attack_record.id}/sign/',
            data=json.dumps({
                'version': 1, 'confirm': True, 'request_id': 'sec-req-shared',
            }), content_type='application/json').json()
        self.assertIn('幂等冲突', resp.get('error', ''), resp)
        attack_record.refresh_from_db()
        self.assertEqual(attack_record.status, 'draft')
        self.assertIsNone(attack_record.signature_usage_id)

    def test_request_id_cross_record_replay_rejected(self):
        """回归修复：已签记录重放其他记录的 request_id 必须拒绝而非返回成功"""
        r1 = self._create_draft_for(self.signer, self.signer_client, '重放源记录')
        resp = self._sign(r1, 'sec-reuse-x', version=1)
        self.assertFalse(resp.json().get('error'), resp.json())

        r2 = self._create_draft_for(self.signer, self.signer_client, '重放目标记录')
        resp = self._sign(r2, 'sec-reuse-y', version=1)
        self.assertFalse(resp.json().get('error'), resp.json())
        r2.refresh_from_db()
        usage_2 = r2.signature_usage_id

        # 携记录一的 request_id 重放记录二的签署 → 必须拒绝
        resp = self._sign(r2, 'sec-reuse-x', version=r2.version)
        self.assertTrue(resp.json().get('error'), resp)
        r2.refresh_from_db()
        self.assertEqual(r2.signature_usage_id, usage_2)
        self.assertEqual(r2.status, 'signed')


class InputInjectionSecurityTests(TestCase):
    """输入注入与特殊字符往返"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.user = _make_user('ddl_sec_inject', tenant_id='tenant_a')
        _grant_perms(self.user, [
            ('department_duty_log', 'department_duty_log',
             ['view', 'add', 'edit', 'export']),
        ])
        self.client = _make_client(self.user)
        self.record = _make_record(self.user)

    def test_keyword_sql_injection_harmless(self):
        before = DepartmentDutyLog.objects.count()
        for keyword in ("' OR '1'='1", "'; DROP TABLE tdyw_department_duty_log;--",
                        "' UNION SELECT NULL--", "%_%"):
            body = self.client.get(
                f'/department-duty-log/records/?keyword={quote(keyword)}').json()
            self.assertFalse(body.get('error'), (keyword, body))
            self.assertEqual(body['data']['total'], 0, keyword)
        self.assertEqual(DepartmentDutyLog.objects.count(), before)
        # 表完好，原记录仍可查
        body = self.client.get('/department-duty-log/records/?keyword=值班正常').json()
        self.assertEqual(body['data']['total'], 1)

    def test_duty_person_name_injection_harmless(self):
        for name in ("' OR '1'='1'--", "%‘%"):
            body = self.client.get(
                f'/department-duty-log/records/?duty_person_name={quote(name)}').json()
            self.assertFalse(body.get('error'), (name, body))

    def test_special_chars_roundtrip(self):
        """含引号/尖括号/反斜杠/换行的内容完整存取，JSON 转义无损"""
        weather = "晴<>&\"'"
        duty_record = "<script>alert('x')</script>\r\n第二行 & 符号 \\反斜杠"
        remark = "备注'\"\\<>混合"
        resp = self.client.post(
            '/department-duty-log/records/', data=json.dumps({
                'duty_date': str(date.today()),
                'weather': weather,
                'duty_record': duty_record,
                'remark': remark,
            }), content_type='application/json').json()
        self.assertFalse(resp.get('error'), resp)
        record_id = resp['data']['id']
        detail = self.client.get(
            f'/department-duty-log/records/{record_id}/').json()['data']
        self.assertEqual(detail['weather'], weather)
        self.assertEqual(detail['duty_record'], duty_record)
        self.assertEqual(detail['remark'], remark)

    def test_export_keyword_injection_no_server_error(self):
        for keyword in ("' OR '1'='1", "'; DROP TABLE tdyw_department_duty_log;--"):
            resp = self.client.post(
                '/department-duty-log/export/pdf/',
                data=json.dumps({'keyword': keyword}),
                content_type='application/json')
            body = resp.json()
            self.assertNotEqual(
                body.get('error'), '服务器内部错误，请联系管理员', (keyword, body))


class PermissionGranularitySecurityTests(TestCase):
    """权限粒度：缺对应权限编码一律'权限拒绝'"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.record_owner = _make_user('ddl_sec_gran_owner', tenant_id='tenant_a')

    def _grant(self, user, *keys):
        _grant_perms(user, [('department_duty_log', 'department_duty_log', list(keys))])

    def test_view_only_user_cannot_write(self):
        viewer = _make_user('ddl_sec_viewer', tenant_id='tenant_a')
        self._grant(viewer, 'view')
        client = _make_client(viewer)
        record = _make_record(self.record_owner, status='draft')
        payload = json.dumps({
            'duty_date': str(date.today()), 'weather': '晴',
            'duty_record': '越权', 'remark': '', 'version': 1,
        })
        resp = client.post(
            '/department-duty-log/records/', data=payload,
            content_type='application/json').json()
        self.assertEqual(resp.get('error'), '权限拒绝')
        resp = client.put(
            f'/department-duty-log/records/{record.id}/', data=payload,
            content_type='application/json').json()
        self.assertEqual(resp.get('error'), '权限拒绝')
        resp = client.delete(
            f'/department-duty-log/records/{record.id}/').json()
        self.assertEqual(resp.get('error'), '权限拒绝')
        resp = client.post(
            f'/department-duty-log/records/{record.id}/sign/',
            data=json.dumps({'version': 1, 'confirm': True}),
            content_type='application/json').json()
        self.assertEqual(resp.get('error'), '权限拒绝')
        resp = client.post(
            '/department-duty-log/export/pdf/', data=json.dumps({}),
            content_type='application/json').json()
        self.assertEqual(resp.get('error'), '权限拒绝')
        record.refresh_from_db()
        self.assertEqual(record.status, 'draft')

    def test_add_only_user_cannot_read_or_edit(self):
        user = _make_user('ddl_sec_addonly', tenant_id='tenant_a')
        self._grant(user, 'add')
        client = _make_client(user)
        resp = client.get('/department-duty-log/records/').json()
        self.assertEqual(resp.get('error'), '权限拒绝')
        record = _make_record(self.record_owner)
        resp = client.put(
            f'/department-duty-log/records/{record.id}/',
            data=json.dumps({
                'duty_date': str(date.today()), 'weather': '晴',
                'duty_record': 'x', 'remark': '', 'version': 1,
            }), content_type='application/json').json()
        self.assertEqual(resp.get('error'), '权限拒绝')

    def test_edit_del_sign_return_isolated(self):
        """edit/del 与 sign/return 权限互相独立"""
        editor = _make_user('ddl_sec_editor', tenant_id='tenant_a')
        self._grant(editor, 'view', 'edit', 'del')
        signer = _make_user('ddl_sec_signer', tenant_id='tenant_a')
        self._grant(signer, 'view', 'sign')

        draft = _make_record(self.record_owner)
        resp = _make_client(signer).put(
            f'/department-duty-log/records/{draft.id}/',
            data=json.dumps({
                'duty_date': str(date.today()), 'weather': '晴',
                'duty_record': 'x', 'remark': '', 'version': 1,
            }), content_type='application/json').json()
        self.assertEqual(resp.get('error'), '权限拒绝')

        signed = _make_record(self.record_owner, status='signed')
        resp = _make_client(signer).post(
            f'/department-duty-log/records/{signed.id}/return/',
            data=json.dumps({}), content_type='application/json').json()
        self.assertEqual(resp.get('error'), '权限拒绝')
        signed.refresh_from_db()
        self.assertEqual(signed.status, 'signed')


class ExportSecurityTests(TestCase):
    """导出安全：草稿不可经导出触达，无 view 权限不可导出"""

    def setUp(self):
        AppSetting.set('bind_ip', False)
        self.exporter = _make_user('ddl_sec_exporter', tenant_id='tenant_a')
        _grant_perms(self.exporter, [
            ('department_duty_log', 'department_duty_log', ['view', 'export']),
        ])
        self.client = _make_client(self.exporter)

    def test_draft_content_not_leakable_via_export(self):
        """草稿内容不能通过导出关键字搜索触达"""
        creator = _make_user('ddl_sec_creator', tenant_id='tenant_a')
        _grant_perms(creator, [
            ('department_duty_log', 'department_duty_log', ['view', 'add']),
        ])
        _make_client(creator).post(
            '/department-duty-log/records/', data=json.dumps({
                'duty_date': str(date.today()),
                'weather': '晴',
                'duty_record': 'TOPSECRET-42 机密草稿内容',
                'remark': '',
            }), content_type='application/json')

        resp = self.client.post(
            '/department-duty-log/export/pdf/',
            data=json.dumps({'keyword': 'TOPSECRET'}),
            content_type='application/json')
        body = resp.json()
        self.assertEqual(resp.status_code, 400)
        self.assertIn('没有可导出的已签记录', body.get('error', ''))

    def test_export_without_view_perm_denied(self):
        user = _make_user('ddl_sec_exportonly', tenant_id='tenant_a')
        _grant_perms(user, [
            ('department_duty_log', 'department_duty_log', ['export']),
        ])
        resp = _make_client(user).post(
            '/department-duty-log/export/pdf/', data=json.dumps({}),
            content_type='application/json').json()
        self.assertIn('权限拒绝：需要查看权限', resp.get('error', ''))

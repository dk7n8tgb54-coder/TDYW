# -*- coding: utf-8 -*-
"""原生维护台账模板生命周期测试（2026-10-18 接入）。

覆盖：创建/详情/基础信息修改、草稿整体替换与全量校验、发布不可变版本
（发布后改草稿不影响历史版本与历史台账）、版本只读（写方法 405）、
停用/删除（引用复查）、跨租户拒绝与权限拒绝（后端独立校验）。
"""
from django.test import TestCase

from apps.equipment_lifecycle.native_models import (
    OperationLedgerNativeTemplate,
    OperationLedgerNativeTemplateVersion,
)
from apps.equipment_lifecycle.tests.base import make_client, make_user
from apps.equipment_lifecycle.tests.native_fixtures import (
    make_binding,
    make_native_ledger,
    make_native_template,
    make_published_version,
    sample_paper,
    sample_snapshot,
)

URL = '/equipment-lifecycle/native-templates'
PERMS = [
    'equipment_lifecycle.ledger_template.%s' % a
    for a in ('view', 'add', 'edit', 'del')
] + ['equipment_lifecycle.ledger.%s' % a for a in ('view', 'add', 'edit')]


class NativeTemplateApiTests(TestCase):
    def setUp(self):
        self.user = make_user('native_tpl_user', perms=PERMS)
        self.client = make_client(self.user)

    def _draft_payload(self, bindings=None, **paper_overrides):
        return {
            'snapshot': sample_snapshot(),
            'bindings': [make_binding('field_a')] if bindings is None else bindings,
            'paper': sample_paper(**paper_overrides),
        }

    def test_create_and_detail(self):
        res = self.client.post('%s/' % URL, {
            'name': '信道维护原生模板', 'ledger_type': 'week_month',
            'description': '说明',
        }, content_type='application/json')
        self.assertEqual(res.json()['error'], '')
        data = res.json()['data']['data']
        self.assertEqual(data['name'], '信道维护原生模板')
        self.assertEqual(data['ledger_type'], 'week_month')
        self.assertEqual(data['status'], 'draft')
        self.assertIsNone(data['draft'])

        res = self.client.get('%s/%d/' % (URL, data['id']))
        self.assertEqual(res.json()['error'], '')
        self.assertEqual(res.json()['data']['data']['id'], data['id'])

    def test_create_requires_name_and_valid_type(self):
        res = self.client.post('%s/' % URL, {'name': '', 'ledger_type': 'week_month'},
                               content_type='application/json')
        self.assertIn('模板名称不能为空', res.json()['error'])
        res = self.client.post('%s/' % URL, {'name': 'X', 'ledger_type': 'inspection'},
                               content_type='application/json')
        self.assertTrue(res.json()['error'])

    def test_update_meta_rejects_type_change(self):
        template = make_native_template(self.user)
        res = self.client.put('%s/%d/' % (URL, template.id), {
            'name': '改名', 'ledger_type': 'seasonal',
        }, content_type='application/json')
        self.assertIn('不可修改', res.json()['error'])
        res = self.client.put('%s/%d/' % (URL, template.id), {'name': '新名字'},
                              content_type='application/json')
        self.assertEqual(res.json()['error'], '')
        template.refresh_from_db()
        self.assertEqual(template.name, '新名字')
        self.assertEqual(template.ledger_type, 'week_month')

    # ==================== 草稿保存与校验 ====================

    def test_save_draft_roundtrip(self):
        template = make_native_template(self.user)
        payload = self._draft_payload()
        res = self.client.put('%s/%d/draft/' % (URL, template.id), payload,
                              content_type='application/json')
        self.assertEqual(res.json()['error'], '')
        data = res.json()['data']['data']
        self.assertTrue(data['has_draft'])
        self.assertTrue(data['has_draft_bindings'])
        self.assertEqual(data['draft']['bindings'][0]['key'], 'field_a')
        self.assertEqual(data['draft']['paper']['size'], 'A4')

    def test_save_draft_validation(self):
        template = make_native_template(self.user)
        # 空绑定允许保存（发布时才要求 ≥1）
        res = self.client.put('%s/%d/draft/' % (URL, template.id),
                              {'snapshot': sample_snapshot(), 'bindings': []},
                              content_type='application/json')
        self.assertEqual(res.json()['error'], '')

        # 非法单元格引用
        bad = [make_binding('a', cell_range='5B')]
        res = self.client.put('%s/%d/draft/' % (URL, template.id),
                              self._draft_payload(bad), content_type='application/json')
        self.assertIn('单元格引用不合法', res.json()['error'])
        # 重复 key
        bad = [make_binding('a', cell_range='B2'), make_binding('a', cell_range='B3')]
        res = self.client.put('%s/%d/draft/' % (URL, template.id),
                              self._draft_payload(bad), content_type='application/json')
        self.assertIn('字段标识重复', res.json()['error'])
        # 重复单元格
        bad = [make_binding('a', cell_range='B2'), make_binding('b', cell_range='B2')]
        res = self.client.put('%s/%d/draft/' % (URL, template.id),
                              self._draft_payload(bad), content_type='application/json')
        self.assertIn('被绑定到多个字段', res.json()['error'])
        # 非法类型
        bad = [make_binding('a', ftype='magic')]
        res = self.client.put('%s/%d/draft/' % (URL, template.id),
                              self._draft_payload(bad), content_type='application/json')
        self.assertIn('字段类型不合法', res.json()['error'])
        # 非法纸张
        res = self.client.put('%s/%d/draft/' % (URL, template.id),
                              self._draft_payload(size='B5'),
                              content_type='application/json')
        self.assertIn('纸张规格', res.json()['error'])
        res = self.client.put('%s/%d/draft/' % (URL, template.id),
                              self._draft_payload(margins={'top': 3}),
                              content_type='application/json')
        self.assertIn('页边距', res.json()['error'])

    # ==================== 发布与版本不可变 ====================

    def test_publish_and_version_immutable(self):
        template = make_native_template(self.user)
        self.client.put('%s/%d/draft/' % (URL, template.id),
                        self._draft_payload(), content_type='application/json')
        res = self.client.post('%s/%d/publish/' % (URL, template.id))
        self.assertEqual(res.json()['error'], '')
        self.assertEqual(res.json()['data']['data']['latest_version_no'], 1)
        version_id = res.json()['data']['data']['versions'][0]['id']

        # 未绑定不能发布
        template2 = make_native_template(self.user, name='未绑定模板')
        self.client.put('%s/%d/draft/' % (URL, template2.id),
                        {'snapshot': sample_snapshot(), 'bindings': []},
                        content_type='application/json')
        res = self.client.post('%s/%d/publish/' % (URL, template2.id))
        self.assertIn('绑定至少一个', res.json()['error'])

        # 无草稿不能发布
        template3 = make_native_template(self.user, name='无草稿模板')
        res = self.client.post('%s/%d/publish/' % (URL, template3.id))
        self.assertIn('没有可发布的草稿', res.json()['error'])

        # 发布后修改草稿：历史版本快照不变，再发布产生 v2
        changed = sample_snapshot(title='改过的标题')
        self.client.put('%s/%d/draft/' % (URL, template.id), {
            'snapshot': changed,
            'bindings': [make_binding('field_a'), make_binding('field_b', cell_range='B3')],
            'paper': sample_paper(orientation='portrait'),
        }, content_type='application/json')
        res = self.client.get('%s/%d/versions/%d/' % (URL, template.id, 1))
        self.assertEqual(res.json()['error'], '')
        v1 = res.json()['data']['data']
        self.assertEqual(v1['version_no'], 1)
        self.assertEqual(v1['id'], version_id)
        # v1 快照仍是发布时内容
        title_cell = v1['snapshot']['sheets']['ledger']['cellData']['1']['0']['v']
        self.assertEqual(title_cell, '原生测试台账')
        self.assertEqual(len(v1['bindings']), 1)

        res = self.client.post('%s/%d/publish/' % (URL, template.id))
        self.assertEqual(res.json()['data']['data']['latest_version_no'], 2)
        # v2 才是新内容
        res = self.client.get('%s/%d/versions/2/' % (URL, template.id))
        v2 = res.json()['data']['data']
        self.assertEqual(
            v2['snapshot']['sheets']['ledger']['cellData']['1']['0']['v'], '改过的标题')
        self.assertEqual(v2['paper']['orientation'], 'portrait')

    def test_version_detail_is_readonly(self):
        template = make_native_template(self.user)
        version = make_published_version(template, self.user)
        for method, path in (
            ('put', '%s/%d/versions/%d/' % (URL, template.id, version.version_no)),
            ('post', '%s/%d/versions/%d/' % (URL, template.id, version.version_no)),
            ('delete', '%s/%d/versions/%d/' % (URL, template.id, version.version_no)),
        ):
            res = getattr(self.client, method)(path, {}, content_type='application/json')
            self.assertEqual(res.status_code, 405, (method, res.status_code))

    # ==================== 停用 / 删除 ====================

    def test_deactivate_and_destroy_with_reference_check(self):
        template = make_native_template(self.user)
        version = make_published_version(template, self.user)
        ledger = make_native_ledger(self.user, version)

        # 被引用模板不能物理删除
        res = self.client.delete('%s/%d/' % (URL, template.id))
        self.assertIn('不能删除', res.json()['error'])

        # 停用后：新台账拒绝，历史台账正常
        res = self.client.post('%s/%d/deactivate/' % (URL, template.id))
        self.assertEqual(res.json()['error'], '')
        res = self.client.post('%s/%d/deactivate/' % (URL, template.id))
        self.assertEqual(res.json()['error'], '')  # 幂等
        res = self.client.put('%s/%d/draft/' % (URL, template.id),
                              self._draft_payload(), content_type='application/json')
        self.assertIn('停用', res.json()['error'])
        res = self.client.post('/equipment-lifecycle/native-ledgers/', {
            'version_id': version.id, 'executed_date': '2026-10-18',
            'client_token': '',
        }, content_type='application/json')
        self.assertIn('停用', res.json()['error'])
        res = self.client.get('/equipment-lifecycle/native-ledgers/%d/' % ledger.id)
        self.assertEqual(res.json()['error'], '')

        # 无引用模板可删除（版本级联删除）
        template2 = make_native_template(self.user, name='待删模板')
        make_published_version(template2, self.user)
        res = self.client.delete('%s/%d/' % (URL, template2.id))
        self.assertEqual(res.json()['error'], '')
        self.assertFalse(OperationLedgerNativeTemplate.objects.filter(pk=template2.id).exists())
        self.assertFalse(
            OperationLedgerNativeTemplateVersion.objects.filter(template_id=template2.id).exists())

    # ==================== 权限与租户 ====================

    def test_cross_tenant_and_permission_denied(self):
        template = make_native_template(self.user)
        other = make_user('native_other_tenant', tenant_id='tenant-other', perms=PERMS)
        other_client = make_client(other)
        res = other_client.get('%s/%d/' % (URL, template.id))
        self.assertIn('不存在', res.json()['error'])

        no_perm_user = make_user('native_no_perm', perms=[])
        res = make_client(no_perm_user).get('%s/' % URL)
        self.assertIn('权限拒绝', res.json()['error'])

        # 跨租户用户看到的列表不含他租户模板
        res = other_client.get('%s/' % URL)
        self.assertEqual(res.json()['data']['data'], [])

    def test_version_snapshot_contract(self):
        """版本快照/绑定/纸张读取端必须可解析（防御分支覆盖在服务层）。"""
        template = make_native_template(self.user)
        version = make_published_version(template, self.user)
        snapshot = version.get_snapshot()
        self.assertIn('sheets', snapshot)
        self.assertEqual(version.get_bindings()[0]['key'], 'field_a')
        self.assertEqual(version.get_paper()['size'], 'A4')

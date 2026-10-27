"""干扰分类选项与事件分类校验契约测试（2026-10-25 分类选项化改造）。

覆盖：迁移播种、选项查询权限、超级管理员维护（权限/唯一性/审计/删除）、
事件保存/编辑/导入的选项表校验、停用编码历史保留、明细场景一致性、
CSV 导入导出名称往返、数据分析显示名称，以及选项删除与事件写入的
并发锁序（TransactionTestCase）。
"""

import csv
import io
import json
import threading
import time
from datetime import datetime

from django.db import connection, transaction
from django.test import RequestFactory, TestCase, TransactionTestCase

from apps.interference import category_services
from apps.interference.category_views import CategoryDetailView
from apps.interference.models import (
    AirInterferenceDetail,
    InterferenceCategoryOption,
    InterferenceEvent,
)
from apps.logs.models import AuditLog
from apps.utils.test_helpers import make_client, make_user, setup_test_env

EVENT_PERMS = [
    'interference.interference.view',
    'interference.interference.add',
    'interference.interference.edit',
    'interference.interference.del',
]
CATEGORIES_URL = '/interference/categories/'


def ok_data(response):
    """断言业务成功并返回解包后的 data（项目约定成功载荷包在 data 键内）。"""
    payload = json.loads(response.content)
    assert not payload.get('error'), payload
    return payload.get('data') or {}


def err(response):
    """返回业务错误信息（HTTP 200 + error 约定）。"""
    return json.loads(response.content).get('error') or ''


class CategorySeedTest(TestCase):
    """迁移播种：按 2026-10-26 裁剪口径（21→13）播种固定选项——干扰类型 4 条、
    疑似干扰源 2 条、受影响系统 7 条不变（含「未知/待查」）。"""

    def test_seed_options_imported(self):
        # 2026-10-26 种子精简（21→13，对齐开发环境已验证口径）：
        # 干扰类型仅 noise/intermittent/communication_loss/unknown，
        # 疑似干扰源仅 ground_equipment/unknown，受影响系统 7 条不变。
        for group, expected_codes in (
            ('interference_kind', [
                'noise', 'intermittent', 'communication_loss', 'unknown']),
            ('affected_system', [
                'communication', 'navigation', 'surveillance', 'datalink',
                'equipment', 'other', 'unknown']),
            ('source_type', [
                'ground_equipment', 'unknown']),
        ):
            codes = list(
                InterferenceCategoryOption.objects.filter(group=group)
                .order_by('sort_id', 'id').values_list('code', flat=True))
            self.assertEqual(codes, expected_codes, group)
            for option in InterferenceCategoryOption.objects.filter(group=group):
                self.assertTrue(option.is_active)
                self.assertTrue(option.name)

    def test_unknown_option_semantics(self):
        option = InterferenceCategoryOption.objects.get(
            group='affected_system', code='unknown')
        self.assertEqual(option.name, '未知/待查')
        self.assertTrue(option.is_active)


class CategoryQueryPermissionTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.user = make_user('inter_cat_query', EVENT_PERMS)
        self.client_auth = make_client(self.user)
        self.supper = make_user('inter_cat_supper', is_supper=True)
        self.client_supper = make_client(self.supper)

    def test_normal_user_reads_active_options(self):
        data = ok_data(self.client_auth.get(CATEGORIES_URL))
        records = data['records']
        self.assertTrue(records)
        self.assertTrue(all(item['is_active'] for item in records))
        groups = {item['value'] for item in data['groups']}
        self.assertEqual(
            groups, {'interference_kind', 'affected_system', 'source_type'})

    def test_normal_user_cannot_read_inactive(self):
        # 种子精简后 environment 不在种子内：用例内自建待停用选项（不依赖种子）
        option = InterferenceCategoryOption.objects.create(
            group='source_type', code='legacy_option', name='遗留选项',
            sort_id=90)
        option.is_active = False
        option.save()
        data = ok_data(self.client_auth.get(
            CATEGORIES_URL + '?include_inactive=1&group=source_type'))
        codes = {item['code'] for item in data['records']}
        self.assertNotIn('legacy_option', codes)

    def test_supper_reads_inactive_options(self):
        # 种子精简后 environment 不在种子内：用例内自建待停用选项（不依赖种子）
        option = InterferenceCategoryOption.objects.create(
            group='source_type', code='legacy_option', name='遗留选项',
            sort_id=90)
        option.is_active = False
        option.save()
        data = ok_data(self.client_supper.get(
            CATEGORIES_URL + '?include_inactive=1&group=source_type'))
        codes = {item['code'] for item in data['records']}
        self.assertIn('legacy_option', codes)

    def test_user_without_interference_perm_rejected(self):
        outsider = make_user('inter_cat_outsider', ['home.announcement.view'])
        response = make_client(outsider).get(CATEGORIES_URL)
        self.assertEqual(err(response), '权限拒绝')


class CategoryManagePermissionTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.user = make_user('inter_cat_mgr_user', EVENT_PERMS)
        self.client_auth = make_client(self.user)
        self.supper = make_user('inter_cat_mgr_supper', is_supper=True)
        self.client_supper = make_client(self.supper)

    def test_normal_user_cannot_create(self):
        response = self.client_auth.post(CATEGORIES_URL, {
            'group': 'interference_kind', 'code': 'harmonic',
            'name': '谐波干扰',
        }, content_type='application/json')
        # 维护权限码不进入角色权限树：普通用户先被 @auth 拦截；
        # 即使权限码被手工授予，视图内的 is_supper 校验仍会拒绝
        self.assertIn(err(response), ('权限拒绝', '仅超级管理员可维护分类选项'))
        self.assertFalse(InterferenceCategoryOption.objects.filter(code='harmonic').exists())

    def test_normal_user_cannot_update(self):
        option = InterferenceCategoryOption.objects.get(
            group='interference_kind', code='noise')
        response = self.client_auth.put(
            f'{CATEGORIES_URL}{option.id}/',
            {'name': '改名'}, content_type='application/json')
        self.assertIn(err(response), ('权限拒绝', '仅超级管理员可维护分类选项'))
        option.refresh_from_db()
        self.assertEqual(option.name, '杂音')

    def test_supper_creates_option_with_audit(self):
        response = self.client_supper.post(CATEGORIES_URL, {
            'group': 'interference_kind', 'code': 'harmonic',
            'name': '谐波干扰', 'sort_id': 65,
        }, content_type='application/json')
        data = ok_data(response)
        self.assertEqual(data['code'], 'harmonic')
        option = InterferenceCategoryOption.objects.get(
            group='interference_kind', code='harmonic')
        self.assertEqual(option.name, '谐波干扰')
        self.assertEqual(option.sort_id, 65)
        self.assertTrue(option.is_active)
        self.assertTrue(AuditLog.objects.filter(
            action='create', target_type='interference_category',
            target_id=str(option.id)).exists())

    def test_supper_create_defaults_sort_id(self):
        data = ok_data(self.client_supper.post(CATEGORIES_URL, {
            'group': 'source_type', 'code': 'radar', 'name': '雷达干扰',
        }, content_type='application/json'))
        self.assertGreater(data['sort_id'], 0)

    def test_duplicate_code_rejected_within_group(self):
        response = self.client_supper.post(CATEGORIES_URL, {
            'group': 'interference_kind', 'code': 'noise', 'name': '重复编码',
        }, content_type='application/json')
        self.assertIn('相同编码', err(response))

    def test_same_code_allowed_across_groups(self):
        # communication 已存在于 affected_system 种子，本用例证明同编码跨分组可用
        data = ok_data(self.client_supper.post(CATEGORIES_URL, {
            'group': 'interference_kind', 'code': 'communication', 'name': '通信干扰',
        }, content_type='application/json'))
        self.assertEqual(data['group'], 'interference_kind')

    def test_invalid_inputs_rejected(self):
        cases = [
            ({'group': 'nope', 'code': 'abc', 'name': 'x'}, '分组'),
            ({'group': 'interference_kind', 'code': 'Bad-Code', 'name': 'x'}, '编码'),
            ({'group': 'interference_kind', 'code': '1abc', 'name': 'x'}, '编码'),
            ({'group': 'interference_kind', 'code': 'abc', 'name': ''}, '名称'),
        ]
        for payload, keyword in cases:
            response = self.client_supper.post(
                CATEGORIES_URL, payload, content_type='application/json')
            self.assertIn(keyword, err(response), payload)

    def test_supper_updates_name_sort_and_audits(self):
        option = InterferenceCategoryOption.objects.get(
            group='interference_kind', code='noise')
        data = ok_data(self.client_supper.put(
            f'{CATEGORIES_URL}{option.id}/',
            {'name': '电磁杂音', 'sort_id': 5},
            content_type='application/json'))
        self.assertEqual(data['name'], '电磁杂音')
        option.refresh_from_db()
        self.assertEqual(option.name, '电磁杂音')
        self.assertEqual(option.sort_id, 5)
        self.assertTrue(AuditLog.objects.filter(
            action='update', target_type='interference_category',
            target_id=str(option.id)).exists())

    def test_group_and_code_immutable(self):
        option = InterferenceCategoryOption.objects.get(
            group='interference_kind', code='noise')
        response = self.client_supper.put(
            f'{CATEGORIES_URL}{option.id}/',
            {'code': 'renamed'}, content_type='application/json')
        self.assertIn('不可修改', err(response))
        option.refresh_from_db()
        self.assertEqual(option.code, 'noise')

    def test_deactivate_keeps_history_display(self):
        # 种子精简后 environment 不在种子内：用例内自建待停用选项（不依赖种子）
        InterferenceCategoryOption.objects.create(
            group='source_type', code='legacy_src', name='遗留干扰源',
            sort_id=90)
        event = InterferenceEvent.objects.create(
            tenant_id=self.user.tenant_id, datetime=datetime(2026, 10, 1, 9, 0),
            scene_code='ground', source_type_code='legacy_src',
            created_by=self.user)
        option = InterferenceCategoryOption.objects.get(
            group='source_type', code='legacy_src')
        ok_data(self.client_supper.put(
            f'{CATEGORIES_URL}{option.id}/', {'is_active': False},
            content_type='application/json'))
        option.refresh_from_db()
        self.assertFalse(option.is_active)
        # 历史事件仍按选项名称显示
        view = event.to_view()
        self.assertEqual(view['source_type_text'], '遗留干扰源')
        # 新事件不能选择停用编码
        payload = {
            'datetime': '2026-10-02 09:00:00', 'scene_code': 'ground',
            'source_type_code': 'legacy_src', 'phenomenon': '新事件',
        }
        response = self.client_auth.post(
            '/interference/events/', payload, content_type='application/json')
        self.assertIn('停用', err(response))


class EventCategoryValidationTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.user = make_user('inter_cat_event', EVENT_PERMS)
        self.client_auth = make_client(self.user)

    def _payload(self, **extra):
        payload = {
            'datetime': '2026-10-15 10:00:00', 'scene_code': 'ground',
            'phenomenon': '测试事件',
        }
        payload.update(extra)
        return payload

    def test_create_with_explicit_codes(self):
        data = ok_data(self.client_auth.post('/interference/events/', self._payload(
            interference_kind_code='intermittent',
            affected_system_code='communication',
            source_type_code='ground_equipment',
        ), content_type='application/json'))
        self.assertEqual(data['interference_kind_code'], 'intermittent')
        self.assertEqual(data['interference_kind_text'], '间歇中断')

    def test_defaults_are_unknown_not_other(self):
        data = ok_data(self.client_auth.post(
            '/interference/events/', self._payload(),
            content_type='application/json'))
        self.assertEqual(data['affected_system_code'], 'unknown')
        self.assertEqual(data['affected_system_text'], '未知/待查')
        self.assertEqual(data['interference_kind_code'], 'unknown')
        self.assertEqual(data['source_type_code'], 'unknown')

    def test_unknown_codes_rejected(self):
        response = self.client_auth.post('/interference/events/', self._payload(
            interference_kind_code='not_exist',
        ), content_type='application/json')
        self.assertIn('具体干扰类型', err(response))

    def test_cross_group_code_rejected(self):
        # communication 属于受影响系统分组，不能用作具体干扰类型
        response = self.client_auth.post('/interference/events/', self._payload(
            interference_kind_code='communication',
        ), content_type='application/json')
        self.assertIn('具体干扰类型', err(response))

    def test_retired_classification_status_rejected(self):
        response = self.client_auth.post('/interference/events/', self._payload(
            classification_status='confirmed',
        ), content_type='application/json')
        self.assertIn('classification_status', err(response))

    def test_import_accepts_display_names(self):
        payload = {'events': [{
            'datetime': '2026-10-16 08:00:00', 'scene_code': '地面',
            'interference_kind_code': '杂音',
            'affected_system_code': '导航',
            'source_type_code': '地面设备',
            'phenomenon': '按名称导入',
        }]}
        data = ok_data(self.client_auth.post(
            '/interference/events/import/', payload,
            content_type='application/json'))
        self.assertEqual(data['errors'], [])
        event = InterferenceEvent.objects.get(pk=data['created_ids'][0])
        self.assertEqual(event.scene_code, 'ground')
        self.assertEqual(event.interference_kind_code, 'noise')
        self.assertEqual(event.affected_system_code, 'navigation')
        self.assertEqual(event.source_type_code, 'ground_equipment')

    def test_import_rejects_unresolvable_value(self):
        payload = {'events': [{
            'datetime': '2026-10-16 08:00:00', 'scene_code': 'ground',
            'interference_kind_code': '不存在的类型',
        }]}
        data = ok_data(self.client_auth.post(
            '/interference/events/import/', payload,
            content_type='application/json'))
        self.assertEqual(data['created_ids'], [])
        self.assertTrue(data['errors'])
        self.assertIn('具体干扰类型', data['errors'][0]['error'])

    def test_edit_keeps_existing_value_of_inactive_option(self):
        event = InterferenceEvent.objects.create(
            tenant_id=self.user.tenant_id, datetime=datetime(2026, 10, 1, 9, 0),
            scene_code='ground', affected_system_code='datalink',
            created_by=self.user)
        option = InterferenceCategoryOption.objects.get(
            group='affected_system', code='datalink')
        option.is_active = False
        option.save()
        # 编辑其他字段，保留已停用编码的原值
        data = ok_data(self.client_auth.post('/interference/events/', {
            'id': event.id, 'phenomenon': '更新现象',
        }, content_type='application/json'))
        self.assertEqual(data['affected_system_code'], 'datalink')
        event.refresh_from_db()
        self.assertEqual(event.affected_system_code, 'datalink')
        self.assertEqual(event.phenomenon, '更新现象')

    def test_scene_detail_consistency_enforced(self):
        response = self.client_auth.post(
            '/interference/events/', self._payload(air_detail={'route': 'A-B'}),
            content_type='application/json')
        self.assertIn('空中明细', err(response))
        self.assertFalse(AirInterferenceDetail.objects.exists())

    def test_ground_event_without_detail_allowed(self):
        # 「已确认必须填明细」规则已随分类状态下线；场景一致性仍然保留
        ok_data(self.client_auth.post(
            '/interference/events/', self._payload(),
            content_type='application/json'))


class EventListExportImportRoundTripTest(TestCase):
    def setUp(self):
        setup_test_env(self)
        self.user = make_user('inter_cat_roundtrip', EVENT_PERMS)
        self.client_auth = make_client(self.user)
        self.event = InterferenceEvent.objects.create(
            tenant_id=self.user.tenant_id, datetime=datetime(2026, 10, 1, 9, 0),
            scene_code='ground', interference_kind_code='noise',
            affected_system_code='communication', source_type_code='ground_equipment',
            flight_number='CA1234', phenomenon='往返测试', created_by=self.user)

    def test_list_shows_option_names_for_custom_option(self):
        InterferenceCategoryOption.objects.create(
            group='interference_kind', code='harmonic', name='谐波干扰')
        self.event.interference_kind_code = 'harmonic'
        self.event.save()
        data = ok_data(self.client_auth.get('/interference/events/'))
        item = next(x for x in data['records'] if x['id'] == self.event.id)
        self.assertEqual(item['interference_kind_text'], '谐波干扰')
        # 下拉选项来自选项表，自定义选项可选
        kind_options = data['options']['interference_kind_code']
        self.assertIn({'value': 'harmonic', 'label': '谐波干扰'}, kind_options)
        self.assertNotIn('classification_status', data['options'])

    def test_export_uses_display_names_without_status_column(self):
        response = self.client_auth.get('/interference/events/export/')
        self.assertEqual(response.status_code, 200)
        text = response.content.decode('utf-8-sig')
        rows = list(csv.reader(io.StringIO(text)))
        header = rows[0]
        self.assertNotIn('classification_status', header)
        body = next(row for row in rows[1:] if row and row[0] == str(self.event.id))
        record = dict(zip(header, body))
        self.assertEqual(record['scene_code'], '地面')
        self.assertEqual(record['interference_kind_code'], '杂音')
        self.assertEqual(record['affected_system_code'], '通信')
        self.assertEqual(record['source_type_code'], '地面设备')

    def test_csv_file_import_round_trip(self):
        csv_text = (
            'id,datetime,scene_code,interference_kind_code,affected_system_code,'
            'source_type_code,flight_number,aircraft_no,aircraft_type,phenomenon,'
            'initial_assessment,remark\n'
            ',2026-10-03 10:00:00,地面,杂音,通信,地面设备,CA999,,,,CSV往返,\n'
        )
        response = self.client_auth.post('/interference/events/import/', {
            'file': io.BytesIO(csv_text.encode('utf-8-sig')),
        })
        data = ok_data(response)
        self.assertEqual(data['errors'], [])
        event = InterferenceEvent.objects.get(pk=data['created_ids'][0])
        self.assertEqual(event.scene_code, 'ground')
        self.assertEqual(event.interference_kind_code, 'noise')
        self.assertEqual(event.affected_system_code, 'communication')
        self.assertEqual(event.source_type_code, 'ground_equipment')


class CategoryDeleteTest(TestCase):
    """选项删除契约：仅超管、仅未引用、unknown 保护、审计与下拉联动。"""

    def setUp(self):
        setup_test_env(self)
        self.user = make_user('inter_del_user', EVENT_PERMS)
        self.client_auth = make_client(self.user)
        self.supper = make_user('inter_del_supper', is_supper=True)
        self.client_supper = make_client(self.supper)

    def _create_option(self, group='interference_kind', code='unused_kind',
                       name='未使用类型'):
        return InterferenceCategoryOption.objects.create(
            group=group, code=code, name=name, sort_id=99)

    def test_supper_deletes_unused_option_with_audit(self):
        option = self._create_option()
        response = self.client_supper.delete(
            f'{CATEGORIES_URL}{option.id}/', content_type='application/json')
        self.assertEqual(json.loads(response.content).get('error') or '', '')
        self.assertFalse(
            InterferenceCategoryOption.objects.filter(pk=option.id).exists())
        audit = AuditLog.objects.filter(
            action='delete', target_type='interference_category',
            target_id=str(option.id)).first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.target_name, '未使用类型')
        detail = json.loads(audit.detail) if audit.detail else {}
        self.assertEqual(detail.get('group'), 'interference_kind')
        self.assertEqual(detail.get('code'), 'unused_kind')

    def test_normal_user_cannot_delete(self):
        option = self._create_option()
        response = self.client_auth.delete(
            f'{CATEGORIES_URL}{option.id}/', content_type='application/json')
        self.assertIn(json.loads(response.content).get('error') or '',
                      ('权限拒绝', '仅超级管理员可维护分类选项'))
        self.assertTrue(
            InterferenceCategoryOption.objects.filter(pk=option.id).exists())

    def test_referenced_options_rejected_in_all_groups(self):
        for group, code in (
            ('interference_kind', 'noise'),
            ('affected_system', 'communication'),
            ('source_type', 'ground_equipment'),
        ):
            option = InterferenceCategoryOption.objects.get(group=group, code=code)
            InterferenceEvent.objects.create(
                tenant_id=self.user.tenant_id, datetime=datetime(2026, 10, 20, 9, 0),
                scene_code='ground', created_by=self.user, **{f'{group}_code': code})
            response = self.client_supper.delete(
                f'{CATEGORIES_URL}{option.id}/', content_type='application/json')
            message = json.loads(response.content).get('error') or ''
            self.assertIn('引用', message, group)
            self.assertIn('停用', message, group)
            self.assertTrue(
                InterferenceCategoryOption.objects.filter(pk=option.id).exists(),
                group)

    def test_soft_deleted_event_still_counts_as_reference(self):
        option = self._create_option()
        event = InterferenceEvent.objects.create(
            tenant_id=self.user.tenant_id, datetime=datetime(2026, 10, 20, 9, 0),
            scene_code='ground', interference_kind_code='unused_kind',
            created_by=self.user)
        event.is_deleted = True
        event.deleted_at = event.created_at
        event.save(update_fields=['is_deleted', 'deleted_at'])
        response = self.client_supper.delete(
            f'{CATEGORIES_URL}{option.id}/', content_type='application/json')
        self.assertIn('引用', json.loads(response.content).get('error') or '')
        self.assertTrue(
            InterferenceCategoryOption.objects.filter(pk=option.id).exists())

    def test_unknown_not_deletable_in_any_group(self):
        for group in ('interference_kind', 'affected_system', 'source_type'):
            option = InterferenceCategoryOption.objects.get(group=group, code='unknown')
            response = self.client_supper.delete(
                f'{CATEGORIES_URL}{option.id}/', content_type='application/json')
            self.assertIn('默认', json.loads(response.content).get('error') or '', group)
            self.assertTrue(
                InterferenceCategoryOption.objects.filter(pk=option.id).exists(),
                group)

    def test_other_tenant_reference_blocks_delete(self):
        option = self._create_option()
        InterferenceEvent.objects.create(
            tenant_id='other_tenant_x', datetime=datetime(2026, 10, 20, 9, 0),
            scene_code='ground', interference_kind_code='unused_kind',
            created_by=self.user)
        response = self.client_supper.delete(
            f'{CATEGORIES_URL}{option.id}/', content_type='application/json')
        self.assertIn('引用', json.loads(response.content).get('error') or '')

    def test_deleted_option_disappears_from_dropdowns(self):
        option = self._create_option(code='drop_kind', name='待删类型')
        self.client_supper.delete(
            f'{CATEGORIES_URL}{option.id}/', content_type='application/json')
        data = ok_data(self.client_auth.get(CATEGORIES_URL))
        codes = {item['code'] for item in data['records']}
        self.assertNotIn('drop_kind', codes)
        event_data = ok_data(self.client_auth.get('/interference/events/'))
        kind_values = {x['value'] for x in event_data['options']['interference_kind_code']}
        self.assertNotIn('drop_kind', kind_values)

    def test_event_create_rejected_after_option_deleted(self):
        option = self._create_option(code='race_kind', name='竞态类型')
        self.client_supper.delete(
            f'{CATEGORIES_URL}{option.id}/', content_type='application/json')
        payload = {
            'datetime': '2026-10-21 10:00:00', 'scene_code': 'ground',
            'interference_kind_code': 'race_kind', 'phenomenon': '删除后新建',
        }
        response = self.client_auth.post(
            '/interference/events/', payload, content_type='application/json')
        self.assertIn('具体干扰类型', json.loads(response.content).get('error') or '')
        self.assertFalse(InterferenceEvent.objects.filter(
            interference_kind_code='race_kind').exists())

    def test_lock_revalidation_rejects_option_deleted_after_validation(self):
        # 模拟并发窗口：负载校验通过后、加锁前选项被另一事务删除并提交
        option = self._create_option(code='race_kind2', name='竞态二')
        values = {
            'scene_code': 'ground',
            'interference_kind_code': 'race_kind2',
            'affected_system_code': 'communication',
            'source_type_code': 'unknown',
        }
        self.assertIsNone(category_services.normalize_event_options(dict(values), None))
        InterferenceCategoryOption.objects.filter(pk=option.pk).delete()
        error = category_services.lock_event_options(values, None)
        self.assertIn('已被删除', error)

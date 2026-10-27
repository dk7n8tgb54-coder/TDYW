# -*- coding: utf-8 -*-
"""Excel 台账新增只使用模板当前在用版本的稳定契约（2026-10-19）。

业务规则：同一模板可有多个迭代版本，新增台账与按期生成只能使用该模板
当前在用的已发布版本（模板内最大 version_no）；旧版本仅供历史追溯。

真实执行 HTTP → View → Service → Model 链路（Docker + 隔离测试库）：
1. available 接口每个模板只返回当前在用版本（旧版本不进入创建入口）；
2. 用当前版本创建成功，且存在未发布新草稿时仍用当前已发布版本；
3. 绕过前端提交旧版本 ID：后端独立校验并拒绝，返回明确业务错误，
   不产生台账（手工新增与批量生成同一规则）；
4. 模板停用后其版本一律不能用于新增；
5. 批量生成（period-generate）固定使用最新已发布版本；
6. 旧版本台账不受新版本影响：发布新版本后仍可填写、完成、导出，
   详情与导出继续走创建时的版本快照。
"""
import io
import json
import shutil
import tempfile
import uuid
from datetime import datetime
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from openpyxl import load_workbook

from apps.equipment_lifecycle import ledger_period_services
from apps.equipment_lifecycle.excel_models import (
    OperationLedgerExcelRecord,
    OperationLedgerExcelTemplateVersion,
)
from apps.equipment_lifecycle.excel_sample_template import build_acceptance_sample_xlsx
from apps.equipment_lifecycle.models import OperationLedger
from apps.equipment_lifecycle.tests.base import URL_PREFIX, make_client, make_system, make_user
from apps.equipment_lifecycle.tests.stable_contract.ledger_base import (
    ALL_LEDGER_PERMS,
    ALL_TEMPLATE_PERMS,
)

TPL_URL = URL_PREFIX + '/excel-templates'
LEDGER_URL = URL_PREFIX + '/excel-ledgers'
GENERATE_URL = URL_PREFIX + '/ledgers/period-generate/'
SHEET_MAIN = '信道维护记录'

P_ALL = ALL_TEMPLATE_PERMS + ALL_LEDGER_PERMS


class CurrentVersionContractBase(TestCase):
    """存储隔离 + 权限用户夹具（模板管理与台账操作同权）。

    user/client 须在 setUp 创建：setUpTestData 赋 self.client 会被 Django
    TestCase 每测试重建的 client 覆盖，导致全部请求 401。
    """

    def setUp(self):
        self.user = make_user('cur_ver_op_%s' % uuid.uuid4().hex[:8], perms=P_ALL)
        self.client = make_client(self.user)
        self._storage_dir = tempfile.mkdtemp(prefix='el_cur_ver_test_')
        self._override = override_settings(EL_EXCEL_TEMPLATE_BASE_DIR=self._storage_dir)
        self._override.enable()
        self.addCleanup(self._override.disable)
        self.addCleanup(shutil.rmtree, self._storage_dir, ignore_errors=True)

    # ---------- 模板夹具（全部走真实接口） ----------

    def make_binding(self, coordinate, field_name):
        return {
            'field_id': str(uuid.uuid4()), 'sheet_name': SHEET_MAIN,
            'cell_coordinate': coordinate, 'field_name': field_name,
            'input_type': 'status', 'is_required': True, 'unit': '', 'options': [],
        }

    def upload_template(self, name='信道Excel维护台账', ledger_type='week_month'):
        response = self.client.post(TPL_URL + '/', {
            'file': SimpleUploadedFile('channel.xlsx', build_acceptance_sample_xlsx()),
            'name': name, 'ledger_type': ledger_type,
        })
        payload = response.json()
        self.assertEqual(payload.get('error', ''), '')
        return payload['data']['data']

    def save_bindings(self, template_id, bindings):
        response = self.client.put('%s/%s/bindings/' % (TPL_URL, template_id),
                                   json.dumps({'field_bindings': bindings}),
                                   content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')

    def publish(self, template_id):
        """发布当前草稿为新版本，返回版本 dict。"""
        response = self.client.post('%s/%s/publish/' % (TPL_URL, template_id))
        payload = response.json()
        self.assertEqual(payload.get('error', ''), '')
        return payload['data']['data']

    def publish_new_iteration(self, template_id, coordinate='F4', field_name='BB模块'):
        """上传新草稿 → 绑定 → 发布（产生下一个迭代版本）。"""
        response = self.client.post('%s/%s/draft-file/' % (TPL_URL, template_id), {
            'file': SimpleUploadedFile('channel.xlsx', build_acceptance_sample_xlsx())})
        self.assertEqual(response.json().get('error', ''), '')
        self.save_bindings(template_id, [self.make_binding(coordinate, field_name)])
        return self.publish(template_id)

    def fetch_available(self, ledger_type='week_month'):
        response = self.client.get(
            TPL_URL + '/available/?ledger_type=' + ledger_type)
        return response.json()['data']['data']

    def create_ledger(self, version_id, **kwargs):
        body = {'version_id': version_id, 'ledger_type': 'week_month'}
        body.update(kwargs)
        return self.client.post(LEDGER_URL + '/', json.dumps(body),
                                content_type='application/json')


class AvailableOnlyCurrentVersionTests(CurrentVersionContractBase):
    """available 接口：每个启用模板只暴露当前在用版本。"""

    def test_multiple_published_versions_only_current_exposed(self):
        template = self.upload_template()
        self.save_bindings(template['id'], [self.make_binding('C4', 'PS模块')])
        v1 = self.publish(template['id'])
        v2 = self.publish_new_iteration(template['id'])
        self.assertEqual(v2['version_no'], 2)
        data = self.fetch_available()
        self.assertEqual([t['id'] for t in data], [template['id']])
        versions = data[0]['versions']
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0]['id'], v2['id'])
        self.assertEqual(versions[0]['version_no'], 2)

    def test_unpublished_draft_not_exposed(self):
        """已发布新草稿（未发布）不影响可用版本：仍只暴露当前已发布版本。"""
        template = self.upload_template()
        self.save_bindings(template['id'], [self.make_binding('C4', 'PS模块')])
        v1 = self.publish(template['id'])
        # 上传新草稿并绑定（未发布）
        response = self.client.post('%s/%s/draft-file/' % (TPL_URL, template['id']), {
            'file': SimpleUploadedFile('channel.xlsx', build_acceptance_sample_xlsx())})
        self.assertEqual(response.json().get('error', ''), '')
        self.save_bindings(template['id'], [self.make_binding('F4', 'BB模块')])
        data = self.fetch_available()
        versions = data[0]['versions']
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0]['id'], v1['id'])
        self.assertEqual(versions[0]['version_no'], 1)


class CreateUsesCurrentVersionTests(CurrentVersionContractBase):
    """手工新增：只接受当前在用版本，旧版本后端独立拒绝。"""

    def test_create_with_current_version_succeeds(self):
        template = self.upload_template()
        self.save_bindings(template['id'], [self.make_binding('C4', 'PS模块')])
        v1 = self.publish(template['id'])
        v2 = self.publish_new_iteration(template['id'])
        response = self.create_ledger(v2['id'])
        payload = response.json()
        self.assertEqual(payload.get('error', ''), '')
        record = OperationLedgerExcelRecord.objects.get(ledger=payload['data']['data']['id'])
        self.assertEqual(record.version_id, v2['id'])

    def test_create_with_old_version_rejected(self):
        """绕过前端提交旧版本 ID：拒绝且不产生台账。"""
        template = self.upload_template()
        self.save_bindings(template['id'], [self.make_binding('C4', 'PS模块')])
        v1 = self.publish(template['id'])
        v2 = self.publish_new_iteration(template['id'])
        before = OperationLedger.objects.count()
        response = self.create_ledger(v1['id'])
        payload = response.json()
        self.assertTrue(payload.get('error'), payload)
        self.assertIn('当前', payload['error'])
        self.assertIn('不能用于新台账', payload['error'])
        self.assertEqual(OperationLedger.objects.count(), before)
        self.assertFalse(
            OperationLedgerExcelRecord.objects.filter(version_id=v1['id']).exists())

    def test_create_with_old_version_rejected_without_prior_ledger(self):
        """从未用 v1 创建过台账时，提交 v1 同样被拒（校验不依赖台账存在）。"""
        template = self.upload_template()
        self.save_bindings(template['id'], [self.make_binding('C4', 'PS模块')])
        self.publish(template['id'])
        v2 = self.publish_new_iteration(template['id'])
        self.assertEqual(OperationLedger.objects.count(), 0)
        response = self.create_ledger(
            OperationLedgerExcelTemplateVersion.objects.get(
                template_id=template['id'], version_no=1).id)
        self.assertTrue(response.json().get('error'), response.json())
        self.assertEqual(OperationLedger.objects.count(), 0)

    def test_unpublished_draft_does_not_block_create_on_current(self):
        """存在未发布新草稿时，当前已发布版本创建不受影响，台账绑定当前版本。"""
        template = self.upload_template()
        self.save_bindings(template['id'], [self.make_binding('C4', 'PS模块')])
        v1 = self.publish(template['id'])
        response = self.client.post('%s/%s/draft-file/' % (TPL_URL, template['id']), {
            'file': SimpleUploadedFile('channel.xlsx', build_acceptance_sample_xlsx())})
        self.assertEqual(response.json().get('error', ''), '')
        self.save_bindings(template['id'], [self.make_binding('F4', 'BB模块')])
        response = self.create_ledger(v1['id'])
        payload = response.json()
        self.assertEqual(payload.get('error', ''), '')
        record = OperationLedgerExcelRecord.objects.get(ledger=payload['data']['data']['id'])
        self.assertEqual(record.version_id, v1['id'])

    def test_inactive_template_version_rejected(self):
        template = self.upload_template()
        self.save_bindings(template['id'], [self.make_binding('C4', 'PS模块')])
        v1 = self.publish(template['id'])
        self.client.post('%s/%s/deactivate/' % (TPL_URL, template['id']))
        response = self.create_ledger(v1['id'])
        self.assertIn('已停用', response.json()['error'])
        self.assertEqual(OperationLedger.objects.count(), 0)


class PeriodGenerateUsesCurrentVersionTests(CurrentVersionContractBase):
    """批量生成：发布新版本后，生成本期应填台账统一使用新版本。"""

    def test_generate_uses_newest_published_version(self):
        system = make_system(self.user, system_code='SYS-CV', name='当前版本系统')
        template = self.upload_template()
        self.save_bindings(template['id'], [self.make_binding('C4', 'PS模块')])
        self.publish(template['id'])
        v2 = self.publish_new_iteration(template['id'])
        response = self.client.put(
            '%s/%s/generation-config/' % (TPL_URL, template['id']),
            json.dumps({'system': system.id, 'generation_period': 'monthly'}),
            content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')
        with mock.patch.object(
                ledger_period_services.timezone, 'now',
                return_value=datetime(2026, 10, 19, 10, 0, 0)):
            result = self.client.post(
                GENERATE_URL,
                json.dumps({'ledger_type': 'week_month',
                            'maintenance_cycles': ['weekly', 'monthly'],
                            'template_ids': [template['id']],
                            'template_kinds': ['excel']}),
                content_type='application/json').json()
        self.assertEqual(result.get('error', ''), '')
        created = result['data']['created']
        self.assertEqual(len(created), 1)
        self.assertEqual(created[0]['version_no'], v2['version_no'])
        record = OperationLedgerExcelRecord.objects.get(ledger=created[0]['id'])
        self.assertEqual(record.version_id, v2['id'])

    def test_rebuild_uses_newest_published_version(self):
        """补建（已作废槽位）同样固定使用最新已发布版本。"""
        system = make_system(self.user, system_code='SYS-RB', name='补建系统')
        template = self.upload_template()
        self.save_bindings(template['id'], [self.make_binding('C4', 'PS模块')])
        v1 = self.publish(template['id'])
        v2 = self.publish_new_iteration(template['id'])
        response = self.client.put(
            '%s/%s/generation-config/' % (TPL_URL, template['id']),
            json.dumps({'system': system.id, 'generation_period': 'monthly'}),
            content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')
        today_patch = mock.patch.object(
            ledger_period_services.timezone, 'now',
            return_value=datetime(2026, 10, 19, 10, 0, 0))
        with today_patch:
            first = self.client.post(
                GENERATE_URL,
                json.dumps({'ledger_type': 'week_month',
                            'maintenance_cycles': ['weekly', 'monthly'],
                            'template_ids': [template['id']],
                            'template_kinds': ['excel']}),
                content_type='application/json').json()
            self.assertEqual(first.get('error', ''), '')
            ledger_id = first['data']['created'][0]['id']
            # 作废首张台账释放槽位（正式台账作废端点）
            void = self.client.post(
                '%s/ledgers/%s/void/' % (URL_PREFIX, ledger_id),
                json.dumps({'reason': '测试作废'}), content_type='application/json')
            self.assertEqual(void.json().get('error', ''), '')
            # 模板发布过 v1/v2，补建应使用 v2
            rebuild = self.client.post(
                '%s/ledgers/period-generate/rebuild/' % URL_PREFIX,
                json.dumps({'template_id': template['id']}),
                content_type='application/json').json()
        self.assertEqual(rebuild.get('error', ''), '')
        row = rebuild['data']
        self.assertEqual(row['version_no'], v2['version_no'])
        record = OperationLedgerExcelRecord.objects.get(ledger=row['id'])
        self.assertEqual(record.version_id, v2['id'])


class OldLedgerKeepsVersionTests(CurrentVersionContractBase):
    """旧版本台账不受新版本发布影响：填写、完成、导出照常。"""

    def test_old_ledger_fill_complete_export_after_new_publish(self):
        template = self.upload_template()
        bindings = [self.make_binding('C4', 'PS模块'),
                    self.make_binding('H4', '备注')]
        bindings[1]['input_type'] = 'text'
        bindings[1]['is_required'] = False
        self.save_bindings(template['id'], bindings)
        v1 = self.publish(template['id'])
        response = self.create_ledger(v1['id'])
        ledger = response.json()['data']['data']
        ledger_id = ledger['id']
        values = {bindings[0]['field_id']: '正常', bindings[1]['field_id']: '阻抗正常'}
        response = self.client.put('%s/%s/' % (LEDGER_URL, ledger_id),
                                   json.dumps({'values': values}),
                                   content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')
        # 发布 v2 后，旧 v1 台账仍可完成填写并导出
        v2 = self.publish_new_iteration(template['id'])
        self.assertEqual(v2['version_no'], 2)
        response = self.client.post('%s/%s/complete/' % (LEDGER_URL, ledger_id))
        self.assertEqual(response.json().get('error', ''), '')
        detail = self.client.get('%s/%s/' % (LEDGER_URL, ledger_id)).json()['data']['data']
        self.assertEqual(detail['excel']['version']['version_no'], 1)
        self.assertEqual(detail['excel']['values'][bindings[0]['field_id']], '正常')
        response = self.client.post('%s/%s/export/excel/' % (LEDGER_URL, ledger_id))
        workbook = load_workbook(filename=io.BytesIO(response.content))
        self.assertEqual(workbook[SHEET_MAIN]['C4'].value, '正常')
        self.assertEqual(workbook[SHEET_MAIN]['H4'].value, '阻抗正常')

    def test_new_publish_does_not_touch_unfinished_old_draft(self):
        """发布新版本不得悄悄改变未完成旧草稿的内容（填写值保持）。"""
        template = self.upload_template()
        bindings = [self.make_binding('C4', 'PS模块')]
        self.save_bindings(template['id'], bindings)
        v1 = self.publish(template['id'])
        response = self.create_ledger(v1['id'])
        ledger_id = response.json()['data']['data']['id']
        values = {bindings[0]['field_id']: '正常'}
        self.client.put('%s/%s/' % (LEDGER_URL, ledger_id),
                        json.dumps({'values': values}),
                        content_type='application/json')
        self.publish_new_iteration(template['id'])
        detail = self.client.get('%s/%s/' % (LEDGER_URL, ledger_id)).json()['data']['data']
        self.assertEqual(detail['excel']['version']['version_no'], 1)
        self.assertEqual(detail['excel']['values'][bindings[0]['field_id']], '正常')
        self.assertEqual(detail['status'], 'draft')

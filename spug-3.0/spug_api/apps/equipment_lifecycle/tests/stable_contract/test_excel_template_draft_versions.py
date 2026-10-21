# -*- coding: utf-8 -*-
"""Excel 模板草稿状态 + 历史版本只读查看/复制为新草稿稳定契约（2026-10-21）。

覆盖任务书「已发布版本不可变 / 当前草稿独立编辑 / 历史版本可查看可复制」
验收项（真实 HTTP 路径 URL→View→Service→Model + 真实文件副作用）：

1. 版本详情读取：布局/绑定/PDF 参数快照与模板名称快照、分页计划；
2. 跨租户访问版本详情、版本预览、版本源文件、复制一律按不存在拒绝；
3. 无 edit 权限复制被拒绝；停用模板不能复制；不存在版本不能复制；
4. 复制历史版本为新草稿：草稿文件字节、哈希、布局、绑定、打印参数与
   该版本快照一致，草稿更新时间/更新人刷新；历史版本行与其版本文件
   不变；不产生新发布版本；
5. 复制写入审计（action_kind + 来源版本号）；
6. 数据库写入失败时不返回成功，且草稿文件还原为复制前字节；
7. 历史版本 PDF 预览使用版本自身源文件/布局/绑定/参数，不改当前草稿；
8. 历史版本源文件下载返回该版本文件字节；
9. 模板详情的 draft_state：无版本/完全一致/基于版本后有修改/无法确认
   四种关系（含多版本同源文件时不猜测来源）；
10. 旧口径版本快照（统一打印布局改造前：print 段缺 scale/page_margins/
    print_area、列宽范围列漏记）复制为新草稿后，草稿分页计划与版本
    详情完全一致（读取端修正对称），不出现"草稿 2 页、版本查看 1 页"。
"""
import hashlib
import io
import json
import uuid
from unittest import mock, skipUnless

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from openpyxl import Workbook

from apps.equipment_lifecycle import excel_template_storage
from apps.equipment_lifecycle.excel_models import (
    OperationLedgerExcelTemplate,
    OperationLedgerExcelTemplateVersion,
)
from apps.equipment_lifecycle.excel_pdf_service import detect_soffice
from apps.equipment_lifecycle.tests.base import make_client, make_user
from apps.equipment_lifecycle.tests.stable_contract.test_excel_ledger_templates import (
    P_TPL,
    TPL_URL,
    ExcelLedgerContractBase,
)
from apps.logs.models import AuditLog

AUDIT_TARGET = 'el_ledger_excel_template'


def build_other_workbook():
    """第二个源文件（与验收样例不同字节，用于制造草稿/版本来源差异）。"""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = '其它维护表'
    sheet['A1'] = '其它维护表'
    sheet['A2'] = '设备'
    sheet['B2'] = '状态'
    sheet['B4'] = ''
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


class TemplateDraftVersionContractTests(ExcelLedgerContractBase):
    """草稿状态、历史版本只读查看与复制为新草稿。"""

    def detail(self, template_id, client=None):
        response = (client or self.owner_client).get(
            '%s/%s/' % (TPL_URL, template_id))
        self.assertEqual(response.json().get('error', ''), '')
        return response.json()['data']['data']

    def version_detail(self, template_id, version_no, client=None):
        response = (client or self.owner_client).get(
            '%s/%s/versions/%s/' % (TPL_URL, template_id, version_no))
        return response.json()

    def copy_to_draft(self, template_id, version_no, client=None):
        client = client or self.owner_client
        return client.post('%s/%s/versions/%s/copy-to-draft/'
                           % (TPL_URL, template_id, version_no))

    def draft_bytes(self, template_id):
        return excel_template_storage.read_source(
            excel_template_storage.draft_path(template_id))

    def version_bytes(self, template_id, version_no):
        return excel_template_storage.read_source(
            excel_template_storage.version_path(template_id, version_no))

    def version_row(self, template_id, version_no):
        return OperationLedgerExcelTemplateVersion.objects.get(
            template_id=template_id, version_no=version_no)

    # ==================== 版本详情读取与边界 ====================

    def test_version_detail_returns_snapshot_content(self):
        template, version, bindings = self.create_published_version()
        payload = self.version_detail(template['id'], 1)['data']['data']
        self.assertEqual(payload['template_name'], template['name'])
        self.assertEqual(payload['source_filename'], 'channel.xlsx')
        self.assertEqual(payload['field_count'], 3)
        self.assertEqual(len(payload['bindings']), 3)
        self.assertEqual(
            sorted(b['field_id'] for b in payload['bindings']),
            sorted(b['field_id'] for b in bindings))
        self.assertEqual(payload['layout']['sheets'][0]['name'], '信道维护记录')
        self.assertIn('pdf_params', payload)
        self.assertTrue(payload['print_plan'], '版本详情须携带统一打印计划')

    def test_version_detail_cross_tenant_rejected(self):
        template, version, bindings = self.create_published_version()
        payload = self.version_detail(template['id'], 1, self.other_client)
        self.assertEqual(payload.get('error'), 'Excel台账模板不存在')

    # ==================== 复制为新草稿：校验边界 ====================

    def test_copy_requires_edit_permission(self):
        template, version, bindings = self.create_published_version()
        before = self.detail(template['id'])['draft']
        viewer = make_user('excel_view_%s' % uuid.uuid4().hex[:8],
                           perms=['equipment_lifecycle.ledger_template.view'])
        payload = self.copy_to_draft(
            template['id'], 1, make_client(viewer)).json()
        self.assertEqual(payload.get('error'), '权限拒绝')
        # 权限拒绝不产生任何草稿变更
        after = self.detail(template['id'])['draft']
        self.assertEqual(after['source_hash'], before['source_hash'])
        self.assertEqual(after['draft_updated_at'], before['draft_updated_at'])
        self.assertEqual(
            sorted(b['field_id'] for b in after['field_bindings']),
            sorted(b['field_id'] for b in before['field_bindings']))

    def test_copy_cross_tenant_rejected(self):
        template, version, bindings = self.create_published_version()
        payload = self.copy_to_draft(
            template['id'], 1, self.other_client).json()
        self.assertEqual(payload.get('error'), 'Excel台账模板不存在')

    def test_copy_blocked_when_template_inactive(self):
        template, version, bindings = self.create_published_version()
        deleter = make_user(
            'excel_del_%s' % uuid.uuid4().hex[:8],
            perms=P_TPL + ['equipment_lifecycle.ledger_template.del'])
        response = make_client(deleter).post(
            '%s/%s/deactivate/' % (TPL_URL, template['id']))
        self.assertEqual(response.json().get('error', ''), '')
        payload = self.copy_to_draft(template['id'], 1).json()
        self.assertIn('停用', payload['error'])

    def test_copy_unknown_version_rejected(self):
        template, version, bindings = self.create_published_version()
        payload = self.copy_to_draft(template['id'], 9).json()
        self.assertEqual(payload.get('error'), '模板版本不存在')

    def test_copied_legacy_snapshot_draft_pagination_matches_version(self):
        """旧口径版本快照复制为草稿后，网页分页与版本查看完全一致。

        模拟统一打印布局（2026-10-21）之前的快照格式：print 段缺
        scale/page_margins/print_area、列宽为旧解析的漏记值。复制后
        草稿的 print_plan 必须与版本详情一致（两侧都以源文件做读取端
        修正）；否则出现"草稿 2 页、版本查看 1 页"的口径分裂。
        """
        template, version, bindings = self.create_published_version()
        template_id = template['id']
        v1 = self.version_row(template_id, 1)
        legacy = json.loads(v1.layout)
        for sheet in legacy['layout']['sheets']:
            print_cfg = dict(sheet.get('print') or {})
            for key in ('scale', 'page_margins', 'print_area'):
                print_cfg.pop(key, None)
            sheet['print'] = print_cfg
            sheet['column_widths'] = {
                letter: round(float(width) / 2, 2)
                for letter, width in (sheet.get('column_widths') or {}).items()}
        legacy_json = json.dumps(legacy, ensure_ascii=False, separators=(',', ':'))
        OperationLedgerExcelTemplateVersion.objects.filter(pk=v1.pk).update(
            layout=legacy_json)

        payload = self.copy_to_draft(template_id, 1).json()
        self.assertEqual(payload.get('error', ''), '', payload)
        draft_plan = payload['data']['data']['draft']['print_plan']
        version_plan = self.version_detail(
            template_id, 1)['data']['data']['print_plan']
        self.assertTrue(draft_plan, '复制后的草稿须携带统一打印计划')
        self.assertTrue(version_plan, '版本详情须携带统一打印计划')
        self.assertEqual(draft_plan, version_plan)
        # 历史版本快照本身不变（复制不回写旧口径快照）
        self.assertEqual(self.version_row(template_id, 1).layout, legacy_json)

    # ==================== 复制为新草稿：内容与不可变 ====================

    def test_copy_version_replaces_draft_and_keeps_version_immutable(self):
        template, version, bindings = self.create_published_version()
        template_id = template['id']
        v1_before = self.version_row(template_id, 1)
        v1_snapshot = {
            'layout': v1_before.layout,
            'bindings': v1_before.bindings,
            'source_hash': v1_before.source_hash,
            'published_at': v1_before.published_at,
        }
        v1_file = self.version_bytes(template_id, 1)
        # 制造与 v1 不同的当前草稿：换打印参数 + 只保留一个绑定
        response = self.owner_client.put(
            '%s/%s/pdf-params/' % (TPL_URL, template_id),
            json.dumps({'pdf_params': {'paper_size': 'A3',
                                       'orientation': 'landscape'}}),
            content_type='application/json')
        self.assertEqual(response.json().get('error', ''), '')
        response = self.save_bindings(
            template_id, [self.make_binding('C4', '仅保留一个字段')])
        self.assertEqual(response.json().get('error', ''), '')
        changed = self.detail(template_id)
        self.assertEqual(changed['draft_state']['relation'], 'modified')

        payload = self.copy_to_draft(template_id, 1).json()
        self.assertEqual(payload.get('error', ''), '', payload)

        # 返回的详情 = 复制后的草稿（源文件/参数/绑定均为 v1 快照）
        detail = payload['data']['data']
        copied = detail['draft']
        self.assertEqual(copied['source_filename'], 'channel.xlsx')
        self.assertEqual(copied['source_hash'], v1_snapshot['source_hash'])
        self.assertEqual(copied['pdf_params']['paper_size'], 'A4')
        self.assertEqual(copied['pdf_params']['orientation'], 'portrait')
        self.assertEqual(len(copied['field_bindings']), 3)
        self.assertEqual(detail['draft_state']['relation'], 'identical')
        self.assertEqual(detail['draft_state']['based_on_version_no'], 1)
        self.assertFalse(detail['draft_state']['differs_from_latest'])
        self.assertEqual(detail['draft_state']['updated_by_username'],
                         self.owner.username)

        # 数据库草稿列与版本快照逐项一致；物理草稿文件 = 版本文件
        locked = OperationLedgerExcelTemplate.objects.get(pk=template_id)
        self.assertEqual(locked.draft_source_hash, v1_snapshot['source_hash'])
        self.assertEqual(locked.draft_layout, v1_snapshot['layout'])
        self.assertEqual(locked.draft_bindings, v1_snapshot['bindings'])
        self.assertEqual(locked.draft_updated_by_id, self.owner.id)
        self.assertEqual(self.draft_bytes(template_id), v1_file)
        self.assertEqual(
            hashlib.sha256(self.draft_bytes(template_id)).hexdigest(),
            v1_snapshot['source_hash'])

        # 历史版本行与版本文件不变；不产生新版本
        v1_after = self.version_row(template_id, 1)
        self.assertEqual(v1_after.layout, v1_snapshot['layout'])
        self.assertEqual(v1_after.bindings, v1_snapshot['bindings'])
        self.assertEqual(v1_after.published_at, v1_snapshot['published_at'])
        self.assertEqual(self.version_bytes(template_id, 1), v1_file)
        self.assertEqual(
            OperationLedgerExcelTemplateVersion.objects.filter(
                template_id=template_id).count(), 1)

        # 审计记录来源版本号与动作类型
        log = AuditLog.objects.filter(
            target_type=AUDIT_TARGET, target_id=str(template_id),
            action='update').order_by('-id').first()
        self.assertIsNotNone(log)
        after = json.loads(log.detail)['after']
        self.assertEqual(after['action_kind'], 'copy_version_to_draft')
        self.assertEqual(after['source_version_no'], 1)

    def test_copy_failure_restores_previous_draft_file(self):
        template, version, bindings = self.create_published_version()
        template_id = template['id']
        # 当前草稿替换为另一份源文件（与 v1 不同），记录复制前字节
        other = build_other_workbook()
        response = self.owner_client.post(
            '%s/%s/draft-file/' % (TPL_URL, template_id),
            {'file': SimpleUploadedFile('other.xlsx', other)})
        self.assertEqual(response.json().get('error', ''), '')
        before_file = self.draft_bytes(template_id)
        before_hash = OperationLedgerExcelTemplate.objects.get(
            pk=template_id).draft_source_hash

        failing = Client(raise_request_exception=False)
        failing.defaults['HTTP_X_TOKEN'] = self.owner.access_token
        failing.defaults['HTTP_X_FORWARDED_FOR'] = '127.0.0.1'
        with mock.patch.object(OperationLedgerExcelTemplate, 'save',
                               side_effect=RuntimeError('数据库写入失败')):
            response = failing.post(
                '%s/%s/versions/1/copy-to-draft/' % (TPL_URL, template_id))
        # 失败不得返回成功响应（项目约定：200 + error，data 为空）
        payload = response.json()
        self.assertTrue(payload.get('error'), '复制失败必须返回业务错误')
        self.assertNotIsInstance(payload.get('data'), dict)
        # 草稿文件还原为复制前字节，数据库草稿未变
        self.assertEqual(self.draft_bytes(template_id), before_file)
        self.assertEqual(
            OperationLedgerExcelTemplate.objects.get(
                pk=template_id).draft_source_hash, before_hash)

    # ==================== 历史版本预览与源文件 ====================

    def test_version_preview_uses_version_snapshot_not_draft(self):
        """预览组装必须用版本快照（绑定/参数/版本文件），不是当前草稿。"""
        template, version, bindings = self.create_published_version()
        template_id = template['id']
        v1 = self.version_row(template_id, 1)
        # 草稿改为另一套绑定与打印参数（与 v1 不同）
        self.save_bindings(template_id, [self.make_binding('C4', '草稿单字段')])
        self.owner_client.put(
            '%s/%s/pdf-params/' % (TPL_URL, template_id),
            json.dumps({'pdf_params': {'paper_size': 'A3'}}),
            content_type='application/json')
        draft_file_before = self.draft_bytes(template_id)

        captured = {}

        def fake_preview(meta, source_path, converter=None):
            captured['meta'] = meta
            captured['source_path'] = source_path
            return b'%PDF-1.4 fake preview bytes'

        with mock.patch(
                'apps.equipment_lifecycle.excel_template_manage.preview_blank_pdf',
                side_effect=fake_preview):
            response = self.owner_client.post(
                '%s/%s/versions/1/preview/pdf/' % (TPL_URL, template_id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertEqual(len(captured['meta']['field_bindings']), 3)
        self.assertEqual(captured['meta']['pdf_params']['paper_size'], 'A4')
        self.assertEqual(
            captured['source_path'],
            excel_template_storage.version_path(template_id, 1))
        self.assertEqual(captured['meta']['source_file_hash'], v1.source_hash)
        # 预览不改当前草稿（文件与绑定原样）
        self.assertEqual(self.draft_bytes(template_id), draft_file_before)
        self.assertEqual(
            len(self.detail(template_id)['draft']['field_bindings']), 1)

    def test_version_preview_cross_tenant_and_missing_version(self):
        template, version, bindings = self.create_published_version()
        payload = self.other_client.post(
            '%s/%s/versions/1/preview/pdf/' % (TPL_URL, template['id'])).json()
        self.assertEqual(payload.get('error'), 'Excel台账模板不存在')
        payload = self.owner_client.post(
            '%s/%s/versions/9/preview/pdf/' % (TPL_URL, template['id'])).json()
        self.assertEqual(payload.get('error'), '模板版本不存在')

    @skipUnless(detect_soffice(), 'LibreOffice 不可用（或当前引擎为 chromium）')
    def test_version_preview_real_pdf_keeps_draft(self):
        template, version, bindings = self.create_published_version()
        template_id = template['id']
        draft_file_before = self.draft_bytes(template_id)
        response = self.owner_client.post(
            '%s/%s/versions/1/preview/pdf/' % (TPL_URL, template_id))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertTrue(response.get('X-El-Pdf-Pages'))
        self.assertEqual(self.draft_bytes(template_id), draft_file_before)

    def test_version_source_download_matches_version_file(self):
        template, version, bindings = self.create_published_version()
        response = self.owner_client.get(
            '%s/%s/versions/1/source/' % (TPL_URL, template['id']))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, self.version_bytes(template['id'], 1))
        self.assertIn('channel.xlsx',
                      response['Content-Disposition'].replace('%20', ' '))
        payload = self.other_client.get(
            '%s/%s/versions/1/source/' % (TPL_URL, template['id'])).json()
        self.assertEqual(payload.get('error'), 'Excel台账模板不存在')

    # ==================== 草稿状态（draft_state） ====================

    def test_draft_state_no_versions(self):
        template = self.upload_sample()
        state = self.detail(template['id'])['draft_state']
        self.assertEqual(state['relation'], 'no_versions')
        self.assertEqual(state['latest_version_no'], 0)
        self.assertIsNone(state['differs_from_latest'])
        self.assertEqual(state['binding_count'], 0)
        self.assertEqual(state['updated_by_username'], self.owner.username)

    def test_draft_state_identical_then_modified(self):
        template, version, bindings = self.create_published_version()
        state = self.detail(template['id'])['draft_state']
        self.assertEqual(state['relation'], 'identical')
        self.assertEqual(state['based_on_version_no'], 1)
        self.assertFalse(state['differs_from_latest'])
        self.assertEqual(state['binding_count'], 3)
        # 只改绑定（源文件不变）→ 可判定基于 v1，之后有修改
        self.save_bindings(template['id'],
                           [self.make_binding('C4', '保留一个字段')])
        state = self.detail(template['id'])['draft_state']
        self.assertEqual(state['relation'], 'modified')
        self.assertEqual(state['based_on_version_no'], 1)
        self.assertTrue(state['differs_from_latest'])

    def test_draft_state_unknown_when_source_differs(self):
        template, version, bindings = self.create_published_version()
        response = self.owner_client.post(
            '%s/%s/draft-file/' % (TPL_URL, template['id']),
            {'file': SimpleUploadedFile('other.xlsx', build_other_workbook())})
        self.assertEqual(response.json().get('error', ''), '')
        state = self.detail(template['id'])['draft_state']
        self.assertEqual(state['relation'], 'unknown')
        self.assertIsNone(state['based_on_version_no'])
        self.assertTrue(state['differs_from_latest'])
        self.assertEqual(state['source_filename'], 'other.xlsx')

    def test_draft_state_unknown_when_multiple_versions_share_source(self):
        """多版本同源文件时不猜来源：只能确认"无法判定基于哪个版本"。"""
        template, version, bindings = self.create_published_version()
        template_id = template['id']
        self.publish(template_id)  # v2 与 v1 源文件/内容完全相同
        self.assertEqual(
            self.version_row(template_id, 1).source_hash,
            self.version_row(template_id, 2).source_hash)
        self.save_bindings(template_id,
                           [self.make_binding('C4', '与两个版本都不同')])
        state = self.detail(template_id)['draft_state']
        self.assertEqual(state['relation'], 'unknown')
        self.assertIsNone(state['based_on_version_no'])
        self.assertTrue(state['differs_from_latest'])

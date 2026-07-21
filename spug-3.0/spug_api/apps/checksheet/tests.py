# -*- coding: utf-8 -*-
"""检查表模块测试

覆盖：
- TemplateView：模板列表/创建（含重名校验）
- TemplateDetailView：详情/编辑/删除
- ProjectListView：项目名列表
- RecordListView：检查记录查询/保存（含参数校验）
- SubmissionView：提交批次状态流转（submit/review/reject/close/void + 非法流转被拒）
- export_pdf：权限校验（不测 PDF 内容，依赖 reportlab 字体）
- EvidencePackageView：证据包导出权限
- 权限码：view/edit/template_view/template_add/template_edit/template_del
"""
import json
import tempfile

from django.test import TestCase, override_settings

from apps.checksheet.models import (
    CheckSheetTemplate, CheckSheetRecord, CheckSheetSubmission,
    CheckSheetDailySummary, SUBMISSION_TRANSITIONS,
)
from apps.utils.test_helpers import make_user, make_client, setup_test_env


VIEW_PERMS = ['checksheet.checksheet.view']
EDIT_PERMS = [
    'checksheet.checksheet.view',
    'checksheet.checksheet.edit',
]
TEMPLATE_VIEW_PERMS = [
    'checksheet.checksheet.template_view',
]
TEMPLATE_EDIT_PERMS = [
    'checksheet.checksheet.template_view',
    'checksheet.checksheet.template_add',
    'checksheet.checksheet.template_edit',
    'checksheet.checksheet.template_del',
]


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class TemplateViewTest(TestCase):
    """检查表模板 CRUD 测试"""

    def setUp(self):
        setup_test_env(self)
        self.viewer = make_user('viewer', VIEW_PERMS)
        self.editor = make_user('editor', EDIT_PERMS + TEMPLATE_EDIT_PERMS)
        self.tpl_editor = make_user('tpl_editor', TEMPLATE_EDIT_PERMS)
        self.noperm = make_user('noperm', [])
        self.viewer_client = make_client(self.viewer)
        self.editor_client = make_client(self.editor)
        self.tpl_editor_client = make_client(self.tpl_editor)
        self.noperm_client = make_client(self.noperm)

    def _create_template(self, project='项目A', items=None):
        CheckSheetTemplate.objects.create(
            project=project,
            check_items=json.dumps(items or [{'name': 'item1'}], ensure_ascii=False)
        )

    # ---- 列表 ----

    def test_list_denied_without_perm(self):
        r = self.noperm_client.get('/checksheet/template/')
        self.assertTrue(r.json().get('error'))

    def test_list_ok_with_template_view_perm(self):
        self._create_template()
        r = self.tpl_editor_client.get('/checksheet/template/')
        body = r.json()
        self.assertFalse(body.get('error'))
        self.assertEqual(len(body['data']['templates']), 1)

    def test_list_returns_full_not_paginated(self):
        """P2 修复：模板列表返回全量不分页"""
        for i in range(55):
            self._create_template(project=f'项目{i}')
        r = self.tpl_editor_client.get('/checksheet/template/')
        body = r.json()
        self.assertEqual(len(body['data']['templates']), 55)

    # ---- 创建 ----

    def test_create_template_success(self):
        r = self.editor_client.post(
            '/checksheet/template/',
            data=json.dumps({
                'project': '新项目',
                'check_items': [{'name': '检查项1'}],
            }),
            content_type='application/json',
        )
        self.assertFalse(r.json().get('error'))
        self.assertTrue(CheckSheetTemplate.objects.filter(project='新项目').exists())

    def test_create_template_denied_without_perm(self):
        r = self.viewer_client.post(
            '/checksheet/template/',
            data=json.dumps({'project': 'p', 'check_items': []}),
            content_type='application/json',
        )
        self.assertTrue(r.json().get('error'))

    def test_create_template_duplicate_project_rejected(self):
        """P0-3 修复：重名项目被拒"""
        self._create_template(project='重复项目')
        r = self.editor_client.post(
            '/checksheet/template/',
            data=json.dumps({'project': '重复项目', 'check_items': []}),
            content_type='application/json',
        )
        body = r.json()
        self.assertTrue(body.get('error'))
        self.assertIn('已存在', body['error'])

    def test_create_template_missing_project(self):
        r = self.editor_client.post(
            '/checksheet/template/',
            data=json.dumps({'check_items': []}),
            content_type='application/json',
        )
        self.assertTrue(r.json().get('error'))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class TemplateDetailViewTest(TestCase):
    """模板详情/编辑/删除测试"""

    def setUp(self):
        setup_test_env(self)
        self.editor = make_user('editor', EDIT_PERMS + TEMPLATE_EDIT_PERMS)
        self.viewer = make_user('viewer', TEMPLATE_VIEW_PERMS)
        self.editor_client = make_client(self.editor)
        self.viewer_client = make_client(self.viewer)
        self.template = CheckSheetTemplate.objects.create(
            project='项目A', check_items='[{"name":"item1"}]'
        )

    def test_get_detail_success(self):
        r = self.viewer_client.get(f'/checksheet/template/{self.template.id}/')
        body = r.json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['project'], '项目A')

    def test_get_detail_not_found(self):
        r = self.viewer_client.get('/checksheet/template/99999/')
        self.assertEqual(r.status_code, 404)

    def test_put_edit_template_success(self):
        r = self.editor_client.put(
            f'/checksheet/template/{self.template.id}/',
            data=json.dumps({'project': '项目A改名', 'check_items': [{'name': 'new'}]}),
            content_type='application/json',
        )
        self.assertFalse(r.json().get('error'))
        self.template.refresh_from_db()
        self.assertEqual(self.template.project, '项目A改名')

    def test_put_edit_rename_conflict(self):
        """改名时与其他模板重名被拒"""
        CheckSheetTemplate.objects.create(project='项目B', check_items='[]')
        r = self.editor_client.put(
            f'/checksheet/template/{self.template.id}/',
            data=json.dumps({'project': '项目B'}),
            content_type='application/json',
        )
        self.assertTrue(r.json().get('error'))

    def test_delete_template_success(self):
        r = self.editor_client.delete(f'/checksheet/template/{self.template.id}/')
        self.assertFalse(r.json().get('error'))
        self.assertFalse(CheckSheetTemplate.objects.filter(id=self.template.id).exists())

    def test_delete_template_not_found(self):
        r = self.editor_client.delete('/checksheet/template/99999/')
        self.assertEqual(r.status_code, 404)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ProjectListViewTest(TestCase):
    """项目名列表接口测试"""

    def setUp(self):
        setup_test_env(self)
        self.viewer = make_user('viewer', VIEW_PERMS)
        self.noperm = make_user('noperm', [])
        self.viewer_client = make_client(self.viewer)
        self.noperm_client = make_client(self.noperm)
        for name in ['项目A', '项目B', '项目C']:
            CheckSheetTemplate.objects.create(project=name, check_items='[]')

    def test_list_projects_success(self):
        r = self.viewer_client.get('/checksheet/template/projects/')
        body = r.json()
        self.assertFalse(body.get('error'))
        self.assertEqual(len(body['data']['projects']), 3)

    def test_list_projects_denied(self):
        r = self.noperm_client.get('/checksheet/template/projects/')
        self.assertTrue(r.json().get('error'))


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class RecordListViewTest(TestCase):
    """检查记录查询/保存测试"""

    def setUp(self):
        setup_test_env(self)
        self.editor = make_user('editor', EDIT_PERMS)
        self.viewer = make_user('viewer', VIEW_PERMS)
        self.noperm = make_user('noperm', [])
        self.editor_client = make_client(self.editor)
        self.viewer_client = make_client(self.viewer)
        self.noperm_client = make_client(self.noperm)
        self.template = CheckSheetTemplate.objects.create(
            project='项目A', check_items='[{"name":"item1"},{"name":"item2"}]'
        )

    def _save_records(self, client=None, records=None, day='1'):
        client = client or self.editor_client
        return client.post(
            '/checksheet/record/',
            data=json.dumps({
                'year': '2026', 'month': '07', 'day': day,
                'project': '项目A',
                'records': records or [
                    {'item_index': 0, 'day': 1, 'status': 'NORMAL'},
                    {'item_index': 1, 'day': 1, 'status': 'UNCHECKED'},
                ],
                'signatures': {'operator': '张三'},
                'daily_summary': {'remark': '正常', 'rectification': ''},
            }),
            content_type='application/json',
        )

    # ---- 查询 ----

    def test_get_records_missing_params(self):
        r = self.viewer_client.get('/checksheet/record/?year=2026')
        self.assertEqual(r.status_code, 400)

    def test_get_records_template_not_found(self):
        r = self.viewer_client.get(
            '/checksheet/record/?year=2026&month=07&project=不存在'
        )
        self.assertEqual(r.status_code, 400)

    def test_get_records_success(self):
        self._save_records()
        r = self.viewer_client.get(
            '/checksheet/record/?year=2026&month=07&project=项目A'
        )
        body = r.json()
        self.assertFalse(body.get('error'))
        self.assertEqual(len(body['data']['records']), 2)

    def test_get_records_denied_without_perm(self):
        r = self.noperm_client.get(
            '/checksheet/record/?year=2026&month=07&project=项目A'
        )
        self.assertTrue(r.json().get('error'))

    def test_get_records_invalid_day_type(self):
        """P1-2 修复：day 非整数返回友好错误"""
        r = self.viewer_client.get(
            '/checksheet/record/?year=2026&month=07&project=项目A&day=abc'
        )
        body = r.json()
        self.assertTrue(body.get('error'))
        self.assertIn('整数', body['error'])

    def test_get_records_day_out_of_range(self):
        """day 超出 1-31 范围返回错误"""
        r = self.viewer_client.get(
            '/checksheet/record/?year=2026&month=07&project=项目A&day=32'
        )
        self.assertTrue(r.json().get('error'))

    # ---- 保存 ----

    def test_save_records_success(self):
        r = self._save_records()
        self.assertFalse(r.json().get('error'))
        self.assertEqual(CheckSheetRecord.objects.count(), 2)
        record = CheckSheetRecord.objects.first()
        self.assertEqual(record.status, 'NORMAL')
        self.assertEqual(record.operator, '张三')

    def test_save_records_denied_without_edit_perm(self):
        r = self._save_records(client=self.viewer_client)
        self.assertTrue(r.json().get('error'))

    def test_save_records_too_many_rejected(self):
        """单次提交超过 500 条记录被拒"""
        records = [
            {'item_index': i, 'day': 1, 'status': 'NORMAL'}
            for i in range(501)
        ]
        r = self._save_records(records=records)
        body = r.json()
        self.assertTrue(body.get('error'))
        self.assertIn('500', body['error'])

    def test_save_records_invalid_status_rejected(self):
        """非法 status 值被拒"""
        r = self._save_records(records=[
            {'item_index': 0, 'day': 1, 'status': 'INVALID'},
        ])
        self.assertTrue(r.json().get('error'))

    def test_save_records_invalid_item_index(self):
        """item_index 非整数被拒"""
        r = self._save_records(records=[
            {'item_index': 'abc', 'day': 1, 'status': 'NORMAL'},
        ])
        self.assertTrue(r.json().get('error'))

    def test_save_records_creates_daily_summary(self):
        self._save_records()
        summary = CheckSheetDailySummary.objects.get(year='2026', month='07', day=1)
        self.assertEqual(summary.operator, '张三')
        self.assertEqual(summary.remark, '正常')

    def test_save_records_idempotent_update(self):
        """重复保存同一记录应更新而非新增"""
        self._save_records()
        self._save_records()
        self.assertEqual(CheckSheetRecord.objects.count(), 2)

    def test_save_records_auto_creates_submission(self):
        """保存记录时自动创建 draft 批次"""
        self._save_records()
        sub = CheckSheetSubmission.objects.filter(
            project='项目A', year='2026', month='07'
        ).first()
        self.assertIsNotNone(sub)
        self.assertEqual(sub.status, 'draft')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class SubmissionViewTest(TestCase):
    """提交批次状态流转测试"""

    def setUp(self):
        setup_test_env(self)
        self.editor = make_user('editor', EDIT_PERMS)
        self.viewer = make_user('viewer', VIEW_PERMS)
        self.editor_client = make_client(self.editor)
        self.viewer_client = make_client(self.viewer)
        self.template = CheckSheetTemplate.objects.create(
            project='项目A', check_items='[{"name":"item1"}]'
        )

    def _create_submission(self, status='draft', project='项目A'):
        return CheckSheetSubmission.objects.create(
            tenant_id='admin', project=project, year='2026', month='07',
            status=status,
        )

    def _action(self, action, project='项目A', **extra):
        data = {'project': project, 'year': '2026', 'month': '07', 'action': action}
        data.update(extra)
        return self.editor_client.post(
            '/checksheet/submission/',
            data=json.dumps(data),
            content_type='application/json',
        )

    # ---- 查询 ----

    def test_get_submission_missing_params(self):
        r = self.viewer_client.get('/checksheet/submission/?project=项目A')
        self.assertTrue(r.json().get('error'))

    def test_get_submission_not_exists(self):
        r = self.viewer_client.get(
            '/checksheet/submission/?project=项目A&year=2026&month=07'
        )
        body = r.json()
        self.assertFalse(body.get('error'))
        self.assertFalse(body['data']['exists'])

    def test_get_submission_exists(self):
        sub = self._create_submission()
        r = self.viewer_client.get(
            '/checksheet/submission/?project=项目A&year=2026&month=07'
        )
        body = r.json()
        self.assertTrue(body['data']['exists'])
        self.assertEqual(body['data']['status'], 'draft')

    # ---- 状态流转 ----

    def test_submit_from_draft_ok(self):
        self._create_submission(status='draft')
        r = self._action('submit')
        body = r.json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['status'], 'submitted')

    def test_review_from_submitted_ok(self):
        self._create_submission(status='submitted')
        r = self._action('review', review_comment='通过')
        body = r.json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['status'], 'reviewed')

    def test_reject_from_submitted_to_draft(self):
        self._create_submission(status='submitted')
        r = self._action('reject', review_comment='不通过')
        body = r.json()
        self.assertFalse(body.get('error'))
        self.assertEqual(body['data']['status'], 'draft')

    def test_close_from_reviewed_ok(self):
        self._create_submission(status='reviewed')
        r = self._action('close')
        self.assertEqual(r.json()['data']['status'], 'closed')

    def test_void_from_draft_ok(self):
        self._create_submission(status='draft')
        r = self._action('void', void_reason='填写错误')
        self.assertEqual(r.json()['data']['status'], 'voided')

    def test_void_from_closed_ok(self):
        """closed → voided 合法"""
        self._create_submission(status='closed')
        r = self._action('void', void_reason='归档后发现错误')
        self.assertEqual(r.json()['data']['status'], 'voided')

    def test_invalid_action_rejected(self):
        self._create_submission(status='draft')
        r = self._action('unknown_action')
        self.assertTrue(r.json().get('error'))
        self.assertIn('非法', r.json()['error'])

    def test_invalid_transition_rejected(self):
        """draft → reviewed 非法流转被拒"""
        self._create_submission(status='draft')
        r = self._action('review')
        self.assertTrue(r.json().get('error'))
        self.assertIn('不能转为', r.json()['error'])

    def test_voided_is_terminal(self):
        """voided 是终态，不能再流转"""
        sub = self._create_submission(status='voided')
        for action in ('submit', 'review', 'close'):
            r = self._action(action)
            self.assertTrue(r.json().get('error'), f'{action} 应被拒绝')

    def test_submission_not_exists_rejected(self):
        """批次不存在时操作被拒"""
        r = self._action('submit')
        self.assertTrue(r.json().get('error'))
        self.assertIn('不存在', r.json()['error'])

    def test_submit_sets_snapshot_hash(self):
        """submit 时计算 snapshot_hash"""
        sub = self._create_submission(status='draft')
        # 先保存一条检查记录，让快照有内容
        CheckSheetRecord.objects.create(
            template=self.template, year='2026', month='07', day=1,
            item_index=0, status='NORMAL',
        )
        self._action('submit')
        sub.refresh_from_db()
        self.assertTrue(sub.snapshot_hash)
        self.assertTrue(sub.submitted_by_id)

    def test_review_sets_reviewer(self):
        sub = self._create_submission(status='submitted')
        self._action('review', review_comment='通过')
        sub.refresh_from_db()
        self.assertTrue(sub.reviewed_by_id)
        self.assertEqual(sub.review_comment, '通过')

    def test_void_sets_void_info(self):
        sub = self._create_submission(status='draft')
        self._action('void', void_reason='填写错误')
        sub.refresh_from_db()
        self.assertTrue(sub.voided_by_id)
        self.assertEqual(sub.void_reason, '填写错误')


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class SubmissionTransitionModelTest(TestCase):
    """SUBMISSION_TRANSITIONS 状态机模型测试"""

    def test_draft_can_submit_or_void(self):
        self.assertEqual(SUBMISSION_TRANSITIONS['draft'], {'submitted', 'voided'})

    def test_submitted_can_review_or_reject(self):
        self.assertEqual(SUBMISSION_TRANSITIONS['submitted'], {'reviewed', 'draft'})

    def test_reviewed_can_close_or_reject(self):
        self.assertEqual(SUBMISSION_TRANSITIONS['reviewed'], {'closed', 'draft'})

    def test_closed_can_only_void(self):
        self.assertEqual(SUBMISSION_TRANSITIONS['closed'], {'voided'})

    def test_voided_is_terminal_empty(self):
        self.assertEqual(SUBMISSION_TRANSITIONS['voided'], set())


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ExportPdfViewTest(TestCase):
    """PDF 导出权限测试（不测 PDF 内容）"""

    def setUp(self):
        setup_test_env(self)
        self.editor = make_user('editor', EDIT_PERMS)
        self.viewer = make_user('viewer', VIEW_PERMS)
        self.editor_client = make_client(self.editor)
        self.viewer_client = make_client(self.viewer)

    def test_export_denied_for_view_only(self):
        """导出用 edit 权限（非 view）"""
        r = self.viewer_client.post(
            '/checksheet/export/pdf/',
            data=json.dumps({
                'year': '2026', 'month': '07',
                'table_data': [['表头']], 'daily_summaries': {},
            }),
            content_type='application/json',
        )
        self.assertTrue(r.json().get('error'))

    def test_export_missing_params(self):
        r = self.editor_client.post(
            '/checksheet/export/pdf/',
            data=json.dumps({}),
            content_type='application/json',
        )
        self.assertTrue(r.json().get('error'))

    def test_export_too_many_rows_rejected(self):
        """表格数据超过 500 行被拒"""
        rows = [['x'] for _ in range(501)]
        r = self.editor_client.post(
            '/checksheet/export/pdf/',
            data=json.dumps({
                'year': '2026', 'month': '07',
                'table_data': rows, 'daily_summaries': {},
            }),
            content_type='application/json',
        )
        body = r.json()
        self.assertTrue(body.get('error'))
        self.assertIn('500', body['error'])


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class EvidencePackageViewTest(TestCase):
    """证据包导出测试"""

    def setUp(self):
        setup_test_env(self)
        self.viewer = make_user('viewer', VIEW_PERMS)
        self.noperm = make_user('noperm', [])
        self.viewer_client = make_client(self.viewer)
        self.noperm_client = make_client(self.noperm)
        self.template = CheckSheetTemplate.objects.create(
            project='项目A', check_items='[]'
        )
        self.sub = CheckSheetSubmission.objects.create(
            tenant_id='admin', project='项目A', year='2026', month='07',
            status='submitted',
        )

    def test_export_denied_without_perm(self):
        r = self.noperm_client.get(
            '/checksheet/evidence/package/?project=项目A&year=2026&month=07'
        )
        self.assertTrue(r.json().get('error'))

    def test_export_missing_params(self):
        r = self.viewer_client.get('/checksheet/evidence/package/?project=项目A')
        self.assertTrue(r.json().get('error'))

    def test_export_submission_not_exists(self):
        r = self.viewer_client.get(
            '/checksheet/evidence/package/?project=不存在&year=2026&month=07'
        )
        self.assertTrue(r.json().get('error'))

    def test_export_success_returns_zip(self):
        r = self.viewer_client.get(
            '/checksheet/evidence/package/?project=项目A&year=2026&month=07'
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/zip')
        # Content-Disposition 可能被 RFC 2047 编码（中文文件名），检查解码后含 zip
        import email.header
        disposition = r['Content-Disposition'] or ''
        decoded_parts = email.header.decode_header(disposition)
        decoded = ''.join(
            part.decode(charset or 'utf-8') if isinstance(part, bytes) else part
            for part, charset in decoded_parts
        )
        self.assertIn('attachment', decoded)
        self.assertIn('.zip', decoded)

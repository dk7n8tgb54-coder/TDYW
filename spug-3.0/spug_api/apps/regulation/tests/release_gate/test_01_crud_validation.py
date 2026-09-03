"""R-01 规章 CRUD 与参数/业务校验（stable_contract + defect_reproduction）。

覆盖用户要求：
1. 有效数据创建规章；查询列表和详情
2. 编辑标题、编号、发文单位、业务类型、状态、分类和日期
3. 清空 category_id / publish_date / effective_date 后重新查询数据库确认字段为空
4. 删除规章后确认数据库记录消失、附件记录按设计处理、物理文件清理
5. 不存在的规章 ID 返回明确业务错误，不产生 500
6. 缺少 title / rule_no / status；日期格式非法；非法 status；分类不存在；非叶子分类
7. 编辑时提交空字符串 / null / 未提交字段的语义
8. 重复编号、超长文本、特殊字符和 Unicode 文本
9. 已废止规章重复执行 retire 的幂等性
10. 已废止规章是否允许编辑/上传/删除
"""
import os

from apps.regulation.models import Regulation, RegulationAttachment
from .base import RegulationGateTestCase, PERM_EDIT


class RegulationCreateTests(RegulationGateTestCase):
    """R-01-01 创建规章正向路径"""

    def test_create_minimal_success(self):
        resp = self.create_regulation(title='最小字段规章', rule_no='RG-C-001')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['error'], '')
        reg = Regulation.objects.get(rule_no='RG-C-001')
        self.assertEqual(reg.title, '最小字段规章')
        self.assertEqual(reg.status, Regulation.STATUS_ACTIVE)
        self.assertIsNone(reg.category_id)
        self.assertIsNone(reg.publish_date)
        self.assertIsNone(reg.effective_date)

    def test_create_full_fields_success(self):
        resp = self.create_regulation(
            title='全字段规章', rule_no='RG-C-002',
            category_id=self.leaf_cat.id,
            issuing_authority='国际民航组织',
            biz_type='空管',
            publish_date='2026-01-01',
            effective_date='2026-02-01',
            status='active',
        )
        self.assertEqual(resp.json()['error'], '')
        reg = Regulation.objects.get(rule_no='RG-C-002')
        self.assertEqual(reg.category_id, self.leaf_cat.id)
        self.assertEqual(reg.issuing_authority, '国际民航组织')
        self.assertEqual(reg.biz_type, '空管')
        self.assertEqual(reg.publish_date.isoformat(), '2026-01-01')
        self.assertEqual(reg.effective_date.isoformat(), '2026-02-01')

    def test_create_with_explicit_retired_status(self):
        resp = self.create_regulation(title='直接废止', rule_no='RG-C-003', status='retired')
        self.assertEqual(resp.json()['error'], '')
        self.assertEqual(Regulation.objects.get(rule_no='RG-C-003').status, 'retired')

    def test_create_audit_event_recorded(self):
        self.create_regulation(title='审计校验', rule_no='RG-C-004')
        from apps.logs.models import AuditLog
        log = AuditLog.objects.filter(
            target_type='regulation', action='create', target_name='审计校验').first()
        self.assertIsNotNone(log, '创建规章应产生 create 审计事件')
        self.assertEqual(log.username, self.admin.username)
        self.assertIn('RG-C-004', log.detail or '')


class RegulationReadTests(RegulationGateTestCase):
    """R-01-02 列表与详情查询"""

    def test_list_returns_all(self):
        resp = self.viewer_client.get('/regulation/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['error'], '')
        self.assertEqual(data['data']['total'], 2)
        self.assertEqual(len(data['data']['items']), 2)

    def test_detail_includes_attachments(self):
        self.make_attachment_record(self.regulation, 'detail.pdf')
        resp = self.viewer_client.get(f'/regulation/{self.regulation.id}/')
        data = resp.json()['data']
        self.assertEqual(data['title'], '基准规章')
        self.assertEqual(data['category_name'], '叶子分类')
        self.assertEqual(len(data['attachments']), 1)
        self.assertEqual(data['attachments'][0]['file_name'], 'detail.pdf')

    def test_detail_not_found_returns_business_error(self):
        resp = self.viewer_client.get('/regulation/99999999/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['error'], '规章不存在')

    def test_detail_invalid_id_not_500(self):
        for bad in ('abc', '-1', '1e309'):
            resp = self.viewer_client.get(f'/regulation/{bad}/')
            self.assertNotEqual(resp.status_code, 500, f'非法 ID {bad} 不应 500')
            if resp.status_code == 200:
                self.assertEqual(resp.json()['error'], '规章不存在')


class RegulationUpdateTests(RegulationGateTestCase):
    """R-01-03 编辑：字段更新与清空语义"""

    def test_update_all_editable_fields(self):
        resp = self.admin_client.put(
            f'/regulation/{self.regulation.id}/',
            {
                'title': '改名后',
                'rule_no': 'RG-U-001',
                'issuing_authority': '新单位',
                'biz_type': '新类型',
                'status': 'retired',
                'category_id': self.leaf_cat.id,
                'publish_date': '2026-03-01',
                'effective_date': '2026-04-01',
            },
            content_type='application/json',
        )
        self.assertEqual(resp.json()['error'], '')
        reg = Regulation.objects.get(pk=self.regulation.id)
        self.assertEqual(reg.title, '改名后')
        self.assertEqual(reg.rule_no, 'RG-U-001')
        self.assertEqual(reg.issuing_authority, '新单位')
        self.assertEqual(reg.biz_type, '新类型')
        self.assertEqual(reg.status, 'retired')
        self.assertEqual(reg.publish_date.isoformat(), '2026-03-01')
        self.assertEqual(reg.effective_date.isoformat(), '2026-04-01')
        self.assertIsNotNone(reg.updated_by_id)
        self.assertIsNotNone(reg.updated_at)

    def test_clear_dates_persists_null(self):
        Regulation.objects.filter(pk=self.regulation.id).update(
            publish_date='2026-03-01', effective_date='2026-04-01')
        resp = self.admin_client.put(
            f'/regulation/{self.regulation.id}/',
            {'publish_date': '', 'effective_date': ''},
            content_type='application/json',
        )
        self.assertEqual(resp.json()['error'], '')
        self.regulation.refresh_from_db()
        self.assertIsNone(self.regulation.publish_date, '清空发布日期后必须落库为 NULL')
        self.assertIsNone(self.regulation.effective_date, '清空生效日期后必须落库为 NULL')

    def test_clear_category_persists_null(self):
        self.assertEqual(self.regulation.category_id, self.leaf_cat.id)
        resp = self.admin_client.put(
            f'/regulation/{self.regulation.id}/',
            {'category_id': ''},
            content_type='application/json',
        )
        self.assertEqual(resp.json()['error'], '')
        self.regulation.refresh_from_db()
        self.assertIsNone(self.regulation.category_id, '清空分类后必须落库为 NULL')

    def test_null_date_is_treated_as_not_provided(self):
        """契约确认：JSON null 与"未提交"等价，均保持原值；只有空字符串才清空"""
        Regulation.objects.filter(pk=self.regulation.id).update(publish_date='2026-03-01')
        resp = self.admin_client.put(
            f'/regulation/{self.regulation.id}/',
            {'publish_date': None},
            content_type='application/json',
        )
        self.assertEqual(resp.json()['error'], '')
        self.regulation.refresh_from_db()
        self.assertEqual(self.regulation.publish_date.isoformat(), '2026-03-01',
                         'JSON null 被 JsonParser 归一为未提交，字段保持原值')

    def test_null_category_id_is_treated_as_not_provided(self):
        resp = self.admin_client.put(
            f'/regulation/{self.regulation.id}/',
            {'category_id': None},
            content_type='application/json',
        )
        self.assertEqual(resp.json()['error'], '')
        self.regulation.refresh_from_db()
        self.assertEqual(self.regulation.category_id, self.leaf_cat.id,
                         'JSON null 被归一为未提交，分类保持原值')

    def test_zero_category_id_clears_category(self):
        resp = self.admin_client.put(
            f'/regulation/{self.regulation.id}/',
            {'category_id': 0},
            content_type='application/json',
        )
        self.assertEqual(resp.json()['error'], '')
        self.regulation.refresh_from_db()
        self.assertIsNone(self.regulation.category_id, 'category_id=0 视为清空分类')

    def test_omitted_field_keeps_existing_value(self):
        """未提交的字段必须保持原值不变"""
        resp = self.admin_client.put(
            f'/regulation/{self.regulation.id}/',
            {'title': '仅改标题'},
            content_type='application/json',
        )
        self.assertEqual(resp.json()['error'], '')
        self.regulation.refresh_from_db()
        self.assertEqual(self.regulation.rule_no, 'RG-0001', '未提交的 rule_no 不应变化')
        self.assertEqual(self.regulation.issuing_authority, '测试发文单位')
        self.assertEqual(self.regulation.biz_type, '空管')
        self.assertEqual(self.regulation.category_id, self.leaf_cat.id)

    def test_update_nonexistent_returns_business_error(self):
        resp = self.admin_client.put(
            '/regulation/99999999/', {'title': 'x'}, content_type='application/json')
        self.assertEqual(resp.json()['error'], '规章不存在')


class RegulationValidationTests(RegulationGateTestCase):
    """R-01-04 参数与业务校验"""

    def test_missing_title_rejected(self):
        resp = self.admin_client.post('/regulation/create/', {'rule_no': 'RG-V-001'},
                                      content_type='application/json')
        self.assertIn('规章名称', resp.json()['error'])

    def test_missing_rule_no_rejected(self):
        resp = self.admin_client.post('/regulation/create/', {'title': 'x'},
                                      content_type='application/json')
        self.assertIn('规章编号', resp.json()['error'])

    def test_blank_title_and_rule_no_rejected(self):
        for field, label in (('title', '规章名称'), ('rule_no', '规章编号')):
            payload = {'title': 'x', 'rule_no': 'x'}
            payload[field] = '   '
            resp = self.admin_client.post('/regulation/create/', payload,
                                          content_type='application/json')
            self.assertIn(label, resp.json()['error'])

    def test_invalid_status_rejected(self):
        resp = self.create_regulation(title='非法状态', rule_no='RG-V-002', status='deleted')
        self.assertEqual(resp.json()['error'], '未知的规章状态')
        self.assertFalse(Regulation.objects.filter(rule_no='RG-V-002').exists())

    def test_invalid_publish_date_rejected(self):
        resp = self.create_regulation(title='非法日期', rule_no='RG-V-003',
                                      publish_date='2026/01/01')
        self.assertIn('YYYY-MM-DD', resp.json()['error'])

    def test_invalid_effective_date_rejected(self):
        resp = self.create_regulation(title='非法日期2', rule_no='RG-V-004',
                                      effective_date='2026-13-45')
        self.assertIn('YYYY-MM-DD', resp.json()['error'])

    def test_nonexistent_category_rejected(self):
        resp = self.create_regulation(title='分类不存在', rule_no='RG-V-005', category_id=999999)
        self.assertEqual(resp.json()['error'], '所选分类不存在')

    def test_non_leaf_category_rejected(self):
        resp = self.create_regulation(title='非叶子', rule_no='RG-V-006',
                                      category_id=self.root_cat.id)
        self.assertEqual(resp.json()['error'], '请选择叶子分类')

    def test_effective_before_publish_rejected(self):
        resp = self.create_regulation(title='日期倒置', rule_no='RG-V-007',
                                      publish_date='2026-08-01', effective_date='2026-07-01')
        self.assertIn('生效日期', resp.json()['error'])
        self.assertFalse(Regulation.objects.filter(rule_no='RG-V-007').exists())

    def test_duplicate_rule_no_allowed_by_backend(self):
        """后端未对 rule_no 做唯一约束，重复编号可创建（记录实际行为）"""
        r1 = self.create_regulation(title='重复编号A', rule_no='RG-DUP')
        r2 = self.create_regulation(title='重复编号B', rule_no='RG-DUP')
        self.assertEqual(r1.json()['error'], '')
        self.assertEqual(r2.json()['error'], '')
        self.assertEqual(Regulation.objects.filter(rule_no='RG-DUP').count(), 2)

    def test_idempotency_guard_blocks_immediate_identical_resubmit(self):
        """30 秒幂等窗口内相同 title+rule_no 的重复提交被拒绝"""
        self.create_regulation(title='幂等测试', rule_no='RG-IDEM')
        resp = self.create_regulation(title='幂等测试', rule_no='RG-IDEM')
        self.assertIn('重复提交', resp.json()['error'])

    def test_unicode_and_special_chars_accepted(self):
        title = '规章《测试》—特殊字符 <>&"\'%_  😀 éè'
        resp = self.create_regulation(title=title, rule_no='RG-UNI-😀')
        self.assertEqual(resp.json()['error'], '')
        reg = Regulation.objects.get(title=title)
        self.assertEqual(reg.title, title)
        reg.refresh_from_db()
        self.assertEqual(reg.title, title, 'Unicode 4 字节字符应完整回读')

    def test_title_255_chars_accepted(self):
        title = '长' * 255
        resp = self.create_regulation(title=title, rule_no='RG-LEN-255')
        self.assertEqual(resp.json()['error'], '')
        self.assertEqual(Regulation.objects.get(rule_no='RG-LEN-255').title, title)

    def test_title_over_255_chars_returns_error_without_persisting(self):
        """超长标题 -> 数据库 DataError，被 HandleExceptionMiddleware 兜底为 HTTP 200 + error"""
        resp = self.create_regulation(title='长' * 300, rule_no='RG-LEN-300')
        self.assertNotEqual(resp.json()['error'], '', '超长标题应返回业务错误')
        self.assertFalse(Regulation.objects.filter(rule_no='RG-LEN-300').exists(),
                         '超长标题不应落库')

    def test_rule_no_over_100_chars_returns_error_without_persisting(self):
        resp = self.create_regulation(title='超长编号', rule_no='R' * 150)
        self.assertNotEqual(resp.json()['error'], '')
        self.assertFalse(Regulation.objects.filter(rule_no='R' * 150).exists())

    def test_unhandled_exception_is_downgraded_to_http_200(self):
        """P1 契约风险：未处理异常被中间件兜底为 HTTP 200 + error（非 500）"""
        resp = self.create_regulation(title='长' * 300, rule_no='RG-LEN-400')
        self.assertEqual(resp.status_code, 200,
                         '未处理异常当前被 HandleExceptionMiddleware 兜底为 HTTP 200')
        self.assertNotEqual(resp.status_code, 500)

    def test_debug_mode_leaks_exception_text_to_client(self):
        """P1 信息泄露风险：DEBUG=True 时异常原文直接回显给前端"""
        from django.conf import settings
        if not settings.DEBUG:
            self.skipTest('当前环境 DEBUG=False，无法复现异常原文回显')
        resp = self.create_regulation(title='长' * 300, rule_no='RG-LEN-401')
        error_text = resp.json()['error']
        self.assertTrue(error_text.startswith('Exception:'),
                        'DEBUG 模式下错误文案以 Exception: 开头')
        self.assertIn('Data too long', error_text,
                      'DEBUG 模式下数据库列名与错误细节被回显给客户端')


class RegulationRetireTests(RegulationGateTestCase):
    """R-01-05 废止幂等性与已废止规章操作权限"""

    def test_retire_changes_status(self):
        resp = self.admin_client.post(f'/regulation/{self.regulation.id}/retire/')
        self.assertEqual(resp.json()['error'], '')
        self.regulation.refresh_from_db()
        self.assertEqual(self.regulation.status, Regulation.STATUS_RETIRED)

    def test_retire_is_idempotent(self):
        first = self.admin_client.post(f'/regulation/{self.regulation.id}/retire/')
        second = self.admin_client.post(f'/regulation/{self.regulation.id}/retire/')
        self.assertEqual(first.json()['error'], '')
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()['error'], '')
        self.assertEqual(second.json()['data']['status'], 'retired')
        self.regulation.refresh_from_db()
        self.assertEqual(self.regulation.status, Regulation.STATUS_RETIRED)
        self.assertEqual(Regulation.objects.filter(pk=self.regulation.id).count(), 1)

    def test_retire_nonexistent_returns_business_error(self):
        resp = self.admin_client.post('/regulation/99999999/retire/')
        self.assertEqual(resp.json()['error'], '规章不存在')

    def test_retired_regulation_still_editable_by_backend(self):
        """已废止规章后端允许编辑（前端 Form/Table 已隐藏入口）"""
        self.admin_client.post(f'/regulation/{self.regulation.id}/retire/')
        resp = self.admin_client.put(
            f'/regulation/{self.regulation.id}/', {'title': '废止后改名'},
            content_type='application/json')
        self.assertEqual(resp.json()['error'], '')
        self.regulation.refresh_from_db()
        self.assertEqual(self.regulation.title, '废止后改名')

    def test_retired_regulation_still_accepts_upload(self):
        """已废止规章后端允许上传附件"""
        self.admin_client.post(f'/regulation/{self.regulation.id}/retire/')
        resp = self.upload(self.uploader_client, self.regulation.id)
        self.assertEqual(resp.json()['error'], '')

    def test_retired_regulation_still_deletable(self):
        self.admin_client.post(f'/regulation/{self.regulation.id}/retire/')
        resp = self.admin_client.delete(f'/regulation/{self.regulation.id}/')
        self.assertEqual(resp.json()['error'], '')
        self.assertFalse(Regulation.objects.filter(pk=self.regulation.id).exists())

    def test_retire_requires_edit_permission(self):
        resp = self.viewer_client.post(f'/regulation/{self.regulation.id}/retire/')
        self.assertEqual(resp.json()['error'], '权限拒绝')
        self.regulation.refresh_from_db()
        self.assertEqual(self.regulation.status, Regulation.STATUS_ACTIVE)

    def test_permission_boundary_edit_and_upload(self):
        """仅 upload 权限不能编辑规章；仅 edit 权限不能废止以外的删除"""
        resp = self.uploader_client.put(
            f'/regulation/{self.regulation.id}/', {'title': 'x'},
            content_type='application/json')
        self.assertEqual(resp.json()['error'], '权限拒绝')
        self.assertNotIn(PERM_EDIT, self.uploader.page_perms)


class RegulationDeleteTests(RegulationGateTestCase):
    """R-01-06 删除规章：数据库记录、附件记录与物理文件"""

    def test_delete_removes_db_record(self):
        self.make_attachment_record(self.regulation, 'del.pdf')
        resp = self.admin_client.delete(f'/regulation/{self.regulation.id}/')
        self.assertEqual(resp.json()['error'], '')
        self.assertFalse(Regulation.objects.filter(pk=self.regulation.id).exists())
        self.assertFalse(
            RegulationAttachment.objects.filter(regulation_id=self.regulation.id).exists(),
            'CASCADE 应硬删除附件记录')

    def test_delete_nonexistent_returns_business_error(self):
        resp = self.admin_client.delete('/regulation/99999999/')
        self.assertEqual(resp.json()['error'], '规章不存在')

    def test_delete_requires_delete_permission(self):
        resp = self.editor_client.delete(f'/regulation/{self.regulation.id}/')
        self.assertEqual(resp.json()['error'], '权限拒绝')
        self.assertTrue(Regulation.objects.filter(pk=self.regulation.id).exists())

    def test_delete_audit_event_recorded(self):
        self.admin_client.delete(f'/regulation/{self.regulation.id}/')
        from apps.logs.models import AuditLog
        log = AuditLog.objects.filter(
            target_type='regulation', action='delete', target_name='基准规章').first()
        self.assertIsNotNone(log, '删除规章应产生 delete 审计事件')

    def test_delete_physical_files_cleaned_on_commit(self):
        """on_commit 在 TestCase 中不自动执行，用 captureOnCommitCallbacks 强制触发"""
        self.make_attachment_record(self.regulation, 'cleanup.pdf')
        self.assertEqual(self.physical_file_count(), 1)
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.admin_client.delete(f'/regulation/{self.regulation.id}/')
        self.assertEqual(resp.json()['error'], '')
        self.assertEqual(self.physical_file_count(), 0,
                         '规章删除提交后物理附件文件应被清理')


class RegulationPhysicalFileIntegrityTests(RegulationGateTestCase):
    """R-01-07 上传落盘顺序与 DB 失败回滚"""

    def test_db_failure_removes_written_file(self):
        """文件先落盘，DB create 失败 -> 记录不产生且物理文件被清理"""
        from unittest.mock import patch
        with patch('apps.regulation.views.RegulationAttachment.objects.create',
                   side_effect=Exception('模拟 DB 写入失败')):
            resp = self.upload(self.uploader_client, self.regulation.id, 'orphan.pdf')
        self.assertNotEqual(resp.json()['error'], '', 'DB 写入失败应返回错误')
        self.assertEqual(RegulationAttachment.objects.count(), 0, 'DB 回滚后不应有附件记录')
        self.assertEqual(self.physical_file_count(), 0,
                         'DB 写入失败后不应留下孤儿物理文件')

    def test_physical_write_failure_leaves_no_record(self):
        """物理写入失败 -> 不得产生虚假附件记录"""
        from unittest.mock import patch
        with patch('apps.regulation.views.storage.save_upload_file',
                   side_effect=OSError('模拟磁盘写入失败')):
            resp = self.upload(self.uploader_client, self.regulation.id, 'diskfail.pdf')
        self.assertNotEqual(resp.json()['error'], '')
        self.assertEqual(RegulationAttachment.objects.count(), 0,
                         '物理写入失败不得产生虚假附件记录')
        self.assertEqual(self.physical_file_count(), 0)

    def test_upload_does_not_write_evidence_attachment(self):
        from apps.evidence.models import EvidenceAttachment
        self.upload(self.uploader_client, self.regulation.id, 'no-evidence.pdf')
        self.assertEqual(RegulationAttachment.objects.count(), 1)
        self.assertEqual(
            EvidenceAttachment.objects.filter(
                module='regulation', object_id=str(self.regulation.id)).count(), 0)
        self.assertEqual(EvidenceAttachment.objects.count(), 0,
                         '规章附件不得写入 EvidenceAttachment')

    def test_relative_path_contains_only_relative_segments(self):
        resp = self.upload(self.uploader_client, self.regulation.id, 'pathcheck.pdf')
        att = RegulationAttachment.objects.get(pk=resp.json()['data']['id'])
        self.assertFalse(os.path.isabs(att.file_path))
        self.assertTrue(att.file_path.startswith('regulation/'))
        self.assertTrue(att.file_path.endswith('.pdf'))

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License
"""
验证 upgrade_no 字段已被彻底移除，且不影响升级模块功能。

测试三个维度：
1. 字段删除成功 - 模型层无 upgrade_no 字段、无 unique_together
2. 无残留 - 序列化/导出/URL/服务层均无 upgrade_no 引用
3. 功能不受影响 - CRUD 全流程正常工作
"""
import inspect
from django.test import TestCase
from apps.upgrade.models import UpgradeRecord
from apps.upgrade.serializers import UpgradeRecordSerializer
from apps.upgrade.exporters import EXCEL_COLUMNS
from apps.upgrade.services.record_service import RecordService
from apps.upgrade.services import step_service
from apps.upgrade import constants
from apps.upgrade import urls as upgrade_urls
from apps.account.models import User


class UpgradeNoFieldRemovalTest(TestCase):
    """验证 upgrade_no 字段已彻底移除"""

    def setUp(self):
        self.user = User.objects.create(
            username='test_upgrade_no',
            nickname='测试用户',
            password_hash=User.make_password('pwd123'),
            access_token='a' * 32,
            last_ip='127.0.0.1',
            tenant_id='test_tenant',
        )

    # ================================================================
    # 1. 字段删除成功
    # ================================================================

    def test_model_has_no_upgrade_no_field(self):
        """模型字段列表中不含 upgrade_no"""
        field_names = {f.name for f in UpgradeRecord._meta.get_fields()}
        self.assertNotIn('upgrade_no', field_names)

    def test_model_no_unique_together(self):
        """unique_together 不含 upgrade_no（应为空或不含该字段）"""
        unique_together = UpgradeRecord._meta.unique_together
        # unique_together 可能为空 tuple 或不含 upgrade_no
        for constraint in unique_together:
            self.assertNotIn('upgrade_no', constraint)

    def test_model_repr_uses_title(self):
        """__repr__ 使用 title 而非 upgrade_no"""
        record = UpgradeRecord.objects.create(
            tenant_id='test_tenant',
            title='测试标题',
            system='测试系统',
            upgrade_type='主版本升级',
            upgrade_time='2026-07-30 10:00:00',
            status='处理中',
            owner='张三',
            created_by=self.user,
        )
        repr_str = repr(record)
        self.assertIn('测试标题', repr_str)
        self.assertNotIn('upgrade_no', repr_str)

    def test_constants_no_prefix(self):
        """constants 模块不含 UPGRADE_NO_PREFIX"""
        self.assertFalse(hasattr(constants, 'UPGRADE_NO_PREFIX'))

    def test_record_service_no_generate_method(self):
        """RecordService 不含 generate_upgrade_no 方法"""
        self.assertFalse(hasattr(RecordService, 'generate_upgrade_no'))

    # ================================================================
    # 2. 无残留
    # ================================================================

    def test_serializer_no_upgrade_no(self):
        """序列化器输出不含 upgrade_no"""
        record = UpgradeRecord.objects.create(
            tenant_id='test_tenant',
            title='序列化测试',
            system='测试系统',
            upgrade_type='主版本升级',
            upgrade_time='2026-07-30 10:00:00',
            status='处理中',
            owner='张三',
            created_by=self.user,
        )
        data = UpgradeRecordSerializer.to_list_view(record)
        self.assertNotIn('upgrade_no', data)
        self.assertIn('title', data)
        self.assertIn('id', data)

    def test_export_columns_no_upgrade_no(self):
        """Excel 导出列不含 upgrade_no"""
        columns = [col[0] for col in EXCEL_COLUMNS]
        self.assertNotIn('upgrade_no', columns)
        self.assertIn('title', columns)

    def test_url_patterns_no_next_no(self):
        """URL 路由不含 next-no/"""
        for url_pattern in upgrade_urls.urlpatterns:
            self.assertNotIn('next-no', str(url_pattern.pattern))

    def test_create_view_no_upgrade_no_argument(self):
        """创建视图的 Argument 列表不含 upgrade_no"""
        from apps.upgrade.views.record.create import RecordCreateView
        source = inspect.getsource(RecordCreateView)
        self.assertNotIn('upgrade_no', source)

    def test_step_service_no_upgrade_no(self):
        """step_service 源码不含 upgrade_no"""
        source = inspect.getsource(step_service)
        self.assertNotIn('upgrade_no', source)

    def test_record_service_source_no_upgrade_no(self):
        """record_service 源码不含 upgrade_no（方法体/属性赋值）"""
        source = inspect.getsource(RecordService)
        self.assertNotIn('upgrade_no', source)

    def test_validators_no_upgrade_no(self):
        """validators 源码不含 upgrade_no"""
        from apps.upgrade.validators import RecordValidator
        source = inspect.getsource(RecordValidator)
        self.assertNotIn('upgrade_no', source)

    def test_next_no_view_deleted(self):
        """next_no.py 视图文件已删除"""
        try:
            from apps.upgrade.views.next_no import NextUpgradeNoView  # noqa
            self.fail('NextUpgradeNoView 仍存在，next_no.py 未被删除')
        except (ImportError, ModuleNotFoundError):
            pass  # 预期：导入失败

    # ================================================================
    # 3. 功能不受影响 - CRUD 全流程
    # ================================================================

    def test_create_record_without_upgrade_no(self):
        """创建记录不需要 upgrade_no，且正常成功"""
        from types import SimpleNamespace
        form = SimpleNamespace(
            title='全流程测试',
            system='生产系统',
            upgrade_type='功能升级',
            upgrade_time='2026-07-30 10:00:00',
            status='处理中',
            owner='李四',
            upgrade_content='升级内容描述',
            impact_scope='影响范围',
            risk_desc='风险说明',
            rollback_plan='回退方案',
        )
        record, error = RecordService.create_record(self.user, form)
        self.assertIsNone(error, f'创建失败: {error}')
        self.assertIsNotNone(record)
        self.assertEqual(record.title, '全流程测试')
        self.assertEqual(record.status, '处理中')

    def test_get_detail_no_upgrade_no(self):
        """获取详情返回数据不含 upgrade_no"""
        record = UpgradeRecord.objects.create(
            tenant_id='test_tenant',
            title='详情测试',
            system='测试系统',
            upgrade_type='主版本升级',
            upgrade_time='2026-07-30 10:00:00',
            status='处理中',
            owner='张三',
            created_by=self.user,
        )
        data, error = RecordService.get_detail(record.id, self.user)
        self.assertIsNone(error)
        self.assertNotIn('upgrade_no', data)
        self.assertEqual(data['title'], '详情测试')

    def test_get_list_no_upgrade_no(self):
        """列表查询返回数据不含 upgrade_no"""
        for i in range(3):
            UpgradeRecord.objects.create(
                tenant_id='test_tenant',
                title=f'列表测试{i}',
                system='测试系统',
                upgrade_type='主版本升级',
                upgrade_time='2026-07-30 10:00:00',
                status='处理中',
                owner='张三',
                created_by=self.user,
            )
        result = RecordService.get_list(self.user, page=1, page_size=10)
        for item in result['records']:
            self.assertNotIn('upgrade_no', item)
            self.assertIn('title', item)
        self.assertEqual(result['total'], 3)

    def test_update_record_works(self):
        """更新记录正常工作（不涉及 upgrade_no）"""
        record = UpgradeRecord.objects.create(
            tenant_id='test_tenant',
            title='更新前',
            system='测试系统',
            upgrade_type='主版本升级',
            upgrade_time='2026-07-30 10:00:00',
            status='处理中',
            owner='张三',
            created_by=self.user,
        )
        from types import SimpleNamespace
        form = SimpleNamespace(title='更新后', status='已完成')
        updated, error = RecordService.update_record(record.id, self.user, form)
        self.assertIsNone(error)
        self.assertEqual(updated.title, '更新后')
        self.assertEqual(updated.status, '已完成')

    def test_delete_record_no_rename(self):
        """软删除不再修改 upgrade_no（字段已不存在）"""
        record = UpgradeRecord.objects.create(
            tenant_id='test_tenant',
            title='删除测试',
            system='测试系统',
            upgrade_type='主版本升级',
            upgrade_time='2026-07-30 10:00:00',
            status='处理中',
            owner='张三',
            created_by=self.user,
        )
        record_id = record.id

        # 构造 mock request
        from types import SimpleNamespace
        mock_request = SimpleNamespace(user=self.user)

        error = RecordService.delete_record(record_id, mock_request)
        self.assertIsNone(error)

        # 验证软删除成功
        refetched = UpgradeRecord.objects.get(id=record_id)
        self.assertTrue(refetched.is_deleted)
        self.assertIsNotNone(refetched.deleted_at)

    def test_multiple_records_no_unique_conflict(self):
        """创建多条记录不会因缺少 upgrade_no 唯一约束而冲突"""
        for i in range(5):
            UpgradeRecord.objects.create(
                tenant_id='test_tenant',
                title=f'重复创建测试{i}',
                system='同一系统',
                upgrade_type='主版本升级',
                upgrade_time='2026-07-30 10:00:00',
                status='处理中',
                owner='同一人',
                created_by=self.user,
            )
        count = UpgradeRecord.objects.filter(
            tenant_id='test_tenant', is_deleted=False
        ).count()
        self.assertEqual(count, 5)

    def test_soft_delete_then_recreate_same_title(self):
        """软删除后可以创建同标题记录（无唯一约束阻碍）"""
        record = UpgradeRecord.objects.create(
            tenant_id='test_tenant',
            title='同名测试',
            system='测试系统',
            upgrade_type='主版本升级',
            upgrade_time='2026-07-30 10:00:00',
            status='处理中',
            owner='张三',
            created_by=self.user,
        )
        record.is_deleted = True
        record.save()

        # 再创建一条同名记录，不应报唯一约束冲突
        record2 = UpgradeRecord.objects.create(
            tenant_id='test_tenant',
            title='同名测试',
            system='测试系统',
            upgrade_type='主版本升级',
            upgrade_time='2026-07-30 11:00:00',
            status='处理中',
            owner='张三',
            created_by=self.user,
        )
        self.assertIsNotNone(record2.id)
        self.assertNotEqual(record.id, record2.id)

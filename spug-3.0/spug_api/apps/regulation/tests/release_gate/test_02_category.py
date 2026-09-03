"""R-02 分类管理（stable_contract + 权限安全）。

覆盖用户要求：
- 分类树查询、创建一级分类和子分类
- 父子关系、叶子标识和排序
- 重名、空名称、超长名称
- 删除不存在的分类
- 删除仍被规章使用的分类必须被阻止且不破坏关联规章
- 修改分类父节点：循环引用 / 非法层级
- category_manage 权限必须在后端独立生效
"""
import datetime

from django.utils import timezone

from apps.regulation.models import Regulation, RegulationCategory
from .base import RegulationGateTestCase


class CategoryTreeQueryTests(RegulationGateTestCase):
    """R-02-01 分类树与列表查询"""

    def test_tree_returns_nested_structure(self):
        resp = self.viewer_client.get('/regulation/categories/tree/')
        self.assertEqual(resp.status_code, 200)
        tree = resp.json()['data']
        names = [node['name'] for node in tree]
        self.assertIn('根分类', names)
        root_node = next(n for n in tree if n['name'] == '根分类')
        self.assertEqual(len(root_node['children']), 1)
        self.assertEqual(root_node['children'][0]['name'], '叶子分类')
        self.assertFalse(root_node['is_leaf'])
        self.assertTrue(root_node['children'][0]['is_leaf'])

    def test_flat_list_returns_all_nodes(self):
        resp = self.viewer_client.get('/regulation/categories/')
        self.assertEqual(resp.json()['error'], '')
        self.assertEqual(len(resp.json()['data']), 2)

    def test_tree_sorted_by_sort_order_then_id(self):
        RegulationCategory.objects.create(name='A分类', sort_order=1)
        RegulationCategory.objects.create(name='B分类', sort_order=1)
        resp = self.viewer_client.get('/regulation/categories/')
        rows = resp.json()['data']
        ordered = sorted(rows, key=lambda r: (r['sort_order'], r['id']))
        self.assertEqual([r['id'] for r in rows], [r['id'] for r in ordered])

    def test_tree_requires_view_permission(self):
        resp = self.no_perm_client.get('/regulation/categories/tree/')
        self.assertEqual(resp.json()['error'], '权限拒绝')


class CategoryCreateTests(RegulationGateTestCase):
    """R-02-02 创建分类"""

    def test_create_root_category(self):
        resp = self.cat_manager_client.post(
            '/regulation/categories/', {'name': '新根分类'}, content_type='application/json')
        self.assertEqual(resp.json()['error'], '')
        cat = RegulationCategory.objects.get(name='新根分类')
        self.assertIsNone(cat.parent_id)
        self.assertTrue(cat.is_leaf)

    def test_create_child_category_marks_parent_non_leaf(self):
        resp = self.cat_manager_client.post(
            '/regulation/categories/', {'name': '子分类', 'parent_id': self.leaf_cat.id},
            content_type='application/json')
        self.assertEqual(resp.json()['error'], '')
        self.leaf_cat.refresh_from_db()
        self.assertFalse(self.leaf_cat.is_leaf, '有子节点后父分类必须置为非叶子')

    def test_create_with_nonexistent_parent_rejected(self):
        resp = self.cat_manager_client.post(
            '/regulation/categories/', {'name': 'x', 'parent_id': 999999},
            content_type='application/json')
        self.assertEqual(resp.json()['error'], '父分类不存在')
        self.assertFalse(RegulationCategory.objects.filter(name='x').exists())

    def test_empty_name_rejected(self):
        resp = self.cat_manager_client.post(
            '/regulation/categories/', {'name': ''}, content_type='application/json')
        self.assertEqual(resp.json()['error'], '分类名称不能为空')

    def test_whitespace_name_accepted_records_actual_behaviour(self):
        """后端未对分类名称做 strip，纯空白名称可入库（记录实际行为）"""
        resp = self.cat_manager_client.post(
            '/regulation/categories/', {'name': '   '}, content_type='application/json')
        self.assertEqual(resp.json()['error'], '')
        self.assertTrue(RegulationCategory.objects.filter(name='   ').exists())

    def test_duplicate_name_allowed_outside_idempotency_window(self):
        """幂等窗口（30s）之外，同名分类可重复创建：后端无唯一约束"""
        self.cat_manager_client.post('/regulation/categories/', {'name': '重名分类'},
                                     content_type='application/json')
        # 把首条记录的 created_at 前移，越过幂等窗口
        RegulationCategory.objects.filter(name='重名分类').update(
            created_at=timezone.now() - datetime.timedelta(seconds=60))
        resp = self.cat_manager_client.post('/regulation/categories/', {'name': '重名分类'},
                                            content_type='application/json')
        self.assertEqual(resp.json()['error'], '')
        self.assertEqual(RegulationCategory.objects.filter(name='重名分类').count(), 2)

    def test_idempotency_guard_blocks_identical_resubmit(self):
        self.cat_manager_client.post(
            '/regulation/categories/', {'name': '幂等分类', 'parent_id': self.root_cat.id},
            content_type='application/json')
        resp = self.cat_manager_client.post(
            '/regulation/categories/', {'name': '幂等分类', 'parent_id': self.root_cat.id},
            content_type='application/json')
        self.assertIn('重复提交', resp.json()['error'])

    def test_name_100_chars_accepted(self):
        name = '分' * 100
        resp = self.cat_manager_client.post('/regulation/categories/', {'name': name},
                                            content_type='application/json')
        self.assertEqual(resp.json()['error'], '')
        self.assertTrue(RegulationCategory.objects.filter(name=name).exists())

    def test_name_over_100_chars_returns_error_without_persisting(self):
        resp = self.cat_manager_client.post('/regulation/categories/', {'name': '分' * 150},
                                            content_type='application/json')
        self.assertNotEqual(resp.json()['error'], '', '超长分类名应返回错误')
        self.assertFalse(RegulationCategory.objects.filter(name='分' * 150).exists())

    def test_create_audit_event_recorded(self):
        self.cat_manager_client.post('/regulation/categories/', {'name': '审计分类'},
                                     content_type='application/json')
        from apps.logs.models import AuditLog
        log = AuditLog.objects.filter(
            target_type='regulation', action='create', target_name='审计分类').first()
        self.assertIsNotNone(log, '创建分类应产生审计事件')
        self.assertIn('category', log.detail or '')


class CategoryUpdateTests(RegulationGateTestCase):
    """R-02-03 编辑分类（含父节点变更能力核对）"""

    def test_update_name_and_sort_order(self):
        resp = self.cat_manager_client.put(
            f'/regulation/categories/{self.leaf_cat.id}/',
            {'name': '改名分类', 'sort_order': 5, 'code': 'ICAO'},
            content_type='application/json')
        self.assertEqual(resp.json()['error'], '')
        self.leaf_cat.refresh_from_db()
        self.assertEqual(self.leaf_cat.name, '改名分类')
        self.assertEqual(self.leaf_cat.sort_order, 5)
        self.assertEqual(self.leaf_cat.code, 'ICAO')

    def test_parent_id_is_not_accepted_by_update_api(self):
        """接口 PUT 不接受 parent_id：无法构造父节点变更 / 循环引用场景"""
        other_root = RegulationCategory.objects.create(name='另一根', sort_order=9)
        resp = self.cat_manager_client.put(
            f'/regulation/categories/{other_root.id}/',
            {'parent_id': self.root_cat.id},
            content_type='application/json')
        self.assertEqual(resp.json()['error'], '')
        other_root.refresh_from_db()
        self.assertIsNone(other_root.parent_id,
                          'PUT 不接受 parent_id，父子关系不可通过编辑变更')

    def test_is_leaf_cannot_be_manually_overridden(self):
        """is_leaf 由后端按子节点存在性维护，不允许手工修改"""
        resp = self.cat_manager_client.put(
            f'/regulation/categories/{self.root_cat.id}/',
            {'is_leaf': True},
            content_type='application/json')
        self.assertEqual(resp.json()['error'], '')
        self.root_cat.refresh_from_db()
        self.assertFalse(self.root_cat.is_leaf,
                         '手工传 is_leaf 不应覆盖后端维护的叶子标识')

    def test_update_nonexistent_returns_business_error(self):
        resp = self.cat_manager_client.put(
            '/regulation/categories/999999/', {'name': 'x'},
            content_type='application/json')
        self.assertEqual(resp.json()['error'], '分类不存在')

    def test_update_requires_category_manage_permission(self):
        resp = self.admin_client  # 确保对照组有权限
        self.assertEqual(
            resp.put(f'/regulation/categories/{self.leaf_cat.id}/', {'name': '有权限改名'},
                     content_type='application/json').json()['error'], '')
        denied = self.viewer_client.put(
            f'/regulation/categories/{self.leaf_cat.id}/', {'name': '无权限改名'},
            content_type='application/json')
        self.assertEqual(denied.json()['error'], '权限拒绝')
        self.leaf_cat.refresh_from_db()
        self.assertEqual(self.leaf_cat.name, '有权限改名')


class CategoryDeleteTests(RegulationGateTestCase):
    """R-02-04 删除分类"""

    def test_delete_nonexistent_returns_business_error(self):
        resp = self.cat_manager_client.delete('/regulation/categories/999999/')
        self.assertEqual(resp.json()['error'], '分类不存在')

    def test_delete_category_with_children_blocked(self):
        resp = self.cat_manager_client.delete(f'/regulation/categories/{self.root_cat.id}/')
        self.assertEqual(resp.json()['error'], '该分类下有子分类，不能删除')
        self.assertTrue(RegulationCategory.objects.filter(pk=self.root_cat.id).exists())

    def test_delete_category_used_by_regulation_blocked(self):
        resp = self.cat_manager_client.delete(f'/regulation/categories/{self.leaf_cat.id}/')
        self.assertEqual(resp.json()['error'], '该分类下有规章，不能删除')
        self.assertTrue(RegulationCategory.objects.filter(pk=self.leaf_cat.id).exists())
        # 关联规章必须完好无损
        self.regulation.refresh_from_db()
        self.assertEqual(self.regulation.category_id, self.leaf_cat.id)
        self.assertEqual(self.regulation.title, '基准规章')

    def test_delete_empty_category_restores_parent_leaf(self):
        root = RegulationCategory.objects.create(name='独立根', sort_order=10)
        child = RegulationCategory.objects.create(name='独立子', parent=root, sort_order=0)
        root.is_leaf = False
        root.save(update_fields=['is_leaf'])
        resp = self.cat_manager_client.delete(f'/regulation/categories/{child.id}/')
        self.assertEqual(resp.json()['error'], '')
        self.assertFalse(RegulationCategory.objects.filter(pk=child.id).exists())
        root.refresh_from_db()
        self.assertTrue(root.is_leaf, '删除最后一个子分类后父节点应恢复为叶子')

    def test_delete_requires_category_manage_permission(self):
        resp = self.viewer_client.delete(f'/regulation/categories/{self.leaf_cat.id}/')
        self.assertEqual(resp.json()['error'], '权限拒绝')
        self.assertTrue(RegulationCategory.objects.filter(pk=self.leaf_cat.id).exists())

    def test_delete_audit_event_recorded(self):
        cat = RegulationCategory.objects.create(name='待删分类', sort_order=11)
        self.cat_manager_client.delete(f'/regulation/categories/{cat.id}/')
        from apps.logs.models import AuditLog
        log = AuditLog.objects.filter(
            target_type='regulation', action='delete', target_name='待删分类').first()
        self.assertIsNotNone(log, '删除分类应产生审计事件')


class CategoryPermissionIsolationTests(RegulationGateTestCase):
    """R-02-05 category_manage 权限不得被其它规章权限隐含授予"""

    def test_uploader_cannot_manage_category(self):
        self.assertEqual(
            self.uploader_client.post('/regulation/categories/', {'name': '上传者建分类'},
                                      content_type='application/json').json()['error'],
            '权限拒绝')

    def test_editor_cannot_manage_category(self):
        self.assertEqual(
            self.editor_client.post('/regulation/categories/', {'name': '编辑者建分类'},
                                    content_type='application/json').json()['error'],
            '权限拒绝')

    def test_deleter_cannot_manage_category(self):
        self.assertEqual(
            self.deleter_client.delete(
                f'/regulation/categories/{self.leaf_cat.id}/').json()['error'],
            '权限拒绝')

    def test_category_manage_does_not_grant_regulation_write(self):
        """category_manage 不得隐含 add/edit/delete 规章权限"""
        self.assertEqual(
            self.cat_manager_client.post('/regulation/create/',
                                         {'title': '越权创建', 'rule_no': 'RG-CAT-01'},
                                         content_type='application/json').json()['error'],
            '权限拒绝')
        self.assertFalse(Regulation.objects.filter(rule_no='RG-CAT-01').exists())

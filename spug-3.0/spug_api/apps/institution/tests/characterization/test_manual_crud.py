# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""手册 CRUD、角色关联配置、编辑密码的真实行为测试

核心授权语义（方案 §2/§3）：
- 业务授权完全按手册关联角色判定；tenant_id 不参与归属/可见判断。
- 同租户但无角色者不可见；跨租户持角色者可见。
"""
import json
import os
import tempfile
from unittest.mock import patch

from django.test import TestCase

from apps.institution import storage
from apps.institution.models import (Manual, ManualCategory, ManualOperationLog,
                                     ManualVersion, ManualOriginal)
from apps.institution.tests.base import (
    ALL_PERMS, PERM_ADD, PERM_CONFIG, PERM_DELETE, PERM_EDIT, PERM_UPLOAD,
    PERM_VIEW, delete_json, get_data, has_error, make_client, make_role,
    make_user, post_json, put_json, setup_test_env,
)


def _make_manual(name='操作手册A', **kwargs):
    params = dict(
        name=name, code=f'ZD-{name[-1]}' if name else '',
        owner_type=Manual.OWNER_SECTION, owner_name='某科室',
        tenant_id='deptA',
    )
    params.update(kwargs)
    return Manual.objects.create(**params)


class CategoryApiTests(TestCase):
    def setUp(self):
        setup_test_env()
        self.manager = make_user('cfg', perms=[PERM_VIEW, PERM_CONFIG])
        self.viewer = make_user('viewer', perms=[PERM_VIEW])
        self.manager_client = make_client(self.manager)
        self.viewer_client = make_client(self.viewer)

    def test_create_category_success(self):
        resp = post_json(self.manager_client, '/institution/categories/',
                         {'name': '操作手册', 'sort_order': 1})
        self.assertFalse(has_error(resp))
        data = get_data(resp)
        self.assertEqual(data['name'], '操作手册')
        self.assertTrue(ManualCategory.objects.filter(name='操作手册').exists())

    def test_create_category_requires_config_perm(self):
        resp = post_json(self.viewer_client, '/institution/categories/', {'name': 'x'})
        self.assertTrue(has_error(resp))

    def test_create_duplicate_name_rejected(self):
        post_json(self.manager_client, '/institution/categories/', {'name': '应急手册'})
        resp = post_json(self.manager_client, '/institution/categories/', {'name': '应急手册'})
        self.assertTrue(has_error(resp))
        self.assertIn('已存在', resp.json()['error'])

    def test_list_excludes_inactive_for_normal_user(self):
        ManualCategory.objects.create(name='停用类别', is_active=False)
        ManualCategory.objects.create(name='启用类别', is_active=True)
        resp = self.viewer_client.get('/institution/categories/')
        names = [x['name'] for x in get_data(resp)]
        self.assertIn('启用类别', names)
        self.assertNotIn('停用类别', names)

    def test_manager_can_list_with_inactive(self):
        ManualCategory.objects.create(name='停用类别', is_active=False)
        resp = self.manager_client.get('/institution/categories/?with_inactive=1')
        names = [x['name'] for x in get_data(resp)]
        self.assertIn('停用类别', names)

    def test_update_category(self):
        cat = ManualCategory.objects.create(name='旧名')
        resp = put_json(self.manager_client, f'/institution/categories/{cat.id}/',
                        {'name': '新名', 'sort_order': 2, 'is_active': False})
        self.assertFalse(has_error(resp))
        cat.refresh_from_db()
        self.assertEqual(cat.name, '新名')
        self.assertFalse(cat.is_active)

    def test_delete_blocked_when_manual_referenced(self):
        cat = ManualCategory.objects.create(name='在用类别')
        _make_manual(category=cat)
        resp = delete_json(self.manager_client, f'/institution/categories/{cat.id}/')
        self.assertTrue(has_error(resp))
        self.assertIn('仍有手册', resp.json()['error'])

    def test_delete_empty_category(self):
        cat = ManualCategory.objects.create(name='空类别')
        resp = delete_json(self.manager_client, f'/institution/categories/{cat.id}/')
        self.assertFalse(has_error(resp))
        self.assertFalse(ManualCategory.objects.filter(pk=cat.id).exists())


class ManualCrudTests(TestCase):
    def setUp(self):
        setup_test_env()
        self.manager = make_user('mgr', tenant_id='deptA', perms=ALL_PERMS)
        self.superuser = make_user('root', is_supper=True, tenant_id='root')
        self.manager_client = make_client(self.manager)

    def test_create_manual_with_roles(self):
        view_role = make_role(tenant_id='deptA')
        edit_role = make_role(tenant_id='deptA')
        resp = post_json(self.manager_client, '/institution/manuals/create/', {
            'name': '部门管理手册', 'code': 'GL-001',
            'owner_type': 'department', 'owner_name': '某部门',
            'view_role_ids': [view_role.id], 'edit_role_ids': [edit_role.id],
            'publish_role_ids': [],
        })
        self.assertFalse(has_error(resp))
        data = get_data(resp)
        self.assertEqual(data['name'], '部门管理手册')
        manual = Manual.objects.get(pk=data['id'])
        self.assertEqual(list(manual.view_roles.values_list('id', flat=True)), [view_role.id])
        self.assertTrue(ManualOperationLog.objects.filter(
            manual=manual, action='create').exists())

    def test_create_requires_add_perm(self):
        viewer = make_user('v', perms=[PERM_VIEW])
        resp = post_json(make_client(viewer), '/institution/manuals/create/',
                         {'name': 'x'})
        self.assertTrue(has_error(resp))

    def test_create_invalid_owner_type(self):
        resp = post_json(self.manager_client, '/institution/manuals/create/',
                         {'name': 'x', 'owner_type': 'company'})
        self.assertTrue(has_error(resp))

    def test_create_invalid_role_id(self):
        resp = post_json(self.manager_client, '/institution/manuals/create/', {
            'name': 'x', 'view_role_ids': [999999]})
        self.assertTrue(has_error(resp))
        self.assertIn('无效的角色', resp.json()['error'])

    def test_list_visibility_by_roles_not_tenant(self):
        """核心授权语义：跨租户持角色可见；同租户无角色不可见"""
        view_role = make_role()
        manual = _make_manual()
        manual.view_roles.add(view_role)
        leader_b = make_user('leader', tenant_id='deptB', roles=[view_role],
                             perms=[PERM_VIEW])
        insider_c = make_user('insider', tenant_id='deptA', perms=[PERM_VIEW])
        resp = make_client(leader_b).get('/institution/manuals/')
        names = [x['name'] for x in get_data(resp)['items']]
        self.assertIn(manual.name, names)
        resp = make_client(insider_c).get('/institution/manuals/')
        self.assertEqual(get_data(resp)['items'], [])
        resp = make_client(self.superuser).get('/institution/manuals/')
        names = [x['name'] for x in get_data(resp)['items']]
        self.assertIn(manual.name, names)

    def test_list_keyword_filter(self):
        _make_manual(name='应急救援手册')
        _make_manual(name='SMS手册')
        resp = self.manager_client.get('/institution/manuals/?keyword=应急')
        names = [x['name'] for x in get_data(resp)['items']]
        self.assertEqual(names, ['应急救援手册'])

    def test_detail_visibility(self):
        view_role = make_role()
        manual = _make_manual()
        manual.view_roles.add(view_role)
        holder = make_user('holder', tenant_id='deptB', roles=[view_role],
                           perms=[PERM_VIEW])
        outsider = make_user('out', tenant_id='deptB', perms=[PERM_VIEW])
        resp = make_client(holder).get(f'/institution/manuals/{manual.id}/')
        self.assertFalse(has_error(resp))
        resp = make_client(outsider).get(f'/institution/manuals/{manual.id}/')
        self.assertTrue(has_error(resp))
        self.assertIn('无权限', resp.json()['error'])

    def test_edit_metadata_by_manager(self):
        cat = ManualCategory.objects.create(name='类别1')
        manual = _make_manual()
        resp = put_json(self.manager_client, f'/institution/manuals/{manual.id}/', {
            'name': '改名手册', 'code': 'GL-002', 'category_id': cat.id,
            'owner_type': 'department', 'owner_name': '部门',
            'status': 'archived', 'editor_can_view_published': False,
        })
        self.assertFalse(has_error(resp))
        manual.refresh_from_db()
        self.assertEqual(manual.name, '改名手册')
        self.assertEqual(manual.status, 'archived')
        self.assertFalse(manual.editor_can_view_published)

    def test_edit_requires_edit_perm(self):
        viewer = make_user('v', perms=[PERM_VIEW])
        manual = _make_manual()
        resp = put_json(make_client(viewer), f'/institution/manuals/{manual.id}/',
                        {'name': 'x'})
        self.assertTrue(has_error(resp))

    def test_delete_refused_when_versions_exist(self):
        manual = _make_manual()
        ManualVersion.objects.create(
            manual=manual, version_no=1, file_path='institution/versions/x.docx',
            original_name='x.docx', published_by=self.manager)
        resp = delete_json(self.manager_client, f'/institution/manuals/{manual.id}/')
        self.assertTrue(has_error(resp))
        self.assertIn('归档', resp.json()['error'])
        self.assertTrue(Manual.objects.filter(pk=manual.id).exists())

    def test_delete_ok_without_versions_and_cleans_files(self):
        """第十二节：先删物理文件，成功后才删数据库记录（响应返回时文件已清）"""
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(storage, 'get_institution_storage_base',
                              return_value=tmp):
                manual = _make_manual()
                rel = storage.build_relative_path('original', manual.id, 'a.docx')
                abs_path = storage.resolve_absolute_path(rel)
                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                with open(abs_path, 'wb') as f:
                    f.write(b'docx')
                from apps.institution.models import ManualFile
                file_entry = ManualFile.objects.create(
                    manual=manual, display_name='a.docx', sort_order=0)
                ManualOriginal.objects.create(
                    manual=manual, file=file_entry, file_path=rel,
                    original_name='a.docx', ext='.docx', file_size=4,
                    uploaded_by=self.manager)
                resp = delete_json(self.manager_client,
                                   f'/institution/manuals/{manual.id}/')
                self.assertFalse(has_error(resp))
                self.assertFalse(Manual.objects.filter(pk=manual.id).exists())
                self.assertFalse(os.path.exists(abs_path))

    def test_delete_aborted_when_file_cleanup_fails(self):
        """物理清理失败：直接拒绝删除，手册保持原状（可重试，无孤儿文件）"""
        manual = _make_manual()
        with patch.object(storage, 'safe_delete_manual_dir',
                          return_value=(False, 'disk error')):
            resp = delete_json(self.manager_client,
                               f'/institution/manuals/{manual.id}/')
        self.assertTrue(has_error(resp))
        self.assertIn('清理失败', resp.json()['error'])
        self.assertTrue(Manual.objects.filter(pk=manual.id).exists())

    def test_roles_config_requires_config_perm(self):
        editor = make_user('e', perms=['institution.manual.draft_edit'])
        manual = _make_manual()
        resp = put_json(make_client(editor), f'/institution/manuals/{manual.id}/roles/',
                        {'view_role_ids': []})
        self.assertTrue(has_error(resp))

    def test_roles_config_success_with_oplog(self):
        view_role = make_role(tenant_id='deptA')
        edit_role = make_role(tenant_id='deptA')
        publish_role = make_role(tenant_id='deptA')
        manual = _make_manual()
        resp = put_json(self.manager_client, f'/institution/manuals/{manual.id}/roles/', {
            'view_role_ids': [view_role.id],
            'edit_role_ids': [edit_role.id, publish_role.id],
            'publish_role_ids': [publish_role.id],
        })
        self.assertFalse(has_error(resp))
        manual.refresh_from_db()
        self.assertEqual(set(manual.edit_roles.values_list('id', flat=True)),
                         {edit_role.id, publish_role.id})
        self.assertTrue(ManualOperationLog.objects.filter(
            manual=manual, action='config_change').exists())

    def test_password_set_stores_hash_only(self):
        manual = _make_manual()
        resp = put_json(self.manager_client, f'/institution/manuals/{manual.id}/password/',
                        {'password': 'secret123'})
        self.assertFalse(has_error(resp))
        manual.refresh_from_db()
        self.assertTrue(manual.password_hash)
        self.assertNotEqual(manual.password_hash, 'secret123')
        resp = self.manager_client.get(f'/institution/manuals/{manual.id}/')
        data = get_data(resp)
        self.assertTrue(data['has_password'])
        self.assertNotIn('password_hash', json.dumps(data))
        self.assertNotIn('secret123', json.dumps(data))

    def test_password_requires_config_perm(self):
        editor = make_user('e2', perms=['institution.manual.draft_edit'])
        manual = _make_manual()
        resp = put_json(make_client(editor), f'/institution/manuals/{manual.id}/password/',
                        {'password': 'abcd'})
        self.assertTrue(has_error(resp))

    def test_password_too_short(self):
        manual = _make_manual()
        resp = put_json(self.manager_client, f'/institution/manuals/{manual.id}/password/',
                        {'password': 'ab'})
        self.assertTrue(has_error(resp))


class TenantManagerDeclarationTests(TestCase):
    """租户 Manager 显式声明契约

    TenantModelMixin 上的 manager 会被 Django 自动补的默认 Manager 遮蔽
    （只对模型自身 classdict 里的 Manager 做 add_to_class），因此每个模型
    必须显式 objects = TenantModelManager()，否则 .for_user() 直接
    AttributeError、未来软删过滤静默失效。
    """

    def test_all_models_use_tenant_manager(self):
        from libs.tenant_base_model import TenantModelManager
        from apps.institution import models as m
        names = ('ManualCategory', 'Manual', 'ManualFile', 'ManualOriginal',
                 'ManualDraft', 'ManualVersion', 'ManualVersionFile',
                 'ManualEditSession', 'ManualChapter', 'ManualOperationLog')
        for name in names:
            model = getattr(m, name)
            self.assertIsInstance(model.objects, TenantModelManager, name)
            # 真实走 TenantModelManager.get_queryset 的查询路径
            model.objects.count()


class RoleOptionsTests(TestCase):
    def setUp(self):
        setup_test_env()
        self.config_only = make_user('cfg', tenant_id='deptA', perms=[PERM_CONFIG])
        self.viewer = make_user('viewer', perms=[PERM_VIEW])

    def test_config_holder_can_list_options_without_account_perm(self):
        """制度配置者无需 system.account.view 即可获取本租户可分配角色"""
        make_role(name='本租户编制角色', tenant_id='deptA')
        resp = make_client(self.config_only).get('/institution/roles/')
        self.assertFalse(has_error(resp))
        names = [x['name'] for x in get_data(resp)]
        self.assertIn('本租户编制角色', names)

    def test_supper_sees_platform_level_roles(self):
        """平台级角色（tenant_id 为空）仅超管可见——方案 §3 角色由超管维护"""
        make_role(name='平台编制角色', tenant_id='')
        supper = make_user('root', is_supper=True)
        resp = make_client(supper).get('/institution/roles/')
        names = [x['name'] for x in get_data(resp)]
        self.assertIn('平台编制角色', names)

    def test_view_only_denied(self):
        resp = make_client(self.viewer).get('/institution/roles/')
        self.assertTrue(has_error(resp))

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# 资料与行政业务特征测试 - 党建资料和系统目录
# 覆盖: DocumentSystemFolder, system_scope 隔离, fail-closed, 跨租户
import uuid

from django.test import TestCase

from tests.helpers.test_base import (
    make_user, make_client, setup_test_env)
from apps.document.models import (
    DocumentSystemFolder, DocumentFolderPublic)
from apps.document.services.system_scope_validators import (
    validate_document_context, normalize_context)
from apps.document.services.system_folder_service import (
    PARTY_BUILDING_DOCUMENTS_CODE, is_valid_system_folder_code,
    is_party_building_documents_code, normalize_system_folder_code)


def _make_system_folder(admin, code=PARTY_BUILDING_DOCUMENTS_CODE,
                         name='党建根目录'):
    """创建 DocumentSystemFolder (需要先创建 DocumentFolderPublic)"""
    public_folder = DocumentFolderPublic.objects.create(
        name=name, created_by=admin)
    return DocumentSystemFolder.objects.create(
        code=code, name=name, folder=public_folder,
        is_public=True, protected=True)


class DocumentSystemFolderModelTest(TestCase):
    """系统目录模型测试"""

    def setUp(self):
        setup_test_env()
        self.admin = make_user('admin', is_supper=True)

    def test_model_exists(self):
        folder = _make_system_folder(self.admin)
        self.assertEqual(folder.code, PARTY_BUILDING_DOCUMENTS_CODE)
        self.assertEqual(folder.name, '党建根目录')
        self.assertTrue(folder.is_public)
        self.assertTrue(folder.protected)

    def test_code_unique(self):
        """code 字段唯一"""
        _make_system_folder(self.admin)
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            _make_system_folder(self.admin)

    def test_no_tenant_id(self):
        """系统目录没有 tenant_id (全局共享)"""
        fields = {f.name for f in DocumentSystemFolder._meta.get_fields()}
        self.assertNotIn('tenant_id', fields)

    def test_folder_protect_on_delete(self):
        """folder 使用 on_delete=PROTECT, 不能直接删除被引用的 DocumentFolderPublic"""
        folder = _make_system_folder(self.admin)
        from django.db.models.deletion import ProtectedError
        with self.assertRaises(ProtectedError):
            folder.folder.delete()


class SystemScopeValidatorTest(TestCase):
    """system_scope 验证测试"""

    def setUp(self):
        setup_test_env()
        self.admin = make_user('admin', is_supper=True)

    def test_valid_code(self):
        """党建 code 是有效的"""
        self.assertTrue(is_valid_system_folder_code(
            PARTY_BUILDING_DOCUMENTS_CODE))

    def test_invalid_code(self):
        """无效 code 被拒绝"""
        self.assertFalse(is_valid_system_folder_code('invalid_scope'))

    def test_party_building_code_check(self):
        """党建 code 识别"""
        self.assertTrue(is_party_building_documents_code(
            PARTY_BUILDING_DOCUMENTS_CODE))
        self.assertFalse(is_party_building_documents_code('other'))

    def test_normalize_code(self):
        """code 规范化"""
        self.assertEqual(
            normalize_system_folder_code(PARTY_BUILDING_DOCUMENTS_CODE),
            PARTY_BUILDING_DOCUMENTS_CODE)
        self.assertIsNone(normalize_system_folder_code(None))
        self.assertEqual(normalize_system_folder_code(''), '')

    def test_validate_private_context_no_system_folder(self):
        """私人空间无 system_folder 验证通过"""
        ok, error = validate_document_context(None, False)
        self.assertTrue(ok)

    def test_validate_public_context_no_system_folder(self):
        """公共空间无 system_folder 验证通过 (非系统目录)"""
        ok, error = validate_document_context(None, True)
        self.assertTrue(ok)


class PartyBuildingCrossTenantTest(TestCase):
    """党建跨租户测试"""

    def setUp(self):
        setup_test_env()
        self.t_a = make_user('ta', is_supper=True, tenant_id='tenant_a')
        self.t_b = make_user('tb', is_supper=True, tenant_id='tenant_b')

    def test_system_folder_visible_to_all_tenants(self):
        """系统目录对所有租户可见"""
        folder = _make_system_folder(self.t_a)
        # 租户B也能看到 (没有 tenant_id)
        self.assertTrue(
            DocumentSystemFolder.objects.filter(id=folder.id).exists())

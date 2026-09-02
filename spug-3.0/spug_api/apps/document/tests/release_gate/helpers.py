"""资料库发布门禁测试公共辅助。

所有用例必须通过真实 HTTP 请求 / 真实数据库 / 真实文件系统副作用验证行为，
禁止用读取源码字符串的方式代替行为测试。
"""
import os
import shutil
import uuid

from django.conf import settings

from apps.document.models import (
    DocumentFilePublic,
    DocumentFolderPublic,
    DocumentSystemFolder,
    DocumentTransfer,
)
from apps.document.services.system_folder_service import PARTY_BUILDING_DOCUMENTS_CODE

PB = PARTY_BUILDING_DOCUMENTS_CODE

DOCUMENT_STORAGE_BASE = os.path.join(settings.BASE_DIR, 'storage', 'documents')

# 权限编码
PERM_VIEW = 'document.document.view'
PERM_UPLOAD = 'document.document.upload'
PERM_DOWNLOAD = 'document.document.download'
PERM_DELETE = 'document.document.delete'
PERM_CREATE_FOLDER = 'document.document.create_folder'
PERM_COPY = 'document.document.copy'
PERM_MOVE = 'document.document.move'
PERM_RENAME = 'document.document.rename'

PB_VIEW = 'document.party_building_document.view'
PB_EDIT = 'document.party_building_document.edit'
PB_DELETE = 'document.party_building_document.delete'


def unique(prefix='t'):
    return f'{prefix}_{uuid.uuid4().hex[:12]}'


def make_physical_file(folder_id=None, system_folder=None, content=b'gate-test-content',
                       suffix='.txt', filename=None):
    """在文档存储根目录内创建真实物理文件，返回绝对路径。"""
    from apps.document.libs.document_utils import get_document_absolute_path

    directory = get_document_absolute_path(folder_id=folder_id, system_folder=system_folder)
    os.makedirs(directory, exist_ok=True)
    name = filename or f'{uuid.uuid4().hex}{suffix}'
    path = os.path.join(directory, name)
    with open(path, 'wb') as fh:
        fh.write(content)
    return path


def make_folder(name=None, parent=None, created_by=None):
    return DocumentFolderPublic.objects.create(
        name=name or unique('folder'),
        parent=parent,
        created_by=created_by,
    )


def make_file(folder=None, created_by=None, name=None, content=b'gate-test-content',
              suffix='.txt', physical_name=None):
    """创建带真实物理文件的文件记录。"""
    path = make_physical_file(
        folder_id=folder.id if folder else None,
        content=content,
        suffix=suffix,
    )
    base = name or f'{uuid.uuid4().hex[:16]}{suffix}'
    return DocumentFilePublic.objects.create(
        name=base,
        display_name=base,
        physical_name=physical_name or os.path.basename(path),
        file_path=path,
        file_size=len(content),
        file_type='text/plain',
        folder=folder,
        created_by=created_by,
    )


def bind_party_building(root_folder, code=PB, protected=True):
    """绑定党建系统目录。"""
    return DocumentSystemFolder.objects.create(
        code=code,
        name='党建文档',
        folder=root_folder,
        is_public=True,
        protected=protected,
    )


def make_transfer(user, **kwargs):
    defaults = dict(
        tenant_id=getattr(user, 'tenant_id', '') or '',
        user=user,
        transfer_type='UPLOAD',
        status='PENDING',
        file_name=unique('f') + '.txt',
        file_size=1024,
        file_path='',
        file_hash=uuid.uuid4().hex,
        is_public=True,
        system_folder='',
        total_chunks=0,
    )
    defaults.update(kwargs)
    return DocumentTransfer.objects.create(**defaults)


class StorageCleanupMixin:
    """记录测试期间创建的物理路径，tearDown 时清理，避免污染存储目录。"""

    def setUp(self):
        super().setUp()
        self._gate_created_paths = []

    def track_path(self, path):
        if path:
            self._gate_created_paths.append(path)
        return path

    def tearDown(self):
        for path in getattr(self, '_gate_created_paths', []):
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                elif os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
        super().tearDown()

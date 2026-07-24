# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""初始化文档系统目录绑定（党建工作）

用法：
    python manage.py init_document_system_folders

职责：
1. 确保公共根目录下存在"党建工作"目录（不存在则创建，存在则复用未删除记录）
2. 创建或更新 DocumentSystemFolder(code='party_building_documents') 绑定
3. 幂等执行，便于部署和修复
"""
import logging

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.document.models import DocumentFolderPublic, DocumentSystemFolder
from apps.document.services.system_folder_service import PARTY_BUILDING_DOCUMENTS_CODE

logger = logging.getLogger(__name__)

PARTY_BUILDING_DOCUMENTS_FOLDER_NAME = '党建工作'


class Command(BaseCommand):
    help = '初始化文档系统目录绑定（党建工作）'

    def handle(self, *args, **options):
        self.stdout.write('开始初始化文档系统目录绑定...')

        folder = self._ensure_party_building_documents_folder()
        binding = self._ensure_system_folder_binding(folder)

        self.stdout.write(self.style.SUCCESS(
            f'党建工作系统目录绑定完成：'
            f'folder_id={folder.id}, name={folder.name}, '
            f'code={binding.code}, protected={binding.protected}'
        ))

    @transaction.atomic
    def _ensure_party_building_documents_folder(self):
        """确保公共根目录下存在"党建工作"目录，复用未删除同名目录"""
        # 默认管理器已过滤 is_deleted=False
        existing = (
            DocumentFolderPublic.objects
            .filter(name=PARTY_BUILDING_DOCUMENTS_FOLDER_NAME, parent__isnull=True)
            .first()
        )
        if existing:
            self.stdout.write(f'复用已有"党建工作"目录: id={existing.id}')
            return existing

        folder = DocumentFolderPublic.objects.create(
            name=PARTY_BUILDING_DOCUMENTS_FOLDER_NAME,
            parent=None,
            created_by=None,
        )
        self.stdout.write(f'创建"党建工作"目录: id={folder.id}')
        return folder

    @transaction.atomic
    def _ensure_system_folder_binding(self, folder):
        """创建或更新 DocumentSystemFolder 绑定"""
        binding, created = DocumentSystemFolder.objects.update_or_create(
            code=PARTY_BUILDING_DOCUMENTS_CODE,
            defaults={
                'name': PARTY_BUILDING_DOCUMENTS_FOLDER_NAME,
                'folder': folder,
                'is_public': True,
                'protected': True,
                'description': '党建工作系统业务根目录，受保护不可删除/重命名/移动',
            },
        )
        if created:
            self.stdout.write(f'创建系统目录绑定: code={binding.code}, folder_id={folder.id}')
        else:
            self.stdout.write(f'更新系统目录绑定: code={binding.code}, folder_id={folder.id}')
        return binding

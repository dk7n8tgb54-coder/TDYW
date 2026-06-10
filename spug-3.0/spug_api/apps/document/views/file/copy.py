# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文件复制视图
提供文件复制功能
"""

import os
import json
import shutil
import logging
from django.views.generic import View

from libs import json_response, auth
from libs.tenant_utils import apply_tenant_filter
from apps.document.libs.document_utils import get_folder_model, get_file_model, get_document_absolute_path
from apps.document.libs.naming_utils import generate_physical_name, generate_unique_logical_name, get_file_ext
from apps.document.libs.view_utils import permission_denied_response
from apps.document.views.base import create_model_instance, check_public_space_permission, log_operation

logger = logging.getLogger(__name__)


class FileCopyParamsParser:
    """文件复制参数解析器"""

    @staticmethod
    def parse(request):
        """解析请求参数"""
        try:
            data = json.loads(request.body)
            file_id = data.get('id')
            folder_id = data.get('folder_id')
            is_public = data.get('is_public', False)
            return {'file_id': file_id, 'folder_id': folder_id, 'is_public': is_public}, None
        except Exception:
            return None, '参数错误'


class FileCopyValidator:
    """文件复制验证器"""

    @staticmethod
    def validate_source_file(file_id, is_public, user):
        """验证源文件存在性（权限由调用方检查）"""
        FileModel = get_file_model(is_public=is_public)

        file_query = FileModel.objects.filter(pk=file_id).order_by()
        if not is_public:
            file_query = apply_tenant_filter(file_query, user, strict_mode=True)
        file = file_query.select_related('created_by').first()

        if not file:
            logger.error(f'[Document] Source file not found with id: {file_id}')
            return None, '文件不存在'

        return file, None

    @staticmethod
    def validate_target_folder(folder_id, is_public, user):
        """验证目标文件夹"""
        if not folder_id:
            return None, None

        FolderModel = get_folder_model(is_public=is_public)
        folder_query = FolderModel.objects.filter(pk=folder_id).order_by()
        if not is_public:
            folder_query = apply_tenant_filter(folder_query, user, strict_mode=True)
        folder = folder_query.first()

        if not folder:
            logger.error(f'[Document] Target folder not found with id: {folder_id}')
            return None, '目标文件夹不存在'

        return folder, None


class FileNameGenerator:
    """复制文件名生成器"""

    @staticmethod
    def generate(file, folder, is_public, user):
        """生成复制文件的名称"""
        FileModel = get_file_model(is_public=is_public)

        # 获取原始显示名
        original_display_name = file.display_name or file.name
        _, file_ext = get_file_ext(original_display_name)

        # 生成三层文件名
        physical_name = generate_physical_name(file_ext)
        logical_name = generate_unique_logical_name(FileModel, original_display_name, folder, user)

        return {
            'physical_name': physical_name,
            'logical_name': logical_name,
            'original_display_name': original_display_name
        }

    @staticmethod
    def resolve_display_name(original_name, folder, is_public, user, is_same_folder):
        """解析最终显示名称（处理重名）"""
        FileModel = get_file_model(is_public=is_public)

        new_display_name = original_name
        if is_same_folder:
            new_display_name = f'副本_{original_name}'

        # 检查目标文件夹下是否已存在同名显示名称
        existing_file_query = FileModel.objects.filter(
            folder=folder,
            display_name=new_display_name
        ).order_by()
        if not is_public:
            existing_file_query = apply_tenant_filter(existing_file_query, user, strict_mode=True)
        existing_file = existing_file_query.first()

        if existing_file:
            new_display_name = FileNameGenerator._add_numeric_suffix(
                new_display_name, folder, is_public, user
            )

        return new_display_name

    @staticmethod
    def _add_numeric_suffix(display_name, folder, is_public, user):
        """添加数字后缀解决重名"""
        FileModel = get_file_model(is_public=is_public)
        counter = 1
        new_display_name = display_name

        while True:
            name_without_ext, ext = os.path.splitext(display_name)
            new_display_name = f'{name_without_ext}_{counter}{ext}'

            existing_file_query = FileModel.objects.filter(
                folder=folder,
                display_name=new_display_name
            ).order_by()
            if not is_public:
                existing_file_query = apply_tenant_filter(existing_file_query, user, strict_mode=True)

            if not existing_file_query.first():
                break
            counter += 1

        return new_display_name


class FileCopyExecutor:
    """文件复制执行器"""

    @staticmethod
    def copy_physical_file(source_path, target_path):
        """复制物理文件"""
        shutil.copy2(source_path, target_path)
        logger.info(f'[Document] Physical file copied from {source_path} to {target_path}')

    @staticmethod
    def create_file_record(FileModel, logical_name, display_name, physical_name,
                          folder, file_path, source_file, user):
        """创建文件记录"""
        return create_model_instance(FileModel,
            name=logical_name,
            display_name=display_name,
            physical_name=physical_name,
            folder=folder,
            file_path=file_path,
            file_size=source_file.file_size,
            file_type=source_file.file_type,
            created_by=user
        )

    @staticmethod
    def build_upload_dir(is_public, user_id, folder):
        """构建上传目录"""
        upload_dir = get_document_absolute_path(
            is_public=is_public,
            user_id=user_id,
            folder_id=folder.id if folder else None
        )
        os.makedirs(upload_dir, exist_ok=True)
        return upload_dir


class FileCopyLogger:
    """文件复制日志记录器"""

    @staticmethod
    def log_copy_operation(user, new_file, source_file, original_name,
                          new_name, folder, is_public):
        """记录复制操作日志"""
        log_operation(
            action="FILE_COPY",
            user=user,
            resource_type="FILE",
            resource_id=new_file.id,
            is_public=is_public,
            source_file_id=source_file.id,
            original_display_name=original_name,
            new_display_name=new_name,
            target_folder_id=folder.id if folder else None
        )
        logger.info(f'[Document] File record created successfully, is_public={is_public}')


class FileCopyView(View):
    """文件复制视图"""

    @auth('document.document.copy')
    def post(self, request):
        logger.info(f'[Document] FileCopyView.post called, user: {request.user.username}')

        # 解析参数
        params, error = FileCopyParamsParser.parse(request)
        if error:
            return json_response(error=error)

        file_id = params['file_id']
        folder_id = params['folder_id']
        is_public = params['is_public']

        if not file_id:
            return json_response(error='参数错误')

        # 验证源文件
        file, error = FileCopyValidator.validate_source_file(
            file_id, is_public, request.user
        )
        if error:
            return json_response(error=error)

        # 公共空间权限校验
        if is_public and not check_public_space_permission(request.user, file, 'file', '复制'):
            return permission_denied_response('公共空间中只能复制自己创建的文件', 'not_owner')

        # 验证目标文件夹
        folder, error = FileCopyValidator.validate_target_folder(
            folder_id, is_public, request.user
        )
        if error:
            return json_response(error=error)

        logger.info(f'[Document] Copying file id: {file_id} to folder_id: {folder_id}, is_public={is_public}')

        # 构建上传目录
        upload_dir = FileCopyExecutor.build_upload_dir(
            is_public, request.user.id, folder
        )

        # 生成文件名
        names = FileNameGenerator.generate(file, folder, is_public, request.user)
        new_file_path = os.path.join(upload_dir, names['physical_name'])

        logger.info(f'[Document] Generated names: physical={names["physical_name"]}, logical={names["logical_name"]}')

        # 复制物理文件
        FileCopyExecutor.copy_physical_file(file.file_path, new_file_path)

        # 确定显示名称
        is_same_folder = file.folder == folder
        final_display_name = FileNameGenerator.resolve_display_name(
            names['original_display_name'], folder, is_public, request.user, is_same_folder
        )

        # 创建文件记录
        FileModel = get_file_model(is_public=is_public)
        new_file = FileCopyExecutor.create_file_record(
            FileModel,
            names['logical_name'],
            final_display_name,
            names['physical_name'],
            folder,
            new_file_path,
            file,
            request.user
        )

        # 记录日志
        FileCopyLogger.log_copy_operation(
            request.user, new_file, file,
            names['original_display_name'], final_display_name,
            folder, is_public
        )

        return json_response()

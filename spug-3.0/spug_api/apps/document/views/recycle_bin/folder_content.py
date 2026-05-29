# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
回收站文件夹内容视图
查看已删除文件夹内部的内容
"""

import logging
from django.views.generic import View
from django.db.models import Q

from libs import json_response, JsonParser, Argument, auth
from ...models import (
    DocumentFilePrivate, DocumentFilePublic,
    DocumentFolderPrivate, DocumentFolderPublic
)

logger = logging.getLogger(__name__)


class RecycleBinFolderContentView(View):
    """回收站文件夹内容视图 - 查看已删除文件夹内的内容"""
    
    @auth('document.document.view')
    def get(self, request):
        """获取已删除文件夹内的内容（子文件夹和文件）"""
        form, error = JsonParser(
            Argument('folder_id', type=int, required=True),
            Argument('space', required=True, filter=lambda x: x in ['private', 'public']),
            Argument('page', type=int, required=False, default=1),
            Argument('page_size', type=int, required=False, default=50),
        ).parse(request.GET)
        
        if error:
            return json_response(error=error)
        
        user_tenant_id = getattr(request.user, 'tenant_id', None)
        
        # 获取模型
        FileModel = DocumentFilePrivate if form.space == 'private' else DocumentFilePublic
        FolderModel = DocumentFolderPrivate if form.space == 'private' else DocumentFolderPublic
        
        # 验证文件夹存在且已删除
        try:
            folder = FolderModel.all_objects.get(id=form.folder_id, is_deleted=True)
        except FolderModel.DoesNotExist:
            return json_response(error='文件夹不存在或未被删除', code=404)
        
        # 权限检查 - 【修改】私密空间完全隔离，超级管理员也不能查看其他租户数据
        if form.space == 'private':
            if folder.tenant_id != user_tenant_id:
                return json_response(error='无权访问该文件夹', code=403)
        else:
            if folder.created_by != request.user:
                return json_response(error='无权访问该文件夹', code=403)
        
        # 查询子文件夹（已删除的）
        subfolder_qs = FolderModel.all_objects.filter(
            parent=folder, 
            is_deleted=True
        ).select_related('created_by', 'deleted_by')
        
        # 【修改】私密空间完全隔离，超级管理员也不能查看其他租户数据
        if form.space == 'private':
            subfolder_qs = subfolder_qs.filter(tenant_id=user_tenant_id)
        else:
            subfolder_qs = subfolder_qs.filter(created_by=request.user)
        
        # 查询文件（已删除的，直接属于该文件夹的）
        file_qs = FileModel.all_objects.filter(
            folder=folder,
            is_deleted=True
        ).select_related('created_by')
        
        # 【修改】私密空间完全隔离，超级管理员也不能查看其他租户数据
        if form.space == 'private':
            file_qs = file_qs.filter(tenant_id=user_tenant_id)
        else:
            file_qs = file_qs.filter(created_by=request.user)
        
        # 转换为列表并标记类型
        subfolders = list(subfolder_qs)
        files = list(file_qs)
        
        for f in subfolders:
            f._item_type = 'folder'
        for f in files:
            f._item_type = 'file'
        
        # 合并并按删除时间排序
        all_items = subfolders + files
        all_items.sort(key=lambda x: x.deleted_at or x.updated_at, reverse=True)
        
        total_count = len(all_items)
        
        # 手动分页
        offset = (form.page - 1) * form.page_size
        paginated_items = all_items[offset:offset + form.page_size]
        
        # 格式化结果
        results = []
        for item in paginated_items:
            if getattr(item, '_item_type', 'file') == 'folder':
                results.append(self._format_subfolder(item, form.space))
            else:
                results.append(self._format_file(item, form.space))
        
        # 计算文件夹统计信息
        stats = self._get_folder_stats(folder, form.space, FileModel, FolderModel)
        
        return json_response(data={
            'items': results,
            'total': total_count,
            'page': form.page,
            'page_size': form.page_size,
            'folder_info': {
                'id': folder.id,
                'name': folder.name,
                'deleted_at': folder.deleted_at.isoformat() if folder.deleted_at else None,
                'total_files': stats['total_files'],
                'total_size': stats['total_size'],
                'total_folders': stats['total_folders'],
            },
            'parent_chain': self._get_parent_chain(folder, FolderModel)
        })
    
    def _format_subfolder(self, folder_obj, space):
        """格式化子文件夹信息"""
        # 统计子文件夹内的内容
        FolderModel = DocumentFolderPrivate if space == 'private' else DocumentFolderPublic
        FileModel = DocumentFilePrivate if space == 'private' else DocumentFilePublic
        
        subfolder_count = FolderModel.all_objects.filter(
            parent=folder_obj, 
            is_deleted=True
        ).count()
        
        file_count = FileModel.all_objects.filter(
            folder=folder_obj,
            is_deleted=True
        ).count()
        
        return {
            'id': folder_obj.id,
            'type': 'folder',
            'name': folder_obj.name,
            'deleted_at': folder_obj.deleted_at.isoformat() if folder_obj.deleted_at else None,
            'subfolder_count': subfolder_count,
            'file_count': file_count,
            'created_by': {
                'id': folder_obj.created_by.id,
                'nickname': folder_obj.created_by.nickname
            } if folder_obj.created_by else None,
            'deleted_by': {
                'id': folder_obj.deleted_by.id,
                'nickname': folder_obj.deleted_by.nickname
            } if folder_obj.deleted_by else None
        }
    
    def _format_file(self, file_obj, space):
        """格式化文件信息"""
        return {
            'id': file_obj.id,
            'type': 'file',
            'name': file_obj.name,
            'display_name': file_obj.display_name,
            'file_size': file_obj.file_size,
            'file_type': file_obj.file_type,
            'deleted_at': file_obj.deleted_at.isoformat() if file_obj.deleted_at else None,
            'created_by': {
                'id': file_obj.created_by.id,
                'nickname': file_obj.created_by.nickname
            } if file_obj.created_by else None
        }
    
    def _get_folder_stats(self, folder, space, FileModel, FolderModel):
        """获取文件夹统计信息"""
        total_files = 0
        total_size = 0
        total_folders = 0
        
        # 递归获取所有子文件夹
        folder_ids = self._get_folder_and_descendants(folder, FolderModel)
        total_folders = len(folder_ids) - 1  # 不包括当前文件夹本身
        
        # 统计所有文件
        for folder_id in folder_ids:
            files = FileModel.all_objects.filter(folder_id=folder_id, is_deleted=True)
            total_files += files.count()
            total_size += sum(f.file_size for f in files)
        
        return {
            'total_files': total_files,
            'total_size': total_size,
            'total_folders': total_folders
        }
    
    def _get_folder_and_descendants(self, folder, FolderModel):
        """获取文件夹及其所有子孙文件夹的ID列表"""
        folder_ids = [folder.id]
        
        children = FolderModel.all_objects.filter(parent=folder, is_deleted=True)
        for child in children:
            folder_ids.extend(self._get_folder_and_descendants(child, FolderModel))
        
        return folder_ids
    
    def _get_parent_chain(self, folder, FolderModel):
        """获取父文件夹链"""
        chain = []
        current = folder
        
        # 最多追溯10层，防止意外循环
        for _ in range(10):
            if not current.parent:
                break
            try:
                parent = FolderModel.all_objects.get(id=current.parent.id)
                if not parent.is_deleted:
                    break
                chain.insert(0, {
                    'id': parent.id,
                    'name': parent.name
                })
                current = parent
            except FolderModel.DoesNotExist:
                break
        
        return chain

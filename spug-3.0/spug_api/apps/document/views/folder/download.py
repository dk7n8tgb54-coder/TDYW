# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
文件夹下载视图
提供文件夹打包下载功能
"""

import os
import zipfile
import tempfile
import logging
from django.conf import settings
from django.views.generic import View
from django.http import StreamingHttpResponse
from urllib.parse import quote

from libs import json_response, JsonParser, Argument
from libs.tenant_utils import apply_tenant_filter
from ...libs.document_utils import get_folder_model, get_file_model, is_safe_path
from ...libs.document_auth import document_auth
from ...services.system_folder_service import (
    PARTY_BUILDING_DOCUMENTS_CODE, ensure_folder_in_scope_or_error,
    validate_system_folder_context,
)
from ...services.system_scope_validators import validate_folder_source_scope
from ..base import log_operation

logger = logging.getLogger(__name__)


class FolderDownloadView(View):
    """文件夹下载视图 - ZIP打包"""

    # 【P0-6修复】大文件夹阈值：超过此文件数则使用异步模式
    ASYNC_FILE_COUNT_THRESHOLD = 100

    @document_auth('view')
    def get(self, request):
        """【P0-6修复】支持异步打包模式

        流程：
        1. 小文件夹：同步打包，立即下载
        2. 大文件夹：异步打包，返回任务 ID，前端轮询状态后下载
        """
        logger.info(f'[Document] FolderDownloadView.get called, user: {request.user.username}')
        form, error = JsonParser(
            Argument('id', type=int, help='参数错误'),
            Argument('is_public', type=bool, required=False, default=False),
            Argument('system_folder', type=str, required=False, default=None),
        ).parse(request.GET)

        if error is not None:
            logger.error(f'[Document] Download parse error: {error}')
            return json_response(error=error)

        # 党建文档上下文校验
        ok, ctx_err = validate_system_folder_context(form.system_folder, form.is_public)
        if not ok:
            return json_response(error=ctx_err)

        FolderModel = get_folder_model(is_public=form.is_public)
        FileModel = get_file_model(is_public=form.is_public)

        logger.info(f'[Document] Downloading folder id: {form.id}, is_public={form.is_public}')
        folder_query = FolderModel.objects.filter(pk=form.id).order_by()
        if not form.is_public:
            folder_query = apply_tenant_filter(folder_query, request.user, strict_mode=True)
        folder = folder_query.select_related('created_by').first()

        if not folder:
            logger.error(f'[Document] Folder not found with id: {form.id}')
            return json_response(error='文件夹不存在')

        # 统一对象作用域校验（党建正向 + 普通反向隔离）
        scope_ok, scope_err = validate_folder_source_scope(
            form.system_folder, form.is_public, folder_id=form.id,
            include_root=True, protect_root=False,
        )
        if not scope_ok:
            return json_response(error=scope_err)

        # 【P0-6修复】检查是否需要异步模式
        # 统计文件数量（使用 count 而非加载全部到内存）
        total_files = self._count_folder_files(folder, FolderModel, FileModel, request.user, form.is_public)

        if total_files >= self.ASYNC_FILE_COUNT_THRESHOLD:
            return self._submit_async_pack_task(folder, request.user, form.is_public)

        # 小文件夹：同步打包（保持原有逻辑）
        return self._sync_download(folder, request.user, form.is_public)

    def _count_folder_files(self, folder, FolderModel, FileModel, user, is_public):
        """统计文件夹内的文件总数（BFS 批量计数）"""
        total = 0
        queue = [folder.id]
        visited = {folder.id}

        while queue:
            current_id = queue.pop(0)
            # 批量统计当前层的文件数
            file_count = FileModel.objects.filter(folder_id=current_id).order_by().count()
            total += file_count

            # 批量获取子文件夹
            children = FolderModel.objects.filter(parent_id=current_id).order_by().values_list('id', flat=True)
            for child_id in children:
                if child_id not in visited:
                    visited.add(child_id)
                    queue.append(child_id)

        return total

    def _submit_async_pack_task(self, folder, user, is_public):
        """【P0-6修复】提交异步打包任务"""
        try:
            from ...tasks import pack_folder_to_zip
            from ...libs.pack_task_ownership import record_ownership
            from celery import current_app as celery_app

            # 检查 Celery 连接状态
            inspector = celery_app.control.inspect()
            if inspector.active_queues() is None:
                logger.warning('[Document] Celery not available, falling back to sync mode')
                return self._sync_download(folder, user, is_public)

            # 提交异步任务
            tenant_id = getattr(user, 'tenant_id', None)
            task = pack_folder_to_zip.delay(
                folder_id=folder.id,
                is_public=is_public,
                user_id=user.id,
                tenant_id=tenant_id
            )

            # 【H-6修复】记录 task_id -> 归属，状态查询和 ready 下载均校验
            record_ownership(
                task_id=str(task.id),
                user_id=user.id,
                tenant_id=tenant_id,
                is_public=is_public,
            )

            logger.info(f'[Document] Async pack task submitted: task_id={task.id}, folder_id={folder.id}')

            return json_response(data={
                'async': True,
                'task_id': str(task.id),
                'status': 'pending',
                'message': '打包任务已提交，请稍后轮询状态'
            })

        except Exception as e:
            logger.error(f'[Document] Failed to submit async pack task: {e}', exc_info=True)
            # 降级到同步模式
            logger.info(f'[Document] Falling back to sync mode for folder id={folder.id}')
            return self._sync_download(folder, user, is_public)

    def _sync_download(self, folder, user, is_public):
        """同步打包下载（原有逻辑）"""
        FolderModel = get_folder_model(is_public=is_public)
        FileModel = get_file_model(is_public=is_public)

        zip_path = None
        try:
            # 创建临时 ZIP 文件
            zip_fd, zip_path = tempfile.mkstemp(suffix='.zip', prefix='spug_folder_')
            os.close(zip_fd)

            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                self._add_folder_to_zip(folder, zipf, '', FolderModel, FileModel, is_public, user)

            encoded_foldername = quote(folder.name)
            zip_size = os.path.getsize(zip_path)

            # 使用 StreamingHttpResponse 流式传输
            response = StreamingHttpResponse(
                self._file_iterator(zip_path, chunk_size=65536),
                content_type='application/zip'
            )
            response['Content-Disposition'] = f'attachment; filename="{encoded_foldername}.zip"; filename*=UTF-8\'\'{encoded_foldername}.zip'
            response['Content-Length'] = zip_size

            # 响应结束后清理临时文件
            def cleanup_zip():
                if zip_path and os.path.exists(zip_path):
                    try:
                        os.remove(zip_path)
                    except OSError:
                        pass

            response.on_close = cleanup_zip

            log_operation(
                action="FOLDER_DOWNLOAD",
                user=user,
                resource_type="FOLDER",
                resource_id=folder.id,
                is_public=is_public,
                folder_name=folder.name
            )
            logger.info(f'[Document] Folder sync download: {folder.name}.zip ({zip_size} bytes)')
            return response

        except Exception as e:
            if zip_path and os.path.exists(zip_path):
                try:
                    os.remove(zip_path)
                except OSError:
                    pass
            logger.error(f'[Document] Folder download failed: {folder.name}, error={e}', exc_info=True)
            raise

    def _add_folder_to_zip(self, folder, zipf, path, FolderModel, FileModel, is_public, request_user=None, visited=None):
        """【P0-2修复】使用 BFS 批量查询替代递归，解决 N+1 查询问题

        修复前：每递归一层触发 2 次 DB 查询（文件 + 子文件夹），深度嵌套时指数增长
        修复后：仅 2 次批量查询（文件夹 + 文件），查询次数从 O(N) 降至 O(1)

        Args:
            folder: 根文件夹对象
            zipf: ZipFile 对象
            path: ZIP 内部路径前缀
            FolderModel: 文件夹模型类
            FileModel: 文件模型类
            is_public: 是否公共空间
            request_user: 当前用户（用于租户过滤）
            visited: 已访问文件夹 ID 集合（用于检测循环引用）
        """
        if visited is None:
            visited = set()

        # BFS 收集所有文件夹
        folder_map, folder_children, folder_paths = self._bfs_collect_folders(
            folder, path, FolderModel, is_public, request_user, visited
        )

        # 批量查询所有文件
        files_by_folder = self._batch_query_files(
            folder_map.keys(), FolderModel, FileModel, is_public, request_user
        )

        # ZIP 写入阶段
        self._write_folders_to_zip(
            folder, folder_map, folder_children, folder_paths, files_by_folder, zipf
        )

    def _bfs_collect_folders(self, folder, path, FolderModel, is_public, request_user, visited):
        """BFS 收集所有文件夹及其路径结构"""
        folder_map = {}
        folder_children = {}
        folder_paths = {}

        queue = [folder]
        visited.add(folder.id)
        root_path = path

        while queue:
            current = queue.pop(0)
            folder_map[current.id] = current

            if current.id == folder.id:
                current_zip_path = f'{path}{current.name}/'
            else:
                parent_path = folder_paths.get(current.parent_id, root_path)
                current_zip_path = f'{parent_path}{current.name}/'
            folder_paths[current.id] = current_zip_path

            children_query = FolderModel.objects.filter(parent=current).order_by()
            if request_user and not is_public:
                children_query = apply_tenant_filter(children_query, request_user)
            children = list(children_query.select_related('created_by'))

            folder_children[current.id] = []
            for child in children:
                if child.id not in visited:
                    visited.add(child.id)
                    folder_children[current.id].append(child.id)
                    queue.append(child)

        return folder_map, folder_children, folder_paths

    def _batch_query_files(self, folder_ids, FolderModel, FileModel, is_public, request_user):
        """批量查询所有文件并按 folder_id 分组"""
        files_query = FileModel.objects.filter(folder_id__in=list(folder_ids)).order_by()
        if request_user and not is_public:
            files_query = apply_tenant_filter(files_query, request_user)

        files_by_folder = {}
        for file in files_query.select_related('created_by'):
            files_by_folder.setdefault(file.folder_id, []).append(file)
        return files_by_folder

    def _write_folders_to_zip(self, folder, folder_map, folder_children, folder_paths, files_by_folder, zipf):
        """将文件夹结构写入 ZIP（无 DB 查询）"""
        stack = [folder.id]
        while stack:
            folder_id = stack.pop()
            current_folder = folder_map[folder_id]
            current_path = folder_paths[folder_id]

            for file in files_by_folder.get(folder_id, []):
                # 【P2-2修复】路径安全检查，防止路径遍历攻击
                document_storage_base = os.path.join(settings.BASE_DIR, 'storage', 'documents')
                if not is_safe_path(document_storage_base, file.file_path):
                    logger.warning('[Document] Unsafe file path skipped: %s', file.file_path)
                    continue
                if os.path.exists(file.file_path):
                    zipf.write(file.file_path, f'{current_path}{file.name}')
                    logger.info('[Document] Added file to ZIP: %s', f'{current_path}{file.name}')
                else:
                    logger.warning('[Document] File not found: %s', file.file_path)

            # 将子文件夹入栈（逆序保证顺序正确）
            for child_id in reversed(folder_children.get(folder_id, [])):
                stack.append(child_id)

    def _file_iterator(self, file_path, chunk_size=65536):
        """【P0-1修复】分块文件迭代器，用于 StreamingHttpResponse 流式传输"""
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk


class FolderDownloadStatusView(View):
    """【P0-6新增】查询异步打包任务状态"""

    @document_auth('view')
    def get(self, request):
        """查询打包任务状态

        轮询此接口直到 status变为 success 或 failed

        Returns:
            pending: 任务进行中
            success: 打包完成，包含 zip_path
            failed: 打包失败
        """
        form, error = JsonParser(
            Argument('task_id', required=True, help='任务ID不能为空')
        ).parse(request.GET)

        if error:
            return json_response(error=error)

        try:
            from celery.result import AsyncResult
            from ...tasks import pack_folder_to_zip
            from ...libs.pack_task_ownership import (
                verify_ownership as verify_pack_ownership,
                get_ownership,
            )

            # 【H-6修复】所有状态都校验任务归属（包含 pending 阶段）
            # 之前只在 task.ready() 后校验 result，pending 阶段任意用户可探测
            if not verify_pack_ownership(form.task_id, request.user):
                return json_response(error='无权访问此打包任务', code=403)

            task = AsyncResult(form.task_id, app=pack_folder_to_zip.app)
            state = task.state
            result = task.result if task.ready() else None

            # 【H-1修复】ready 状态后做 result 双重校验（防止 cache 过期被绕过）
            if task.ready() and result and isinstance(result, dict):
                if not self._verify_task_ownership(result, request.user):
                    return json_response(error='无权访问此打包任务', code=403)

            response_data = {
                'task_id': form.task_id,
                'state': state,
                'ready': task.ready(),
            }

            if task.ready():
                if task.successful() and result:
                    response_data['status'] = 'success'
                    response_data['zip_path'] = result.get('zip_path')
                    response_data['zip_size'] = result.get('zip_size')
                    response_data['folder_name'] = result.get('folder_name')
                else:
                    response_data['status'] = 'failed'
                    response_data['error'] = str(result) if result else '任务执行失败'
            else:
                response_data['status'] = 'pending'

            logger.info(f'[Document] Pack task status: task_id={form.task_id}, state={state}')
            return json_response(data=response_data)

        except Exception as e:
            logger.error(f'[Document] Query pack task status failed: task_id={form.task_id}, error={e}', exc_info=True)
            return json_response(error=f'查询任务状态失败: {str(e)}', code=500)

    @staticmethod
    def _verify_task_ownership(result, request_user):
        """【H-1修复】校验打包任务归属

        公共空间：所有登录用户可访问（无租户隔离）
        私有空间：仅任务创建者（同用户+同租户）可访问
        管理员：跳过归属校验
        """
        if getattr(request_user, 'is_supper', False):
            return True

        is_public = result.get('is_public', False)
        if is_public:
            # 公共空间无租户隔离，所有登录用户可访问
            return True

        # 私有空间：必须同用户+同租户
        task_user_id = result.get('user_id')
        task_tenant_id = result.get('tenant_id')
        request_tenant_id = getattr(request_user, 'tenant_id', None)

        if task_user_id != request_user.id:
            return False
        if task_tenant_id != request_tenant_id:
            return False
        return True


class FolderDownloadReadyView(View):
    """【P0-6新增】下载已打包完成的 ZIP 文件"""

    @document_auth('view')
    def get(self, request):
        """下载已完成的打包任务结果

        Query Params:
            task_id: 任务ID
        """
        form, error = JsonParser(
            Argument('task_id', required=True, help='任务ID不能为空')
        ).parse(request.GET)

        if error:
            return json_response(error=error)

        try:
            from celery.result import AsyncResult
            from ...tasks import pack_folder_to_zip, PACK_TASKS_DIR
            from ...libs.pack_task_ownership import verify_ownership as verify_pack_ownership

            # 【H-6修复】ready 下载前先校验服务侧 ownership
            if not verify_pack_ownership(form.task_id, request.user):
                return json_response(error='无权访问此打包任务', code=403)

            task = AsyncResult(form.task_id, app=pack_folder_to_zip.app)

            if not task.ready():
                return json_response(error='任务尚未完成，请先轮询状态', code=400001)

            if not task.successful():
                return json_response(error='任务执行失败', code=500001)

            result = task.result

            # 【H-1修复】校验任务归属
            if not FolderDownloadStatusView._verify_task_ownership(result, request.user):
                return json_response(error='无权访问此打包任务', code=403)

            zip_path = result.get('zip_path')
            folder_name = result.get('folder_name', 'folder')

            if not zip_path or not os.path.exists(zip_path):
                logger.error(f'[Document] Pack task zip not found: zip_path={zip_path}')
                return json_response(error='打包文件不存在或已过期', code=404001)

            # 【H-1修复】路径安全复核：zip_path 必须在 PACK_TASKS_DIR 下
            if not is_safe_path(PACK_TASKS_DIR, zip_path):
                logger.error(f'[Document] Unsafe zip_path detected: {zip_path}')
                return json_response(error='打包文件路径异常', code=400)

            zip_size = os.path.getsize(zip_path)
            encoded_foldername = quote(folder_name)

            response = StreamingHttpResponse(
                self._file_iterator(zip_path, chunk_size=65536),
                content_type='application/zip'
            )
            response['Content-Disposition'] = f'attachment; filename="{encoded_foldername}.zip"; filename*=UTF-8\'\'{encoded_foldername}.zip'
            response['Content-Length'] = zip_size

            # 响应结束后清理 ZIP 文件
            def cleanup_zip():
                if zip_path and os.path.exists(zip_path):
                    try:
                        os.remove(zip_path)
                    except OSError:
                        pass

            response.on_close = cleanup_zip

            logger.info(f'[Document] Serving packed folder: {folder_name}.zip ({zip_size} bytes)')
            return response

        except Exception as e:
            logger.error(f'[Document] Download packed folder failed: task_id={form.task_id}, error={e}', exc_info=True)
            return json_response(error=f'下载失败: {str(e)}', code=500)

    def _file_iterator(self, file_path, chunk_size=65536):
        """分块文件迭代器"""
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
回收站永久删除视图
彻底删除文件（支持异步批量操作和幂等性校验）
"""

import logging
from django.views.generic import View
from django.db import transaction
from django.conf import settings
from django.core.cache import cache

from libs import json_response, JsonParser, Argument, auth
from ...models import DocumentFilePrivate, DocumentFilePublic
from ..base import log_operation
from .utils import invalidate_cache, check_permission
from ...libs.idempotency_utils import IdempotencyChecker, build_idempotency_key_from_request

logger = logging.getLogger(__name__)


class RecycleBinPermanentDeleteView(View):
    """彻底删除视图（支持异步批量操作）"""
    
    LARGE_FILE_THRESHOLD = 100 * 1024 * 1024  # 100MB
    
    @auth('document.recycle-bin.permanent_delete')
    def post(self, request):
        """彻底删除文件（支持幂等性校验）"""
        form, error = JsonParser(
            Argument('file_ids', type=list, required=True),
            Argument('async_mode', type=bool, required=False, default=False),
            Argument('idempotent_key', required=False)  # 【新增】幂等键
        ).parse(request.body)

        if error:
            return json_response(error=error)

        # 【修改】移除批量删除数量限制
        if len(form.file_ids) == 0:
            return json_response(error='请选择要删除的文件')

        # 【新增】幂等性检查
        idempotency_checker = IdempotencyChecker('recycle_bin:permanent_delete', ttl=300)
        if form.idempotent_key:
            cached_result = idempotency_checker.check(form.idempotent_key)
            if cached_result:
                logger.info(f'[RecycleBin] 幂等性命中: user={request.user.username}, files={len(form.file_ids)}')
                return json_response(data=cached_result)
        
        # 判断是否需要异步处理
        total_size = self._calculate_total_size(form.file_ids)
        need_async = form.async_mode or total_size > self.LARGE_FILE_THRESHOLD or len(form.file_ids) > 10
        
        if need_async:
            from ...tasks.cleanup import async_batch_permanent_delete
            from celery import current_app as celery_app
            
            try:
                # 检查Celery连接状态
                inspector = celery_app.control.inspect()
                active_queues = inspector.active_queues()
                logger.info(f'[RecycleBin] Celery连接状态: active_queues={active_queues is not None}')
                
                # 提交异步任务
                task = async_batch_permanent_delete.delay(form.file_ids, request.user.id)
                logger.info(f'[RecycleBin] 异步删除任务已提交: task_id={task.id}, files={len(form.file_ids)}, user={request.user.username}')

                response_data = {
                    'async': True,
                    'task_id': str(task.id),
                    'message': '删除任务已提交',
                    'file_count': len(form.file_ids),
                    'total_size': total_size
                }

                # 【新增】缓存幂等结果（5分钟）
                if form.idempotent_key:
                    idempotency_checker.cache(response_data)

                return json_response(data=response_data)
            except Exception as e:
                logger.error(f'[RecycleBin] 提交异步任务失败: {e}', exc_info=True)
                return json_response(error=f'提交删除任务失败: {str(e)}', code=500)
        
        # 同步删除
        results = []
        total_freed = 0
        
        try:
            with transaction.atomic():
                for file_id in form.file_ids:
                    result = self._permanent_delete(file_id, request.user)
                    results.append(result)
                    if result['status'] == 'success':
                        total_freed += result.get('file_size', 0)
        except Exception as e:
            logger.error(f'[RecycleBin] 批量删除事务失败: {e}')
            return json_response(error='删除操作失败')
        
        invalidate_cache(request.user.id)

        response_data = {
            'async': False,
            'success_count': sum(1 for r in results if r['status'] == 'success'),
            'failed_count': sum(1 for r in results if r['status'] == 'failed'),
            'freed_space': total_freed,
            'details': results
        }

        # 【新增】缓存幂等结果（5分钟）
        if form.idempotent_key:
            idempotency_checker.cache(response_data)

        return json_response(data=response_data)
    
    def _calculate_total_size(self, file_ids):
        """计算文件总大小"""
        total = 0
        for file_id in file_ids:
            try:
                file_obj = DocumentFilePrivate.all_objects.get(id=file_id, is_deleted=True)
                total += file_obj.file_size
            except DocumentFilePrivate.DoesNotExist:
                try:
                    file_obj = DocumentFilePublic.all_objects.get(id=file_id, is_deleted=True)
                    total += file_obj.file_size
                except DocumentFilePublic.DoesNotExist:
                    pass
        return total
    
    def _permanent_delete(self, file_id, user):
        """彻底删除单个文件"""
        logger.info(f'[RecycleBin] 尝试删除文件: file_id={file_id}, user={user.username}')
        try:
            # 先尝试私有空间
            try:
                file_obj = DocumentFilePrivate.all_objects.get(id=file_id, is_deleted=True)
                logger.info(f'[RecycleBin] 找到私密空间文件: file_id={file_id}, tenant_id={repr(file_obj.tenant_id)}')
            except DocumentFilePrivate.DoesNotExist:
                file_obj = DocumentFilePublic.all_objects.get(id=file_id, is_deleted=True)
                logger.info(f'[RecycleBin] 找到公共空间文件: file_id={file_id}, created_by={file_obj.created_by}')
            
            # 权限校验
            has_perm = check_permission(file_obj, user)
            logger.info(f'[RecycleBin] 文件权限检查结果: file_id={file_id}, result={has_perm}')
            if not has_perm:
                logger.error(f'[RecycleBin] 删除文件权限检查失败: file_id={file_id}, user={user.username}')
                return {
                    'id': file_id,
                    'status': 'failed',
                    'error': '只有管理员或文件所有者可以彻底删除文件',
                    'code': 403001
                }
            
            file_size = file_obj.file_size
            is_public = isinstance(file_obj, DocumentFilePublic)
            
            # 调用硬删除
            file_obj.delete(hard=True)
            logger.info(f'[RecycleBin] 文件删除成功: file_id={file_id}')
            
            # 记录审计日志
            log_operation(
                action="FILE_PERMANENT_DELETE",
                user=user,
                resource_type="FILE",
                resource_id=file_id,
                is_public=is_public,
                file_size=file_size
            )
            
            return {'id': file_id, 'status': 'success', 'file_size': file_size}
            
        except (DocumentFilePrivate.DoesNotExist, DocumentFilePublic.DoesNotExist):
            logger.error(f'[RecycleBin] 文件不存在: file_id={file_id}')
            return {'id': file_id, 'status': 'failed', 'error': '文件不存在或未被删除', 'code': 404001}
        except Exception as e:
            logger.error(f'[RecycleBin] 彻底删除文件失败: file_id={file_id}, error={e}', exc_info=True)
            return {'id': file_id, 'status': 'failed', 'error': '删除失败，请稍后重试'}


class RecycleBinTaskStatusView(View):
    """【新增】查询异步删除任务状态"""
    
    @auth('document.recycle-bin.permanent_delete')
    def get(self, request):
        """查询异步任务状态"""
        form, error = JsonParser(
            Argument('task_id', required=True, help='任务ID不能为空')
        ).parse(request.GET)
        
        if error:
            return json_response(error=error)
        
        try:
            from celery.result import AsyncResult
            from ...tasks.cleanup import async_batch_permanent_delete
            
            task = AsyncResult(form.task_id, app=async_batch_permanent_delete.app)
            
            # 获取任务状态
            state = task.state
            result = task.result if task.ready() else None
            
            # 构建响应
            response_data = {
                'task_id': form.task_id,
                'state': state,
                'ready': task.ready(),
                'successful': task.successful() if task.ready() else None,
            }
            
            # 如果任务完成，包含结果
            if task.ready():
                if task.successful():
                    response_data['result'] = result
                else:
                    response_data['error'] = str(result) if result else '任务执行失败'
            
            # 如果任务正在进行中，尝试获取进度信息
            if state == 'PROGRESS' and result:
                response_data['progress'] = result.get('progress', 0)
                response_data['processed'] = result.get('processed', 0)
                response_data['total'] = result.get('total', 0)
            
            logger.info(f'[RecycleBin] 查询任务状态: task_id={form.task_id}, state={state}')
            return json_response(data=response_data)
            
        except Exception as e:
            logger.error(f'[RecycleBin] 查询任务状态失败: task_id={form.task_id}, error={e}', exc_info=True)
            return json_response(error=f'查询任务状态失败: {str(e)}', code=500)

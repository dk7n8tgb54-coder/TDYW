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
from ...exceptions import DocumentPhysicalDeleteError
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
            Argument('idempotent_key', required=False),
            # 【Bug 2 修复 2026-06-08】新增 space 参数
            # - 修复前：前端只传 file_ids，后端不区分空间。
            #   DocumentFilePrivate 和 DocumentFilePublic 共享 id sequence（实测重叠 26 个 id），
            #   异步任务 _permanent_delete_single 先查 Private 表 → 公共空间文件被错误地按 Private 路径处理 → 失败
            #   同步路径虽然两边都查，但同样无法保证正确空间路由。
            # - 修复后：前端按 space 分组调用，后端按 space 路由，异步任务优先按 space 查表
            # - 向后兼容：space 缺省时保持原行为（先 Private 再 Public）
            Argument('space', required=False, default=None,
                     filter=lambda x: x in ('private', 'public', None)),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        if len(form.file_ids) == 0:
            return json_response(error='请选择要删除的文件')

        idempotency_checker = IdempotencyChecker('recycle_bin:permanent_delete', ttl=300)
        if form.idempotent_key:
            cached_result = idempotency_checker.check(form.idempotent_key)
            if cached_result:
                logger.info(f'[RecycleBin] 幂等性命中: user={request.user.username}, files={len(form.file_ids)}')
                return json_response(data=cached_result)

        total_size = self._calculate_total_size(form.file_ids, request.user)
        need_async = form.async_mode or total_size > self.LARGE_FILE_THRESHOLD or len(form.file_ids) > 10

        if need_async:
            return self._submit_async_delete(form, request.user, total_size, idempotency_checker)

        return self._sync_delete(form, request.user, idempotency_checker)

    def _submit_async_delete(self, form, user, total_size, idempotency_checker):
        """提交异步删除任务"""
        from ...tasks.cleanup import async_batch_permanent_delete
        from celery import current_app as celery_app

        try:
            inspector = celery_app.control.inspect()
            active_queues = inspector.active_queues()
            logger.info(f'[RecycleBin] Celery连接状态: active_queues={active_queues is not None}')

            # 【Bug 2 修复 2026-06-08】把 space 透传到异步任务
            task = async_batch_permanent_delete.delay(form.file_ids, user.id, form.space)
            logger.info(f'[RecycleBin] 异步删除任务已提交: task_id={task.id}, files={len(form.file_ids)}, space={form.space}, user={user.username}')

            response_data = {
                'async': True,
                'task_id': str(task.id),
                'message': '删除任务已提交',
                'file_count': len(form.file_ids),
                'total_size': total_size
            }

            if form.idempotent_key:
                idempotency_checker.cache(response_data)

            return json_response(data=response_data)
        except Exception as e:
            logger.error(f'[RecycleBin] 提交异步任务失败: {e}', exc_info=True)
            return json_response(error=f'提交删除任务失败: {str(e)}', code=500)

    def _sync_delete(self, form, user, idempotency_checker):
        """同步批量删除"""
        results = []
        total_freed = 0

        user_tenant_id = getattr(user, 'tenant_id', '') or ''

        # 【Bug 2 修复 2026-06-08】按 space 路由
        # - 修复前：all_files = private.copy() + public.update()，ID 冲突时 Public 覆盖 Private
        #   → 但 dict.get() 拿到的是 Public 对象，_delete_single_file 走 isinstance 检查 → Public 走 Public 路径
        #   → 实际不会失败（因为 Public 后写入）。但**异步路径**先查 Private 表会错。
        # - 修复后：如果 form.space 明确，按 space 单独查；否则保持向后兼容
        all_files = {}

        if form.space in ('private', None):
            private_files = {
                f.id: f for f in DocumentFilePrivate.all_objects.filter(
                    id__in=form.file_ids, is_deleted=True, tenant_id=user_tenant_id
                ).select_related('created_by').order_by()
            }
            all_files.update(private_files)

        if form.space in ('public', None):
            public_files = {
                f.id: f for f in DocumentFilePublic.all_objects.filter(
                    id__in=form.file_ids, is_deleted=True
                ).select_related('created_by').order_by()
            }
            all_files.update(public_files)

        # 【H3 修复 2026-06-08】每个 file 单独事务（SAVEPOINT-like 行为）
        # - 修复前：整个 with transaction.atomic() 包住所有 files，任一失败全部回滚
        #   → 单个 file 失败导致"已删的物理文件"无法回滚
        # - 修复后：每个 file 独立事务，单个失败不影响其他 file
        # - 与 folder_delete.py 同步路径、async_batch_permanent_delete 异步 task 语义一致
        # - 物理文件删除仍可能在事务内（受 DB 失败影响），但**单 file 隔离**已大幅降低不一致风险
        for file_id in form.file_ids:
            try:
                with transaction.atomic():
                    result = self._delete_single_file(file_id, all_files.get(file_id), user)
                    results.append(result)
                    if result['status'] == 'success':
                        total_freed += result.get('file_size', 0)
            except Exception as e:
                # 单个 file 失败被捕获：不影响其他 file
                logger.error(
                    f'[RecycleBin] 删除文件失败: file_id={file_id}, error={e}',
                    exc_info=True
                )
                results.append({
                    'id': file_id,
                    'status': 'failed',
                    'error': f'删除失败: {str(e)}',
                    'code': 500003
                })

        invalidate_cache(user.id)

        response_data = {
            'async': False,
            'success_count': sum(1 for r in results if r['status'] == 'success'),
            'failed_count': sum(1 for r in results if r['status'] == 'failed'),
            'freed_space': total_freed,
            'details': results
        }

        if form.idempotent_key:
            idempotency_checker.cache(response_data)

        return json_response(data=response_data)

    def _delete_single_file(self, file_id, file_obj, user):
        """删除单个文件"""
        if file_obj is None:
            return {'id': file_id, 'status': 'failed', 'error': '文件不存在或未被删除', 'code': 404001}

        has_perm = check_permission(file_obj, user)
        if not has_perm:
            return {'id': file_id, 'status': 'failed', 'error': '只有管理员或文件所有者可以彻底删除文件', 'code': 403001}

        file_size = file_obj.file_size
        is_public = isinstance(file_obj, DocumentFilePublic)

        try:
            file_obj.delete(hard=True)
            log_operation(
                action="FILE_PERMANENT_DELETE",
                user=user,
                resource_type="FILE",
                resource_id=file_id,
                is_public=is_public,
                file_size=file_size
            )
            return {'id': file_id, 'status': 'success', 'file_size': file_size}
        except DocumentPhysicalDeleteError as e:
            # 物理文件删除失败，已标记为待清理，返回特定错误码
            logger.warning(f'[RecycleBin] 物理文件删除失败，已标记待清理: file_id={file_id}, path={e.file_path}')
            return {'id': file_id, 'status': 'pending_clean', 'error': '文件删除失败，已加入待清理队列', 'code': 500004}
        except Exception as del_err:
            logger.error(f'[RecycleBin] 删除文件失败: file_id={file_id}, error={del_err}')
            return {'id': file_id, 'status': 'failed', 'error': '删除失败，请稍后重试', 'code': 500001}
    
    def _calculate_total_size(self, file_ids, user):
        """【P0-5修复】计算文件总大小（数据库聚合查询，完全避免内存迭代）

        Args:
            file_ids: 文件ID列表
            user: 当前用户（用于租户过滤）

        Returns:
            int: 文件总大小（字节）
        """
        from django.db.models import Sum

        user_tenant_id = getattr(user, 'tenant_id', '') or ''

        # 私密空间：使用 aggregate(Sum) 在数据库层面聚合
        private_sum = DocumentFilePrivate.all_objects.filter(
            id__in=file_ids, is_deleted=True, tenant_id=user_tenant_id
        ).aggregate(total=Sum('file_size'))['total'] or 0

        # 公共空间：使用 aggregate(Sum) 在数据库层面聚合
        public_sum = DocumentFilePublic.all_objects.filter(
            id__in=file_ids, is_deleted=True
        ).aggregate(total=Sum('file_size'))['total'] or 0

        return private_sum + public_sum
    
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
        except DocumentPhysicalDeleteError as e:
            logger.warning(f'[RecycleBin] 物理文件删除失败，已标记待清理: file_id={file_id}, path={e.file_path}')
            return {'id': file_id, 'status': 'pending_clean', 'error': '文件删除失败，已加入待清理队列', 'code': 500004}
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

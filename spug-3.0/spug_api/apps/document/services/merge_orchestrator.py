# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
合并流程编排器
封装文件合并的完整流程
"""
import os
import logging
from django.conf import settings

logger = logging.getLogger(__name__)


class MergeContext:
    """合并上下文 - 存储合并过程中的数据"""

    def __init__(self):
        self.params = None
        self.folder = None
        self.chunk_dir = None
        self.names = None
        self.tenant_id = None
        self.merge_lock = None


class ValidationStage:
    """验证阶段"""

    @staticmethod
    def validate_request(context, request, parsers, validators):
        """
        验证请求参数

        Returns:
            (is_valid, error_response) 元组
        """
        # 解析请求
        data, error = parsers['request'].parse(request)
        if error:
            return False, {'error': error}

        # 验证参数
        params, error = parsers['request'].validate_params(data)
        if error:
            return False, {'error': error}

        context.params = params

        # 验证哈希
        if not validators['hash'].validate(params['file_hash']):
            return False, {'error': '非法的文件哈希值'}

        # 验证文件名
        if not validators['file_name'](params['file_name']):
            return False, {'error': '文件名包含非法字符'}

        # 验证文件大小
        max_size = getattr(settings, 'MAX_DOCUMENT_FILE_SIZE', 10 * 1024 * 1024 * 1024)
        if params['file_size'] <= 0 or params['file_size'] > max_size:
            return False, {'error': '文件大小超出限制（最大10GB）'}

        return True, None

    @staticmethod
    def validate_folder_and_file(context, request, resolvers, validators):
        """
        验证文件夹和文件

        Returns:
            (is_valid, error_response) 元组
        """
        params = context.params

        # 解析文件夹
        folder, error = resolvers['folder'].resolve(
            params['folder_id'], params['is_public'], request.user
        )
        if error:
            return False, {'error': error}
        context.folder = folder

        # 验证文件上传
        max_size = getattr(settings, 'MAX_DOCUMENT_FILE_SIZE', 10 * 1024 * 1024 * 1024)
        is_valid, msg = validators['file_upload'](
            params['file_name'], params['file_size'], max_file_size=max_size
        )
        if not is_valid:
            return False, {'error': msg}

        # 验证分片目录
        chunk_dir, error = validators['chunk'].validate_chunk_dir(
            params['file_hash'], params['is_public'], request.user
        )
        if error:
            return False, {'error': error}
        context.chunk_dir = chunk_dir

        return True, None


class PreparationStage:
    """准备阶段"""

    @staticmethod
    def prepare(context, builders, checkers, request):
        """
        准备合并所需的资源

        Returns:
            (is_success, error_response) 元组
        """
        params = context.params

        # 构建文件路径
        context.names = builders['path'].build(params, context.folder, request.user)

        # 幂等性检查
        result, error = checkers['transfer'].check_idempotency(params['transfer_id'])
        if error:
            return False, {'error': error}
        if result:
            return False, result  # 返回已有的结果

        return True, None

    @staticmethod
    def acquire_lock(context, lock_factory):
        """
        获取合并锁

        Returns:
            (is_success, error_response) 元组
        """
        params = context.params
        context.tenant_id = getattr(context, 'tenant_id', None)
        context.merge_lock = lock_factory(
            params['file_hash'], params['is_public'], context.tenant_id
        )

        try:
            timeout = getattr(settings, 'MERGE_LOCK_TIMEOUT', 30)
            if not context.merge_lock.acquire(timeout=timeout, blocking=True):
                return False, {'error': '合并锁获取超时'}
        except Exception as e:
            logger.error(f'[Celery] Failed to acquire merge lock: {e}')
            return False, {'error': '获取合并锁失败'}

        return True, None


class ExecutionStage:
    """执行阶段"""

    @staticmethod
    def execute(context, submitter, transfer_status):
        """
        执行合并任务提交

        Returns:
            成功响应字典
        """
        params = context.params
        chunk_dir = context.chunk_dir
        tenant_id = context.tenant_id

        # 创建状态文件
        from apps.document.constants import TransferStatus
        status_file = os.path.join(chunk_dir, '.merge_status')
        with open(status_file, 'w') as f:
            f.write(TransferStatus.MERGING.value.lower())

        # 检查所有分片
        from apps.document.views.upload.merge import check_all_chunks_present
        missing_chunks = check_all_chunks_present(chunk_dir, params['total_chunks'])
        if missing_chunks:
            with open(status_file, 'w') as f:
                f.write(TransferStatus.FAILED.value.lower())
            return {'error': f'缺少分片: {missing_chunks}'}

        # 更新传输记录状态
        from apps.document.views.upload.merge import update_transfer_to_merging
        update_transfer_to_merging(params['transfer_id'], context.request.user)

        # 提交Celery任务
        from apps.document.views.upload.merge import submit_merge_task, save_task_id_to_transfer, write_merge_task_file
        task, merge_task_id, merge_task_file = submit_merge_task(
            params, context.names, chunk_dir, tenant_id, context.request
        )

        # 保存task_id到传输记录
        save_task_id_to_transfer(params['transfer_id'], task.id)

        # 写入任务文件
        write_merge_task_file(
            merge_task_file, params, params['is_public'], task.id, context.request.user
        )

        return {
            'task_id': task.id,
            'merge_task_id': merge_task_id,
            'status': 'pending',
            'message': '合并任务已提交'
        }


class MergeOrchestrator:
    """合并流程编排器"""

    def __init__(self, request, parsers, validators, resolvers, builders, checkers, lock_factory):
        self.request = request
        self.parsers = parsers
        self.validators = validators
        self.resolvers = resolvers
        self.builders = builders
        self.checkers = checkers
        self.lock_factory = lock_factory
        self.context = MergeContext()
        self.context.request = request

    def run(self):
        """
        执行完整合并流程

        Returns:
            (success, result) 元组
        """
        try:
            # 阶段1: 验证请求
            is_valid, error = ValidationStage.validate_request(
                self.context, self.request, self.parsers, self.validators
            )
            if not is_valid:
                return False, error

            # 阶段2: 验证文件夹和文件
            is_valid, error = ValidationStage.validate_folder_and_file(
                self.context, self.request, self.resolvers, self.validators
            )
            if not is_valid:
                return False, error

            # 阶段3: 准备资源
            is_success, result = PreparationStage.prepare(
                self.context, self.builders, self.checkers, self.request
            )
            if not is_success:
                return False, result if isinstance(result, dict) else {'error': result}

            # 阶段4: 获取锁
            is_success, error = PreparationStage.acquire_lock(
                self.context, self.lock_factory
            )
            if not is_success:
                return False, error

            # 阶段5: 执行合并
            try:
                result = ExecutionStage.execute(
                    self.context, None, None
                )
                return True, result
            finally:
                self._release_lock()

        except Exception as e:
            logger.error(f'[Document] Merge orchestration failed: {e}', exc_info=True)
            return False, {'error': f'合并流程执行失败: {str(e)}'}

    def _release_lock(self):
        """释放合并锁"""
        if self.context.merge_lock:
            try:
                self.context.merge_lock.release()
            except Exception as e:
                logger.error(f'[Celery] Failed to release merge lock: {e}')

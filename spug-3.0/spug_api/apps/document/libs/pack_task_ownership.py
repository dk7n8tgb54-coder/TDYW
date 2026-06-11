# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
【H-6修复】打包任务归属服务侧持久化

背景：
    原实现中，folder pack 任务的归属信息（user_id / tenant_id / is_public）
    只存在于 Celery result 字典里，task.ready() == False 时不可访问。
    任意登录用户只要猜到 task_id 就能轮询 pending 状态，存在 IDOR 风险。

方案：
    任务提交时把 task_id -> ownership 写入 Django cache，
    状态查询和 ready 下载都先查这个服务端记录。cache 生命周期 24h，
    覆盖整个任务执行 + 后续下载窗口。
"""
import logging
from typing import Optional

from django.core.cache import cache

logger = logging.getLogger(__name__)

# 缓存键前缀
PACK_TASK_OWNERSHIP_PREFIX = 'document:pack_task:owner'

# 默认缓存 24 小时（任务最长执行时间 + 下载窗口）
DEFAULT_PACK_TASK_TIMEOUT = 24 * 60 * 60


def _ownership_cache_key(task_id: str) -> str:
    return f'{PACK_TASK_OWNERSHIP_PREFIX}:{task_id}'


def record_ownership(task_id: str, user_id: int, tenant_id: Optional[str], is_public: bool) -> None:
    """提交打包任务时调用，记录 task_id -> ownership 映射。

    Args:
        task_id: Celery 任务 ID
        user_id: 任务提交者用户 ID
        tenant_id: 任务提交者租户 ID（公共空间为 None）
        is_public: 是否公共空间
    """
    try:
        cache.set(
            _ownership_cache_key(task_id),
            {
                'user_id': user_id,
                'tenant_id': tenant_id,
                'is_public': is_public,
            },
            timeout=DEFAULT_PACK_TASK_TIMEOUT,
        )
        logger.debug(f'[PackTaskOwnership] recorded: task_id={task_id}, user={user_id}')
    except Exception as e:
        # cache 写失败不应阻塞任务提交，但记日志供后续排查
        logger.warning(f'[PackTaskOwnership] failed to record: task_id={task_id}, error={e}')


def get_ownership(task_id: str) -> Optional[dict]:
    """查询 task_id 的归属记录。返回 None 表示未找到或已过期。"""
    try:
        return cache.get(_ownership_cache_key(task_id))
    except Exception as e:
        logger.warning(f'[PackTaskOwnership] failed to get: task_id={task_id}, error={e}')
        return None


def verify_ownership(task_id: str, request_user) -> bool:
    """校验当前用户是否有权访问 task_id。

    规则（与原 _verify_task_ownership 一致，便于平滑替换）：
    - 管理员（is_supper）直接通过
    - 公共空间：所有登录用户可访问
    - 私有空间：user_id + tenant_id 同时匹配

    Args:
        task_id: Celery 任务 ID
        request_user: 当前请求用户对象

    Returns:
        bool: True 表示归属合法
    """
    if getattr(request_user, 'is_supper', False):
        return True

    ownership = get_ownership(task_id)
    if not ownership:
        # 服务侧没有记录 → 拒绝（防止探测）
        return False

    if ownership.get('is_public'):
        return True

    if ownership.get('user_id') != request_user.id:
        return False

    request_tenant_id = getattr(request_user, 'tenant_id', None)
    if ownership.get('tenant_id') != request_tenant_id:
        return False

    return True

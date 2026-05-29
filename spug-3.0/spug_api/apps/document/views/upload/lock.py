# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
合并锁管理模块
提供 MergeLock 类和相关工具函数

【P0-2修复】解决内存泄漏问题：
1. 添加最大锁数量限制（MAX_LOCKS）
2. 记录锁的最后访问时间
3. 定期清理久未使用的锁
"""

import threading
import time
import logging
from collections import OrderedDict
from apps.document.constants import DEFAULT_MERGE_LOCK_TIMEOUT

logger = logging.getLogger(__name__)

MERGE_LOCK_TIMEOUT = DEFAULT_MERGE_LOCK_TIMEOUT

# 【P0-2修复】最大锁数量限制
MAX_LOCKS = 5000

# 【P0-2修复】锁闲置清理时间（秒）- 1小时
LOCK_IDLE_TIMEOUT_SECONDS = 3600

# 【P2-1修复】每次清理的锁数量
CLEANUP_LOCKS_BATCH_SIZE = 100

# 【P2-1修复】锁持有超时倍数（相对于MERGE_LOCK_TIMEOUT）
LOCK_STALE_TIMEOUT_MULTIPLIER = 2

# 【P2-1修复】定时任务调用间隔（分钟）- 用于文档说明
CLEANUP_SCHEDULE_INTERVAL_MINUTES = 10

# 全局合并锁字典 - 使用OrderedDict支持LRU
_merge_locks = OrderedDict()
_merge_locks_mutex = threading.Lock()


class MergeLock:
    """【P0-2修复】带超时的合并锁，记录最后访问时间。

    用于防止同一文件被多个进程/线程同时合并，避免数据损坏。
    记录最后访问时间支持LRU清理策略，防止内存泄漏。

    Attributes:
        lock: threading.Lock对象
        acquired_time: 锁获取时间戳，未获取时为None
        holder: 锁持有者线程ID
        last_accessed: 最后访问时间戳，用于LRU清理
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.acquired_time = None
        self.holder = None
        self.last_accessed = time.time()  # 【P0-2修复】记录最后访问时间

    def acquire(self, timeout=None, blocking=True):
        """获取锁。

        Args:
            timeout: 超时时间（秒），None表示无限等待
            blocking: 是否阻塞等待，False表示立即返回

        Returns:
            bool: 是否成功获取锁
        """
        self.last_accessed = time.time()  # 【P0-2修复】更新访问时间
        if blocking:
            acquired = self.lock.acquire(timeout=timeout)
            if acquired:
                self.acquired_time = time.time()
                self.holder = threading.get_ident()
            return acquired
        else:
            acquired = self.lock.acquire(blocking=False)
            if acquired:
                self.acquired_time = time.time()
                self.holder = threading.get_ident()
            return acquired

    def release(self):
        """释放锁。

        如果锁未被持有，调用此方法无效果。
        """
        # 【P1-4修复】使用try-except避免竞态条件
        try:
            self.lock.release()
            self.acquired_time = None
            self.holder = None
        except RuntimeError:
            # 锁未被当前线程持有，忽略
            pass

    def is_locked(self):
        """检查锁是否被持有。

        Returns:
            bool: True表示锁当前被持有
        """
        return self.lock.locked()

    def get_held_duration(self):
        """获取锁被持有的时长。

        Returns:
            float或None: 锁持有的秒数，如果未被持有则返回None
        """
        if self.acquired_time:
            return time.time() - self.acquired_time
        return None

    def get_idle_duration(self):
        """【P0-2修复】获取锁闲置时长。

        Returns:
            float: 锁未被访问的秒数，用于LRU清理决策
        """
        return time.time() - self.last_accessed


def get_merge_lock(file_hash, is_public, tenant_id):
    """
    【P0-2修复】获取按file_hash+空间类型+租户的无嵌套合并锁
    修复点：
    1. 使用LRU策略，将访问的锁移到末尾
    2. 超过最大数量时清理最久未使用的锁

    Args:
        file_hash: 文件MD5哈希值
        is_public: 是否为公共空间
        tenant_id: 租户ID

    Returns:
        MergeLock对象
    """
    if is_public:
        lock_key = f"{file_hash}_public"
    else:
        lock_key = f"{file_hash}_private_{tenant_id or 'default'}"

    with _merge_locks_mutex:
        # 【P0-2修复】如果锁已存在，移到末尾（LRU）
        if lock_key in _merge_locks:
            lock = _merge_locks.pop(lock_key)
            _merge_locks[lock_key] = lock
            return lock

        # 【P0-2修复】检查是否需要清理
        if len(_merge_locks) >= MAX_LOCKS:
            _cleanup_oldest_locks(CLEANUP_LOCKS_BATCH_SIZE)

        # 创建新锁
        lock = MergeLock()
        _merge_locks[lock_key] = lock
        return lock


def _cleanup_oldest_locks(count=CLEANUP_LOCKS_BATCH_SIZE):
    """【P0-2修复】清理最久未使用的锁。

    当锁数量超过MAX_LOCKS时，按LRU策略清理最早未使用的锁。
    只清理当前未被持有的锁，避免影响正在进行的合并任务。

    Args:
        count: 本次最多清理的锁数量，默认为CLEANUP_LOCKS_BATCH_SIZE

    Returns:
        int: 实际清理的锁数量
    """
    removed = 0
    # OrderedDict的popitem(last=False)移除最旧的项
    keys_to_remove = []
    for key, lock_obj in list(_merge_locks.items()):
        if not lock_obj.is_locked():
            keys_to_remove.append(key)
            removed += 1
            if removed >= count:
                break

    for key in keys_to_remove:
        del _merge_locks[key]

    if removed > 0:
        logger.info(f'[Document][Lock] Cleaned up {removed} oldest locks, remaining: {len(_merge_locks)}')

    return removed


def cleanup_stale_locks():
    """
    【P0-2修复】清理长时间持有或久未使用的锁
    应该由定时任务定期调用（每CLEANUP_SCHEDULE_INTERVAL_MINUTES分钟）
    """
    current_time = time.time()
    stale_count = 0
    idle_count = 0

    with _merge_locks_mutex:
        # 1. 清理长时间持有的锁（超过LOCK_STALE_TIMEOUT_MULTIPLIER倍超时时间）
        stale_locks = []
        for lock_key, lock_obj in list(_merge_locks.items()):
            if lock_obj.is_locked():
                duration = lock_obj.get_held_duration()
                if duration and duration > MERGE_LOCK_TIMEOUT * LOCK_STALE_TIMEOUT_MULTIPLIER:
                    stale_locks.append(lock_key)
                    logger.warning(
                        f'[Document][Lock] Found stale merge lock: {lock_key}, '
                        f'held for {duration:.1f}s, timeout={MERGE_LOCK_TIMEOUT}s'
                    )

        for lock_key in stale_locks:
            lock_obj = _merge_locks[lock_key]
            try:
                lock_obj.release()
                stale_count += 1
                logger.info(f'[Document][Lock] Force released stale lock: {lock_key}')
            except Exception as e:
                logger.error(f'[Document][Lock] Failed to release stale lock {lock_key}: {e}')
            finally:
                # 【P0-2修复】从字典中移除，允许GC回收
                _merge_locks.pop(lock_key, None)

        # 2. 【P0-2修复】清理久未使用的闲置锁（超过LOCK_IDLE_TIMEOUT_SECONDS未使用且当前未锁定）
        idle_keys = []
        for lock_key, lock_obj in list(_merge_locks.items()):
            if not lock_obj.is_locked() and lock_obj.get_idle_duration() > LOCK_IDLE_TIMEOUT_SECONDS:
                idle_keys.append(lock_key)

        for lock_key in idle_keys:
            del _merge_locks[lock_key]
            idle_count += 1

    total_cleaned = stale_count + idle_count
    if total_cleaned > 0:
        logger.info(
            f'[Document][Lock] Cleanup completed: {stale_count} stale locks released, '
            f'{idle_count} idle locks removed, remaining: {len(_merge_locks)}'
        )

    return {'stale_released': stale_count, 'idle_removed': idle_count}


def get_lock_stats():
    """【P0-2修复】获取锁统计信息，用于监控。

    返回当前锁的使用情况，可用于监控和调试内存泄漏问题。

    Returns:
        dict: 包含以下键的字典：
            - total_locks: 总锁数量
            - locked: 当前被持有的锁数量
            - unlocked: 当前未被持有的锁数量
            - max_locks: 最大允许锁数量
    """
    with _merge_locks_mutex:
        total = len(_merge_locks)
        locked = sum(1 for lock in _merge_locks.values() if lock.is_locked())
        return {
            'total_locks': total,
            'locked': locked,
            'unlocked': total - locked,
            'max_locks': MAX_LOCKS
        }

# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
断点续传分片获取策略
实现策略模式，支持多种数据源获取已上传分片
"""
import os
import logging
from abc import ABC, abstractmethod
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class ChunkSourceStrategy(ABC):
    """分片数据源策略基类"""

    @abstractmethod
    def get_chunks(self, chunk_dir: str, file_hash: str, user_id: int,
                   is_public: bool, total_chunks: int) -> Tuple[Optional[List[int]], bool]:
        """
        获取已上传分片列表

        Returns:
            Tuple[Optional[List[int]], bool]: (分片列表, 是否全部就绪)
                           返回(None, False)表示策略不适用
        """
        pass

    @property
    @abstractmethod
    def strategy_name(self) -> str:
        """策略名称（用于监控）"""
        pass


class SuccessMarkerStrategy(ChunkSourceStrategy):
    """_SUCCESS_标记文件策略 - 最高优先级"""

    @property
    def strategy_name(self) -> str:
        return 'success_marker'

    def __init__(self, marker_factory):
        self._marker_factory = marker_factory

    def get_chunks(self, chunk_dir: str, file_hash: str, user_id: int,
                   is_public: bool, total_chunks: int) -> Tuple[Optional[List[int]], bool]:
        if total_chunks <= 0:
            return None, False

        try:
            marker_manager = self._marker_factory(chunk_dir)
            marker_data = marker_manager.read()

            if marker_data:
                logger.debug(f'[Resume] _SUCCESS_标记文件存在')
                return list(range(total_chunks)), True
        except Exception as e:
            logger.warning(f'[Resume] 读取标记文件失败: {e}')

        return None, False


class RedisCacheStrategy(ChunkSourceStrategy):
    """Redis缓存策略 - 中等优先级"""

    @property
    def strategy_name(self) -> str:
        return 'redis_cache'

    def __init__(self, cache_factory):
        self._cache_factory = cache_factory

    def get_chunks(self, chunk_dir: str, file_hash: str, user_id: int,
                   is_public: bool, total_chunks: int) -> Tuple[Optional[List[int]], bool]:
        if total_chunks <= 0:
            return None, False

        try:
            cache_manager = self._cache_factory(file_hash, user_id, is_public)
            cached = cache_manager.get_cached_chunks()

            if cached is not None:
                logger.debug(f'[Resume] Redis缓存命中: {file_hash}')
                chunks = list(cached)
                return chunks, len(chunks) >= total_chunks
        except Exception as e:
            logger.warning(f'[Resume] 缓存查询失败: {e}')

        return None, False


class FilesystemScanStrategy(ChunkSourceStrategy):
    """文件系统扫描策略 - 最低优先级（兜底）"""

    @property
    def strategy_name(self) -> str:
        return 'filesystem_scan'

    def __init__(self, scanner_class, cache_factory=None):
        self._scanner_class = scanner_class
        self._cache_factory = cache_factory

    def get_chunks(self, chunk_dir: str, file_hash: str, user_id: int,
                   is_public: bool, total_chunks: int) -> Tuple[Optional[List[int]], bool]:
        try:
            uploaded_chunks, error = self._scanner_class.scan_uploaded_chunks(chunk_dir)

            if error:
                logger.error(f'[Resume] 扫描分片失败: {error}')
                # 扫描失败返回空列表但不更新缓存，避免错误缓存
                return [], False

            # 扫描成功，更新缓存
            if self._cache_factory:
                self._update_cache(file_hash, user_id, is_public, uploaded_chunks)

            all_ready = total_chunks > 0 and len(uploaded_chunks) >= total_chunks
            return uploaded_chunks, all_ready

        except Exception as e:
            logger.error(f'[Resume] 文件系统扫描异常: {e}')
            return [], False

    def _update_cache(self, file_hash: str, user_id: int, is_public: bool,
                      chunks: List[int]):
        """更新Redis缓存"""
        try:
            cache_manager = self._cache_factory(file_hash, user_id, is_public)
            cache_manager.set_cached_chunks(chunks)
        except Exception as e:
            logger.warning(f'[Resume] 更新缓存失败: {e}')


class ChunkStrategyContext:
    """策略上下文 - 管理策略链"""

    def __init__(self):
        self._strategies: List[ChunkSourceStrategy] = []

    def add_strategy(self, strategy: ChunkSourceStrategy):
        """添加策略（按优先级顺序）"""
        self._strategies.append(strategy)
        return self

    def execute(self, chunk_dir: str, file_hash: str, user_id: int,
                is_public: bool, total_chunks: int) -> Tuple[List[int], bool, str]:
        """
        执行策略链

        Returns:
            Tuple[List[int], bool, str]: (分片列表, 是否全部就绪, 使用的策略名)
        """
        for strategy in self._strategies:
            chunks, all_ready = strategy.get_chunks(
                chunk_dir, file_hash, user_id, is_public, total_chunks
            )
            if chunks is not None:
                return chunks, all_ready, strategy.strategy_name

        return [], False, 'none'

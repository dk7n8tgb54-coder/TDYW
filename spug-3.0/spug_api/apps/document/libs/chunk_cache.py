# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
分片缓存管理器
【P2优化】使用Redis缓存替代os.listdir，提升分片检测性能

特性：
1. 缓存已上传分片列表，避免频繁遍历文件系统
2. 支持_SUCCESS_标记文件模式
3. 自动失效机制
"""
import os
import logging
from typing import List, Optional, Set
from django.core.cache import cache
from django.conf import settings

logger = logging.getLogger(__name__)

# 缓存键前缀
CHUNK_CACHE_PREFIX = 'document:chunks'
# 默认缓存时间：30分钟
DEFAULT_CACHE_TIMEOUT = 1800


class ChunkCacheManager:
    """分片缓存管理器"""

    def __init__(self, file_hash: str, user_id: int, is_public: bool = False, transfer_id: int = None):
        self.file_hash = file_hash
        self.user_id = user_id
        self.is_public = is_public
        self.transfer_id = transfer_id
        self.cache_key = self._make_cache_key()

    def _make_cache_key(self) -> str:
        """生成缓存键
        
        【优化4】新 key 包含 transfer_id，隔离同 hash 并发上传
        格式：document:chunks:{space}:{file_hash}:{transfer_id}
        兼容：无 transfer_id 时使用旧格式 document:chunks:{space}:{file_hash}
        """
        space = 'public' if self.is_public else f'user_{self.user_id}'
        base_key = f'{CHUNK_CACHE_PREFIX}:{space}:{self.file_hash}'
        if self.transfer_id is not None:
            return f'{base_key}:{self.transfer_id}'
        return base_key

    def get_cached_chunks(self) -> Optional[Set[int]]:
        """
        获取缓存的分片列表。

        【P1修复】严格按当前 cache_key 读取，**不再自动 fallback 到旧 key**。
        原因：update_cache_after_upload 会先读再写，自动 fallback 会让新 transfer
        的"读已上传分片"误命中同 hash 的旧 transfer 缓存，然后把别人的分片集合写回新 key。

        需要兼容历史数据时，由调用方（resume 策略链）显式查 legacy key，
        并且仅在实际使用 legacy 物理目录时使用 legacy cache。

        Returns:
            分片索引集合，缓存未命中返回None
        """
        try:
            cached = cache.get(self.cache_key)
            if cached is not None:
                logger.debug(f'[ChunkCache] 缓存命中: {self.cache_key}')
                return set(cached)
            return None
        except Exception as e:
            logger.error(f'[ChunkCache] 获取缓存失败: {e}')
            return None

    @property
    def legacy_cache_key(self) -> str:
        """
        【P1修复】对外暴露旧格式 cache_key，仅供 resume 策略链显式查询。
        不要在 update_cache_after_upload 等"写"路径中使用。
        """
        space = 'public' if self.is_public else f'user_{self.user_id}'
        return f'{CHUNK_CACHE_PREFIX}:{space}:{self.file_hash}'

    def set_cached_chunks(self, chunks: List[int], timeout: int = DEFAULT_CACHE_TIMEOUT) -> bool:
        """
        缓存分片列表
        
        Args:
            chunks: 分片索引列表
            timeout: 缓存过期时间（秒）
            
        Returns:
            是否成功
        """
        try:
            cache.set(self.cache_key, chunks, timeout=timeout)
            logger.debug(f'[ChunkCache] 缓存已设置: {self.file_hash}, 分片数: {len(chunks)}')
            return True
        except Exception as e:
            logger.error(f'[ChunkCache] 设置缓存失败: {e}')
            return False

    def delete_cache(self) -> bool:
        """
        删除缓存
        
        Returns:
            是否成功
        """
        try:
            cache.delete(self.cache_key)
            logger.debug(f'[ChunkCache] 缓存已删除: {self.file_hash}')
            return True
        except Exception as e:
            logger.error(f'[ChunkCache] 删除缓存失败: {e}')
            return False

    def update_cache_after_upload(self, chunk_index: int, total_chunks: int) -> bool:
        """
        上传分片后更新缓存
        
        Args:
            chunk_index: 新上传的分片索引
            total_chunks: 总分片数
            
        Returns:
            是否成功
        """
        try:
            cached = self.get_cached_chunks()
            if cached is not None:
                cached.add(chunk_index)
                self.set_cached_chunks(list(cached))
                
                # 如果所有分片都已上传，延长缓存时间
                if len(cached) >= total_chunks:
                    self.set_cached_chunks(list(cached), timeout=3600)  # 1小时
                    logger.info(f'[ChunkCache] 所有分片已上传，缓存已更新: {self.file_hash}')
            return True
        except Exception as e:
            logger.error(f'[ChunkCache] 更新缓存失败: {e}')
            return False


class SuccessMarkerManager:
    """_SUCCESS_标记文件管理器"""

    MARKER_FILENAME = '_SUCCESS_'

    def __init__(self, chunk_dir: str):
        self.chunk_dir = chunk_dir
        self.marker_path = os.path.join(chunk_dir, self.MARKER_FILENAME)

    def exists(self) -> bool:
        """检查标记文件是否存在"""
        return os.path.exists(self.marker_path)

    def create(self, total_chunks: int, file_hash: str) -> bool:
        """
        创建成功标记文件
        
        Args:
            total_chunks: 总分片数
            file_hash: 文件哈希
            
        Returns:
            是否成功
        """
        try:
            from django.utils import timezone
            with open(self.marker_path, 'w') as f:
                f.write(f'completed_at:{timezone.now().isoformat()}\n')
                f.write(f'total_chunks:{total_chunks}\n')
                f.write(f'file_hash:{file_hash}\n')
            logger.info(f'[SuccessMarker] 标记文件已创建: {self.marker_path}')
            return True
        except Exception as e:
            logger.error(f'[SuccessMarker] 创建标记文件失败: {e}')
            return False

    def read(self) -> Optional[dict]:
        """
        读取标记文件内容
        
        Returns:
            标记文件内容字典，不存在返回None
        """
        if not self.exists():
            return None

        try:
            result = {}
            with open(self.marker_path, 'r') as f:
                for line in f:
                    if ':' in line:
                        key, value = line.strip().split(':', 1)
                        result[key] = value
            return result
        except Exception as e:
            logger.error(f'[SuccessMarker] 读取标记文件失败: {e}')
            return None

    def delete(self) -> bool:
        """删除标记文件"""
        try:
            if self.exists():
                os.remove(self.marker_path)
                logger.debug(f'[SuccessMarker] 标记文件已删除: {self.marker_path}')
            return True
        except Exception as e:
            logger.error(f'[SuccessMarker] 删除标记文件失败: {e}')
            return False


def get_chunk_cache_manager(file_hash: str, user_id: int, is_public: bool = False, transfer_id: int = None) -> ChunkCacheManager:
    """
    获取分片缓存管理器实例
    
    Args:
        file_hash: 文件哈希
        user_id: 用户ID
        is_public: 是否公共空间
        transfer_id: 传输记录ID（可选，用于缓存隔离）
        
    Returns:
        ChunkCacheManager实例
    """
    return ChunkCacheManager(file_hash, user_id, is_public, transfer_id)


def get_success_marker_manager(chunk_dir: str) -> SuccessMarkerManager:
    """
    获取标记文件管理器实例
    
    Args:
        chunk_dir: 分片目录路径
        
    Returns:
        SuccessMarkerManager实例
    """
    return SuccessMarkerManager(chunk_dir)

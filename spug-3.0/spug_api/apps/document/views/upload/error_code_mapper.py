# Copyright: (c) OpenSpug Organization
# Released under the AGPL-3.0 License.
"""
错误码映射器
支持配置化的错误消息到错误码映射
"""
from typing import List, Tuple, Optional


class ErrorCodeMapper:
    """错误码映射器"""

    # 类常量：错误码映射表（支持动态扩展）
    ERROR_CODE_MAPPINGS: List[Tuple[List[str], str]] = [
        (['合并', 'merge'], 'MERGE_FAILED'),
        (['磁盘', 'disk', '空间不足', 'no space'], 'DISK_ERROR'),
        (['timeout', '超时', 'time out'], 'TIMEOUT'),
        (['网络', 'network', '连接', 'connection'], 'NETWORK_ERROR'),
        (['权限', 'permission', '拒绝', 'denied'], 'PERMISSION_ERROR'),
    ]

    # 默认错误码
    DEFAULT_ERROR_CODE = 'GENERAL_ERROR'

    @classmethod
    def map(cls, error_message: Optional[str]) -> str:
        """
        将错误消息映射为错误码

        Args:
            error_message: 错误消息文本

        Returns:
            str: 错误码
        """
        if not error_message:
            return cls.DEFAULT_ERROR_CODE

        error_msg_lower = error_message.lower()

        for keywords, code in cls.ERROR_CODE_MAPPINGS:
            if any(kw in error_message or kw in error_msg_lower for kw in keywords):
                return code

        return cls.DEFAULT_ERROR_CODE

    @classmethod
    def add_mapping(cls, keywords: List[str], code: str):
        """动态添加映射（用于扩展）"""
        cls.ERROR_CODE_MAPPINGS.append((keywords, code))

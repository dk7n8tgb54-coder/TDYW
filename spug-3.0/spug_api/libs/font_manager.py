"""
字体管理模块
处理 PDF 生成时的中文字体注册。

字体文件位于 libs/fonts/，被 runlog/duty/device/department_duty_log 等
PDF 导出模块共享复用，避免各模块重复实现注册逻辑。

注册优先级：容器内嵌字体 → 项目内嵌字体 → 系统字体。
"""

import os
import logging
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

logger = logging.getLogger(__name__)

# 注册到 reportlab 的字体名，供 ParagraphStyle / TableStyle / canvas.setFont 使用
FONT_NAME = 'SimHei'

# 全局字体注册状态
_FONT_REGISTERED = False


class FontManager:
    """字体管理器 - 负责注册和获取中文字体"""

    # 内嵌字体文件名（按优先级）
    EMBEDDED_FONTS = ['simhei.ttf', 'simhei.otf']

    # Windows 系统字体路径
    WINDOWS_FONTS = [
        r'C:\Windows\Fonts\simhei.ttf',
        r'C:\Windows\Fonts\simsun.ttc',
        r'C:\Windows\Fonts\msyh.ttc',
    ]

    # Linux 系统字体路径
    LINUX_FONTS = [
        '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
        '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
        '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
    ]

    # 容器内字体路径（生产环境）
    CONTAINER_FONT_DIR = '/data/spug/spug_api/libs/fonts'

    @classmethod
    def register_chinese_font(cls, debug_logger=None):
        """
        注册中文字体。

        按优先级依次尝试：容器内嵌字体 → 项目内嵌字体 → 系统字体。
        成功注册后全局缓存，后续调用直接返回。

        Args:
            debug_logger: 可选的调试日志函数

        Returns:
            bool: 是否成功注册字体
        """
        global _FONT_REGISTERED

        log = debug_logger or logger.debug

        if _FONT_REGISTERED:
            log('Font already registered, skipping registration')
            return True

        font_paths = cls._collect_font_paths(log)

        for font_path in font_paths:
            if cls._try_register_font(font_path, log):
                _FONT_REGISTERED = True
                return True

        logger.warning('No Chinese font found, PDF text may display as squares')
        return False

    @classmethod
    def _collect_font_paths(cls, log):
        """收集所有可能的字体路径（按优先级排序）"""
        font_paths = []

        # 1. 容器内字体（生产环境优先）
        if os.path.exists(cls.CONTAINER_FONT_DIR):
            for font_file in cls.EMBEDDED_FONTS:
                font_path = os.path.join(cls.CONTAINER_FONT_DIR, font_file)
                if os.path.exists(font_path):
                    font_paths.append(font_path)

        # 2. 项目内嵌字体（libs/fonts，相对于本文件）
        project_fonts_dir = os.path.join(os.path.dirname(__file__), 'fonts')
        if os.path.exists(project_fonts_dir):
            for font_file in cls.EMBEDDED_FONTS:
                font_path = os.path.join(project_fonts_dir, font_file)
                if os.path.exists(font_path):
                    font_paths.append(font_path)

        # 3. 系统字体
        if os.name == 'nt':
            font_paths.extend(cls.WINDOWS_FONTS)
        else:
            font_paths.extend(cls.LINUX_FONTS)

        return font_paths

    @classmethod
    def _try_register_font(cls, font_path, log):
        """尝试注册单个字体文件"""
        if not os.path.exists(font_path):
            return False

        try:
            pdfmetrics.registerFont(TTFont(FONT_NAME, font_path))
            log(f'Registered font: {font_path}')
            return True
        except Exception as e:
            log(f'Failed to register font {font_path}: {e}')
            return False

    @classmethod
    def is_font_registered(cls):
        """检查字体是否已注册"""
        return _FONT_REGISTERED

    @classmethod
    def reset_font_state(cls):
        """重置字体注册状态（用于测试）"""
        global _FONT_REGISTERED
        _FONT_REGISTERED = False


def register_chinese_font(debug_logger=None):
    """便捷函数：注册中文字体，等价于 FontManager.register_chinese_font。"""
    return FontManager.register_chinese_font(debug_logger=debug_logger)

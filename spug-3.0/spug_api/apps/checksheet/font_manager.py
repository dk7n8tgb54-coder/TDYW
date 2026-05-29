"""
字体管理模块
处理PDF生成时的中文字体注册
"""

import os
import logging
from django.conf import settings
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

logger = logging.getLogger(__name__)

# 全局字体注册状态
_FONT_REGISTERED = False


class FontManager:
    """字体管理器 - 负责注册和获取中文字体"""

    # 内嵌字体文件名
    EMBEDDED_FONTS = ['simhei.ttf', 'simhei.otf']

    # Windows系统字体路径
    WINDOWS_FONTS = [
        r'C:\Windows\Fonts\simhei.ttf',
        r'C:\Windows\Fonts\simsun.ttc',
        r'C:\Windows\Fonts\msyh.ttc',
    ]

    # Linux系统字体路径
    LINUX_FONTS = [
        '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
        '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
        '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
    ]

    # 容器内字体路径
    CONTAINER_FONT_DIR = '/data/spug/spug_api/apps/checksheet/fonts'

    @classmethod
    def register_chinese_font(cls, debug_logger=None):
        """
        注册中文字体

        Args:
            debug_logger: 可选的调试日志函数

        Returns:
            bool: 是否成功注册字体
        """
        global _FONT_REGISTERED

        log = debug_logger or logger.debug

        # 如果已经注册过，直接返回
        if _FONT_REGISTERED:
            log('Font already registered, skipping registration')
            return True

        log('Registering font for the first time')

        # 收集所有可能的字体路径
        font_paths = cls._collect_font_paths(log)
        log(f'Font search paths: {font_paths}')

        # 尝试注册字体
        for font_path in font_paths:
            log(f'Trying to register font: {font_path}')
            if cls._try_register_font(font_path, log):
                _FONT_REGISTERED = True
                return True

        log('Warning: No Chinese font found, text may display as squares')
        return False

    @classmethod
    def _collect_font_paths(cls, log):
        """收集所有可能的字体路径（按优先级排序）"""
        font_paths = []

        # 1. 容器内字体（生产环境优先）
        if os.path.exists(cls.CONTAINER_FONT_DIR):
            log(f'Found container font dir: {cls.CONTAINER_FONT_DIR}')
            for font_file in cls.EMBEDDED_FONTS:
                font_path = os.path.join(cls.CONTAINER_FONT_DIR, font_file)
                if os.path.exists(font_path):
                    font_paths.append(font_path)

        # 2. 项目内嵌字体
        project_fonts_dir = os.path.join(os.path.dirname(__file__), 'fonts')
        log(f'Project fonts dir: {project_fonts_dir}')
        if os.path.exists(project_fonts_dir):
            log(f'Fonts dir contents: {os.listdir(project_fonts_dir)}')
            for font_file in cls.EMBEDDED_FONTS:
                font_path = os.path.join(project_fonts_dir, font_file)
                if os.path.exists(font_path):
                    font_paths.append(font_path)

        # 3. 系统字体
        if os.name == 'nt':  # Windows
            font_paths.extend(cls.WINDOWS_FONTS)
        else:  # Linux
            font_paths.extend(cls.LINUX_FONTS)

        return font_paths

    @classmethod
    def _try_register_font(cls, font_path, log):
        """尝试注册单个字体文件"""
        if not os.path.exists(font_path):
            log(f'Font path does not exist: {font_path}')
            return False

        try:
            pdfmetrics.registerFont(TTFont('SimHei', font_path))
            log(f'Registered font SUCCESS: {font_path}')

            # 验证字体是否真的注册成功
            from reportlab.pdfbase.pdfmetrics import getFont
            test_font = getFont('SimHei')
            log(f'Verification - SimHei font: {test_font}')
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

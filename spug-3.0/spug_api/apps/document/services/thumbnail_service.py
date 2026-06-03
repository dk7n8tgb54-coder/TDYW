# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
缩略图生成服务
使用 Pillow 生成图片缩略图
"""
import os
import logging
from PIL import Image

logger = logging.getLogger(__name__)

# 缩略图配置
THUMBNAIL_SIZE = (200, 200)  # 最大尺寸，保持比例
THUMBNAIL_QUALITY = 85  # JPEG 质量
THUMBNAIL_FORMAT = 'JPEG'  # 输出格式

# 支持的图片格式
SUPPORTED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}


class ThumbnailGenerator:
    """缩略图生成器"""

    @staticmethod
    def is_supported_image(file_path):
        """判断是否为支持的图片格式"""
        ext = os.path.splitext(file_path)[1].lower()
        return ext in SUPPORTED_IMAGE_EXTENSIONS

    @staticmethod
    def generate_thumbnail(file_path, thumbnail_dir, physical_name):
        """
        生成缩略图

        Args:
            file_path: 原始图片路径
            thumbnail_dir: 缩略图存储目录
            physical_name: 缩略图文件名（使用原文件的物理名）

        Returns:
            str: 缩略图路径，失败返回 None
        """
        try:
            # 检查是否支持
            if not ThumbnailGenerator.is_supported_image(file_path):
                logger.debug(f'[Thumbnail] Not a supported image: {file_path}')
                return None

            # 创建缩略图目录
            os.makedirs(thumbnail_dir, exist_ok=True)

            # 生成缩略图文件名：在物理名后加 _thumb
            name_without_ext, ext = os.path.splitext(physical_name)
            thumbnail_name = f"{name_without_ext}_thumb.jpg"
            thumbnail_path = os.path.join(thumbnail_dir, thumbnail_name)

            # 检查缩略图是否已存在（避免重复生成）
            if os.path.exists(thumbnail_path):
                logger.info(f'[Thumbnail] Thumbnail already exists: {thumbnail_path}')
                return thumbnail_path

            # 打开并生成缩略图
            with Image.open(file_path) as img:
                # 转换为 RGB（JPEG 不支持 RGBA）
                if img.mode in ('RGBA', 'P', 'LA'):
                    img = img.convert('RGB')

                # 生成缩略图（保持比例）
                img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)

                # 保存缩略图
                img.save(thumbnail_path, THUMBNAIL_FORMAT, quality=THUMBNAIL_QUALITY, optimize=True)

            logger.info(f'[Thumbnail] Generated: {thumbnail_path}')
            return thumbnail_path

        except Exception as e:
            logger.error(f'[Thumbnail] Failed to generate thumbnail for {file_path}: {e}')
            return None

    @staticmethod
    def delete_thumbnail(thumbnail_path):
        """删除缩略图"""
        try:
            if thumbnail_path and os.path.exists(thumbnail_path):
                os.remove(thumbnail_path)
                logger.info(f'[Thumbnail] Deleted: {thumbnail_path}')
                return True
        except Exception as e:
            logger.error(f'[Thumbnail] Failed to delete thumbnail {thumbnail_path}: {e}')
        return False


def get_thumbnail_dir(file_path):
    """
    获取缩略图存储目录
    缩略图存储在原图的同一目录的 thumbnails 子目录下

    Args:
        file_path: 原始文件路径

    Returns:
        str: 缩略图目录路径
    """
    return os.path.join(os.path.dirname(file_path), 'thumbnails')


def generate_thumbnail_for_file(file_path, physical_name):
    """
    为文件生成缩略图的便捷函数

    Args:
        file_path: 原始文件路径
        physical_name: 文件物理名

    Returns:
        str: 缩略图路径，失败返回 None
    """
    thumbnail_dir = get_thumbnail_dir(file_path)
    return ThumbnailGenerator.generate_thumbnail(file_path, thumbnail_dir, physical_name)
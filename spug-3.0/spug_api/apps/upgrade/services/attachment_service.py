# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
附件服务 - 上传/清理/路径管理
"""
import os
import uuid
import logging
from django.conf import settings
from django.utils import timezone

from ..constants import ATTACHMENT_MAX_SIZE_MB, ATTACHMENT_ALLOWED_TYPES, ATTACHMENT_UPLOAD_DIR

logger = logging.getLogger(__name__)


class AttachmentService:
    """附件服务 - 统一管理附件上传与清理"""

    @staticmethod
    def upload_attachment(file, user):
        """上传单个附件

        Args:
            file: 上传的文件对象
            user: 当前请求用户

        Returns:
            tuple: (url, error)
        """
        # 校验文件类型
        if file.content_type not in ATTACHMENT_ALLOWED_TYPES:
            return None, f'仅支持 {", ".join(ATTACHMENT_ALLOWED_TYPES)} 格式'

        # 校验文件大小
        if file.size > ATTACHMENT_MAX_SIZE_MB * 1024 * 1024:
            return None, f'文件大小不能超过 {ATTACHMENT_MAX_SIZE_MB}MB'

        # 生成存储路径
        date_path = timezone.now().strftime('%Y%m')
        save_dir = os.path.join(settings.MEDIA_ROOT, ATTACHMENT_UPLOAD_DIR, date_path)
        os.makedirs(save_dir, exist_ok=True)

        # 生成唯一文件名
        ext = os.path.splitext(file.name)[1]
        filename = f'{uuid.uuid4().hex}{ext}'
        file_path = os.path.join(save_dir, filename)

        # 保存文件
        try:
            with open(file_path, 'wb+') as destination:
                for chunk in file.chunks():
                    destination.write(chunk)
        except OSError as e:
            logger.error(f'[Upgrade] 附件保存失败: {e}')
            return None, '附件保存失败'

        # 返回访问 URL
        url = f'/{ATTACHMENT_UPLOAD_DIR}/{date_path}/{filename}'
        return url, None

    @staticmethod
    def clean_orphaned_attachments(old_attachments, new_attachments):
        """清理被移除的附件文件

        Args:
            old_attachments: 原附件URL列表
            new_attachments: 新附件URL列表
        """
        removed = set(old_attachments) - set(new_attachments)
        for url in removed:
            try:
                relative_path = url.lstrip('/')
                full_path = os.path.join(settings.MEDIA_ROOT, relative_path)
                if os.path.exists(full_path):
                    os.remove(full_path)
            except OSError as e:
                logger.warning(f'[Upgrade] 清理附件失败: {e}')

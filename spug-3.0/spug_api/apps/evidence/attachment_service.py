# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""通用附件服务 - 跨业务模块共用

设计要点：
- 文件落盘逻辑统一（文件名清洗、重名加序号、SHA256 计算）
- 业务对象存在性校验由调用方注入（evidence 不知道 upgrade 的 UpgradeRecord 是否存在）
- 软删除保留物理文件和 DB 记录作为证据痕迹
- 配置（允许扩展名、大小上限、存储子目录）由调用方传入，各模块可自定义

使用示例：
    from apps.evidence.attachment_service import AttachmentService
    att, error = AttachmentService.upload(
        file=request.FILES.get('file'),
        user=request.user,
        module='upgrade',
        object_type='record',
        object_id=record_id,
        config=UpgradeAttachmentConfig,  # 各模块自定义配置
        existence_checker=lambda user, oid: _get_record(oid, user),  # 业务对象校验
    )
"""
import os
import re
import logging
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple
from urllib.parse import quote

from django.conf import settings
from django.http import FileResponse
from django.utils import timezone

from libs import human_datetime
from libs.tenant_utils import apply_tenant_filter

from .models import EvidenceAttachment

logger = logging.getLogger(__name__)


@dataclass
class AttachmentConfig:
    """附件配置（各模块可自定义实例）"""
    allowed_extensions: tuple = (
        # 压缩包
        '.zip', '.rar', '.7z', '.tar', '.gz', '.bz2',
        # 安装包/镜像
        '.exe', '.msi', '.deb', '.rpm', '.iso', '.img',
        # 脚本/代码
        '.sh', '.py', '.sql', '.json', '.yaml', '.yml', '.conf',
        # 文档
        '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt', '.md',
        # 图片
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp',
    )
    max_size_mb: int = 500
    upload_dir: str = 'attachments'  # MEDIA_ROOT 下的子目录


# 默认配置（通用场景）
DefaultAttachmentConfig = AttachmentConfig()


class AttachmentService:
    """通用附件服务 - 上传/列表/下载/删除"""

    # ---------------- 私有工具 ----------------

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """文件名清洗：防路径穿越、移除危险字符"""
        safe = os.path.basename(name)
        safe = safe.replace('..', '').replace('/', '').replace('\\', '').replace('\x00', '')
        return safe or 'attachment'

    @staticmethod
    def _unique_disk_name(save_dir: str, safe_name: str) -> Tuple[str, str]:
        """遇重名自动加序号：xxx.zip → xxx_1.zip，返回 (disk_name, file_path)"""
        disk_name = safe_name
        file_path = os.path.join(save_dir, disk_name)
        counter = 1
        base, ext = os.path.splitext(safe_name)
        while os.path.exists(file_path):
            disk_name = f'{base}_{counter}{ext}'
            file_path = os.path.join(save_dir, disk_name)
            counter += 1
        return disk_name, file_path

    @staticmethod
    def _compute_sha256(file_path: str) -> str:
        """流式计算文件 SHA256，失败返回空串（不阻断上传）"""
        try:
            from .services import compute_attachment_hash
            with open(file_path, 'rb') as f:
                return compute_attachment_hash(f)
        except Exception as e:
            logger.warning(f'[Evidence] 附件 SHA256 计算失败: {e}')
            return ''

    @staticmethod
    def _safe_file_path(file_path: str) -> Optional[str]:
        """路径安全检查，返回绝对路径或 None（非法）"""
        media_real = os.path.realpath(settings.MEDIA_ROOT)
        file_real = os.path.realpath(file_path)
        if not file_real.startswith(media_real):
            return None
        if not os.path.exists(file_real):
            return None
        return file_real

    # ---------------- 公共接口 ----------------

    @staticmethod
    def validate(file, config: AttachmentConfig) -> Tuple[Optional[str], Optional[str]]:
        """校验文件类型与大小，返回 (ext, error)"""
        _, ext = os.path.splitext(file.name)
        ext = ext.lower()
        if ext not in config.allowed_extensions:
            return None, f'不支持的文件类型，允许：{", ".join(config.allowed_extensions)}'
        if file.size > config.max_size_mb * 1024 * 1024:
            return None, f'文件大小不能超过 {config.max_size_mb}MB'
        return ext, None

    @staticmethod
    def _sanitize_path_segment(segment: str) -> str:
        """路径段安全清洗：只允许字母/数字/下划线/中划线，其余替换为 _"""
        if segment is None or str(segment).strip() == '':
            return 'default'
        safe = re.sub(r'[^A-Za-z0-9_-]', '_', str(segment))
        return safe or 'default'

    @staticmethod
    def _cleanup_empty_dirs(file_path: str, stop_dir: str = None) -> None:
        """删除文件后向上清理空目录（仅 os.rmdir，遇到非空目录自动停止，失败只记日志）"""
        try:
            parent = os.path.dirname(os.path.abspath(file_path))
            media_real = os.path.realpath(settings.MEDIA_ROOT)
            stop_real = os.path.realpath(stop_dir) if stop_dir else media_real
            while parent and os.path.abspath(parent) != os.path.abspath(stop_real):
                if not os.path.isdir(parent):
                    break
                try:
                    os.rmdir(parent)  # 仅删除空目录，非空会抛 OSError
                except OSError:
                    break  # 目录非空或无权限，停止向上清理
                parent = os.path.dirname(parent)
        except Exception as e:
            logger.warning(f'[Evidence] 空目录清理失败: {e}')

    @staticmethod
    def save_file(file, config: AttachmentConfig, extra_path_parts: List[str] = None) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """保存文件到磁盘，返回 (disk_name, file_path, relative_path, error)

        - extra_path_parts 为空时保持默认行为：自动追加 YYYYMM 月份子目录
        - extra_path_parts 非空时：由调用方完整指定业务子目录（不再自动追加月份），
          例如 ['tenant_xxx', '202607', 'record_123']
        """
        safe_name = AttachmentService._sanitize_filename(file.name)
        if extra_path_parts:
            # 调用方完整控制子目录结构（多租户/业务对象隔离场景）
            sub_parts = [AttachmentService._sanitize_path_segment(p) for p in extra_path_parts]
            save_dir = os.path.join(settings.MEDIA_ROOT, config.upload_dir, *sub_parts)
            rel_parts = '/'.join(sub_parts)
        else:
            date_path = timezone.now().strftime('%Y%m')
            save_dir = os.path.join(settings.MEDIA_ROOT, config.upload_dir, date_path)
            rel_parts = date_path
        os.makedirs(save_dir, exist_ok=True)

        disk_name, file_path = AttachmentService._unique_disk_name(save_dir, safe_name)
        try:
            with open(file_path, 'wb+') as destination:
                for chunk in file.chunks():
                    destination.write(chunk)
        except OSError as e:
            logger.error(f'[Evidence] 附件保存失败: {e}')
            return None, None, None, '附件保存失败'

        relative_path = f'{config.upload_dir}/{rel_parts}/{disk_name}'
        return disk_name, file_path, relative_path, None

    @staticmethod
    def upload(file, user, module: str, object_type: str, object_id,
               config: AttachmentConfig = DefaultAttachmentConfig,
               extra_path_parts: List[str] = None) -> Tuple[Optional[EvidenceAttachment], Optional[str]]:
        """上传附件并入库，返回 (attachment, error)

        业务对象存在性校验应由调用方在调用前完成。
        extra_path_parts：可选的业务子目录段，传入后由调用方完整控制目录结构（不再自动追加月份）。
        """
        ext, error = AttachmentService.validate(file, config)
        if error:
            return None, error

        disk_name, file_path, relative_path, error = AttachmentService.save_file(file, config, extra_path_parts)
        if error:
            return None, error

        file_hash = AttachmentService._compute_sha256(file_path)
        att = EvidenceAttachment.objects.create(
            tenant_id=getattr(user, 'tenant_id', ''),
            module=module,
            object_type=object_type,
            object_id=str(object_id),
            file_name=os.path.basename(file.name),
            file_path=relative_path,
            file_size=file.size,
            file_ext=ext,
            file_hash_sha256=file_hash,
            uploaded_by_id=getattr(user, 'id', None),
            uploaded_by_name=user.nickname or user.username,
        )
        return att, None

    @staticmethod
    def list(user, module: str, object_type: str, object_id):
        """获取附件列表（已过滤软删除），返回 list"""
        qs = apply_tenant_filter(
            EvidenceAttachment.objects.filter(
                module=module, object_type=object_type,
                object_id=str(object_id), is_deleted=False,
            ),
            user,
        ).order_by('-uploaded_at', '-id')
        data = []
        for att in qs:
            item = att.to_view()
            item['uploaded_by_name'] = att.uploaded_by_name or '-'
            item['created_at'] = att.uploaded_at  # 前端统一字段名
            data.append(item)
        return data

    @staticmethod
    def download_response(user, attachment_id) -> FileResponse:
        """获取下载响应，返回 (response, error)"""
        qs = apply_tenant_filter(EvidenceAttachment.objects.all(), user)
        att = qs.filter(pk=attachment_id).first()
        if not att:
            return None, '附件不存在或无权限访问'

        full_path = os.path.join(settings.MEDIA_ROOT, att.file_path)
        safe_path = AttachmentService._safe_file_path(full_path)
        if safe_path is None:
            logger.error(f'[Evidence] 下载路径非法或不存在: {att.file_path}')
            return None, '文件不存在'

        encoded_filename = quote(att.file_name)
        response = FileResponse(
            open(safe_path, 'rb'),
            content_type='application/octet-stream',
        )
        response['Content-Disposition'] = (
            f'attachment; filename="{encoded_filename}"; '
            f"filename*=UTF-8''{encoded_filename}"
        )
        response['Content-Length'] = os.path.getsize(safe_path)
        return response, None

    @staticmethod
    def _remove_physical_file(att: EvidenceAttachment) -> Optional[str]:
        """删除附件对应的物理文件，返回 error 或 None（None 表示可继续软删除数据库记录）

        - 路径非法（穿越 MEDIA_ROOT）：返回错误，调用方不应软删除
        - 物理文件不存在：记 warning，返回 None（允许继续软删除）
        - 删除失败（权限/占用等）：返回错误，调用方不应软删除
        - 删除成功：清理空目录（失败不影响），返回 None
        """
        full_path = os.path.join(settings.MEDIA_ROOT, att.file_path)
        media_real = os.path.realpath(settings.MEDIA_ROOT)
        file_real = os.path.realpath(full_path)
        if not file_real.startswith(media_real + os.sep) and file_real != media_real:
            logger.error(f'[Evidence] 附件路径非法（不在 MEDIA_ROOT 下）: {att.file_path}')
            return '附件文件路径非法，无法删除'
        if not os.path.exists(file_real):
            logger.warning(f'[Evidence] 物理文件不存在，仅删除数据库记录: {att.file_path}')
            return None
        try:
            os.remove(file_real)
        except OSError as e:
            logger.error(f'[Evidence] 物理文件删除失败: {att.file_path} {e}')
            return '附件文件删除失败，请稍后重试'
        logger.info(f'[Evidence] 物理文件已删除: {att.file_path}')
        AttachmentService._cleanup_empty_dirs(file_real)
        return None

    @staticmethod
    def soft_delete(user, attachment_id, reason='', delete_file: bool = False) -> Optional[str]:
        """软删除附件，返回 error 或 None

        delete_file=True 时先删除物理文件，删除成功后再软删除数据库记录；
        物理文件不存在则记 warning 并继续软删除；物理删除失败则返回错误且不软删除。
        """
        qs = apply_tenant_filter(EvidenceAttachment.objects.all(), user)
        att = qs.filter(pk=attachment_id, is_deleted=False).first()
        if not att:
            return '附件不存在或无权限删除'

        if delete_file:
            error = AttachmentService._remove_physical_file(att)
            if error:
                return error

        att.is_deleted = True
        att.deleted_at = human_datetime()
        att.deleted_by_id = getattr(user, 'id', None)
        att.deleted_by_name = user.nickname or user.username
        att.delete_reason = reason or ''
        att.save(update_fields=[
            'is_deleted', 'deleted_at', 'deleted_by_id',
            'deleted_by_name', 'delete_reason',
        ])
        logger.info(
            f'[Evidence] 附件软删除 ID={att.id} 文件={att.file_name} '
            f'module={att.module} 用户={user.username}'
        )
        return None

    @staticmethod
    def soft_delete_by_object(user, module: str, object_type: str, object_id, reason='', delete_file: bool = False):
        """批量软删除某业务对象下的所有附件（用于业务对象删除时联动）

        delete_file=True 时尽力删除物理文件：单个文件删除失败只记 warning 不中断，
        仍软删除数据库记录（避免阻断业务对象删除主流程）。
        """
        qs = apply_tenant_filter(
            EvidenceAttachment.objects.filter(
                module=module, object_type=object_type,
                object_id=str(object_id), is_deleted=False,
            ),
            user,
        )
        now = human_datetime()
        uid = getattr(user, 'id', None)
        uname = user.nickname or user.username
        for att in qs:
            if delete_file:
                error = AttachmentService._remove_physical_file(att)
                if error:
                    logger.warning(f'[Evidence] 批量删除时物理文件清理失败，仍软删除记录: ID={att.id} {error}')
            att.is_deleted = True
            att.deleted_at = now
            att.deleted_by_id = uid
            att.deleted_by_name = uname
            att.delete_reason = reason
            att.save(update_fields=[
                'is_deleted', 'deleted_at', 'deleted_by_id',
                'deleted_by_name', 'delete_reason',
            ])

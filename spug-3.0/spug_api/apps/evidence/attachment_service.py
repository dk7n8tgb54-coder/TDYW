# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""通用附件服务 - 跨业务模块共用

设计要点：
- 文件落盘逻辑统一（文件名清洗、重名加序号、SHA256 计算）
- 物理路径规范：/data/spug/spug_api/media/{module}/{tenant_id}/{yyyyMM}/{object_type}_{object_id}/{file_name}
- 业务对象存在性校验由调用方注入（evidence 不知道 upgrade 的 UpgradeRecord 是否存在）
- 软删除保留物理文件和 DB 记录作为证据痕迹
- 配置（允许扩展名、大小上限）由调用方传入，各模块可自定义
- 在线预览通过 kkFileView 实现，使用短时效 preview_token 不暴露长期 x-token

使用示例：
    from apps.evidence.attachment_service import AttachmentService, AttachmentConfig
    att, error = AttachmentService.upload(
        file=request.FILES.get('file'),
        user=request.user,
        module='upgrade',
        object_type='record',
        object_id=record_id,
        config=UpgradeAttachmentConfig,
    )
"""
import os
from django.db import transaction
import re
import base64
import logging
from dataclasses import dataclass
from typing import Optional, Tuple
from urllib.parse import quote

from django.conf import settings
from django.http import FileResponse
from django.utils import timezone

from django.utils import timezone
from libs.tenant_utils import apply_tenant_filter

from .models import EvidenceAttachment
from .attachment_preview_token import (
    generate_attachment_preview_token,
    validate_attachment_preview_token,
)

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


# 默认配置（通用场景）
DefaultAttachmentConfig = AttachmentConfig()

# 可预览的文件扩展名（kkFileView 支持的类型）
PREVIEWABLE_EXTENSIONS = frozenset({
    '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.pdf', '.txt', '.md', '.csv',
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp',
})


class AttachmentService:
    """通用附件服务 - 上传/列表/下载/删除/预览"""

    # ---------------- 私有工具 ----------------

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """文件名清洗：防路径穿越、移除危险字符"""
        safe = os.path.basename(name)
        safe = safe.replace('..', '').replace('/', '').replace('\\', '').replace('\x00', '')
        return safe or 'attachment'

    @staticmethod
    def _sanitize_path_segment(segment: str) -> str:
        """路径段安全清洗：只允许字母/数字/下划线/中划线，其余替换为 _"""
        if segment is None or str(segment).strip() == '':
            return 'default'
        safe = re.sub(r'[^A-Za-z0-9_-]', '_', str(segment))
        return safe or 'default'

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

    @staticmethod
    def _build_relative_path(module: str, tenant_id, object_type: str, object_id) -> str:
        """构建相对 MEDIA_ROOT 的路径：{module}/{tenant_id}/{yyyyMM}/{object_type}_{object_id}"""
        tenant_seg = AttachmentService._sanitize_path_segment(tenant_id)
        date_seg = timezone.now().strftime('%Y%m')
        obj_seg = f'{AttachmentService._sanitize_path_segment(object_type)}_{AttachmentService._sanitize_path_segment(object_id)}'
        return os.path.join(module, tenant_seg, date_seg, obj_seg)

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
    def save_file(file, module: str, tenant_id, object_type: str, object_id,
                  disk_name: Optional[str] = None) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
        """保存文件到磁盘，返回 (disk_name, file_path, relative_path, error)

        物理路径：{MEDIA_ROOT}/{module}/{tenant_id}/{yyyyMM}/{object_type}_{object_id}/{file_name}

        Args:
            disk_name: 可选，指定磁盘文件名（如 UUID 文件名）。
                       为空时使用 file.name 经清洗后的名字（向后兼容）。
        """
        if disk_name:
            safe_name = AttachmentService._sanitize_filename(disk_name)
        else:
            safe_name = AttachmentService._sanitize_filename(file.name)
        rel_dir = AttachmentService._build_relative_path(module, tenant_id, object_type, object_id)
        save_dir = os.path.join(settings.MEDIA_ROOT, rel_dir)
        os.makedirs(save_dir, exist_ok=True)

        disk_name, file_path = AttachmentService._unique_disk_name(save_dir, safe_name)
        try:
            with open(file_path, 'wb+') as destination:
                for chunk in file.chunks():
                    destination.write(chunk)
        except OSError as e:
            logger.error(f'[Evidence] 附件保存失败: {e}')
            return None, None, None, '附件保存失败'

        relative_path = os.path.join(rel_dir, disk_name)
        return disk_name, file_path, relative_path, None

    @staticmethod
    def upload(file, user, module: str, object_type: str, object_id,
               config: AttachmentConfig = DefaultAttachmentConfig,
               owner_tenant_id: Optional[str] = None,
               disk_name: Optional[str] = None) -> Tuple[Optional[EvidenceAttachment], Optional[str]]:
        """上传附件并入库，返回 (attachment, error)

        业务对象存在性校验应由调用方在调用前完成。
        物理路径：{MEDIA_ROOT}/{module}/{tenant_id}/{yyyyMM}/{object_type}_{object_id}/{file_name}

        Args:
            owner_tenant_id: 可选，附件归属租户。
                为空时使用上传人 (user) 的租户（向后兼容，旧调用方行为完全不变）。
                由内部可信服务层传入（如超级管理员给其他租户账号配置签名时，
                附件应归属目标账号租户）。HTTP 请求参数不得直接映射到本参数。
            disk_name: 可选，指定磁盘文件名（如 UUID 文件名），为空时用 file.name。

        附件 uploaded_by_id/name 始终记录真实上传人 (user)，与 owner_tenant_id 解耦。
        """
        ext, error = AttachmentService.validate(file, config)
        if error:
            return None, error

        # 附件归属租户：显式传入时用传入值，否则用上传人租户（向后兼容）
        tenant_for_attachment = owner_tenant_id if owner_tenant_id is not None else getattr(user, 'tenant_id', '')

        disk_name_used, file_path, relative_path, error = AttachmentService.save_file(
            file, module, tenant_for_attachment, object_type, object_id, disk_name=disk_name)
        if error:
            return None, error

        file_hash = AttachmentService._compute_sha256(file_path)
        att = EvidenceAttachment.objects.create(
            tenant_id=tenant_for_attachment,
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
    def list(user, module: str, object_type: str, object_id, skip_tenant_filter: bool = False):
        """获取附件列表（已过滤软删除），返回 list

        skip_tenant_filter=True 时跳过租户过滤（由调用方自行完成可见性校验），
        用于全平台公告等跨租户可见场景。
        """
        base_qs = EvidenceAttachment.objects.filter(
            module=module, object_type=object_type,
            object_id=str(object_id), is_deleted=False,
        )
        qs = base_qs if skip_tenant_filter else apply_tenant_filter(base_qs, user)
        qs = qs.order_by('-uploaded_at', '-id')
        data = []
        for att in qs:
            item = att.to_view()
            item['uploaded_by_name'] = att.uploaded_by_name or '-'
            item['created_at'] = att.uploaded_at  # 前端统一字段名
            item['previewable'] = att.file_ext in PREVIEWABLE_EXTENSIONS
            data.append(item)
        return data

    @staticmethod
    def count(user, module: str, object_type: str, object_id, skip_tenant_filter: bool = False) -> int:
        """统计业务对象下的未删除附件数量"""
        base_qs = EvidenceAttachment.objects.filter(
            module=module, object_type=object_type,
            object_id=str(object_id), is_deleted=False,
        )
        qs = base_qs if skip_tenant_filter else apply_tenant_filter(base_qs, user)
        return qs.count()

    @staticmethod
    def download_response(user, attachment_id, inline=False, skip_tenant_filter: bool = False) -> Tuple[Optional[FileResponse], Optional[str]]:
        """获取下载响应，返回 (response, error)

        inline=True 时返回 Content-Disposition: inline 并按文件扩展名推断
        正确的 Content-Type，用于浏览器直接内联预览图片/PDF。

        skip_tenant_filter=True 时跳过租户过滤（由调用方完成可见性校验），
        用于全平台公告等跨租户可见场景。
        """
        base_qs = EvidenceAttachment.objects.all()
        qs = base_qs if skip_tenant_filter else apply_tenant_filter(base_qs, user)
        att = qs.filter(pk=attachment_id).first()
        if not att:
            return None, '附件不存在或无权限访问'

        full_path = os.path.join(settings.MEDIA_ROOT, att.file_path)
        safe_path = AttachmentService._safe_file_path(full_path)
        if safe_path is None:
            logger.error(f'[Evidence] 下载路径非法或不存在: {att.file_path}')
            return None, '文件不存在'

        encoded_filename = quote(att.file_name)
        if inline:
            import mimetypes
            content_type, _ = mimetypes.guess_type(att.file_name)
            if not content_type:
                content_type = 'application/octet-stream'
            disposition = 'inline'
        else:
            content_type = 'application/octet-stream'
            disposition = 'attachment'

        response = FileResponse(
            open(safe_path, 'rb'),
            content_type=content_type,
        )
        response['Content-Disposition'] = (
            f'{disposition}; filename="{encoded_filename}"; '
            f"filename*=UTF-8''{encoded_filename}"
        )
        response['Content-Length'] = os.path.getsize(safe_path)
        return response, None

    @staticmethod
    def get_preview_url(user, attachment_id, preview_file_api_path: str,
                        skip_tenant_filter: bool = False,
                        token_tenant_id: str = None) -> Tuple[Optional[dict], Optional[str]]:
        """生成 kkFileView 在线预览 URL

        Args:
            user: 已认证用户
            attachment_id: 附件 ID
            preview_file_api_path: kkFileView 回调下载文件的 API 路径（不含 server URL）
                例："/api/upgrade/attachments/123/preview-file/"
            skip_tenant_filter: True 时跳过租户过滤（由调用方完成可见性校验），用于跨租户可见场景
            token_tenant_id: 覆盖 preview_token 绑定的 tenant_id（默认取 user.tenant_id）。
                跨租户场景需传附件真实 tenant_id，使 kkFileView 回调的令牌绑定校验通过。

        Returns:
            (data, error)
            data = {'preview_url': str, 'file_name': str}
        """
        kkfileview_api_url = getattr(settings, 'KKFILEVIEW_API_URL', '')
        if not kkfileview_api_url:
            return None, 'Office文档预览服务未配置，请联系管理员配置KKFILEVIEW_API_URL'

        kkfileview_server_url = getattr(settings, 'KKFILEVIEW_SERVER_URL', '')
        if not kkfileview_server_url:
            return None, 'Office文档预览服务未配置，请联系管理员配置KKFILEVIEW_SERVER_URL'

        base_qs = EvidenceAttachment.objects.all()
        qs = base_qs if skip_tenant_filter else apply_tenant_filter(base_qs, user)
        att = qs.filter(pk=attachment_id, is_deleted=False).first()
        if not att:
            return None, '附件不存在或无权限访问'

        if att.file_ext not in PREVIEWABLE_EXTENSIONS:
            return None, '该文件类型不支持在线预览'

        # 生成短时效 preview_token（跨租户场景用附件真实 tenant_id 绑定，回调校验才能通过）
        token_tenant = token_tenant_id if token_tenant_id is not None else getattr(user, 'tenant_id', '')
        preview_token = generate_attachment_preview_token(
            attachment_id=att.id,
            user_id=getattr(user, 'id', 0),
            tenant_id=token_tenant,
            module=att.module,
            object_type=att.object_type,
            object_id=att.object_id,
        )

        # 构造 kkFileView 回调下载 URL（fullfilename 拼在 URL 上，一起 base64 编码）
        # fullfilename 用物理文件名（file_path basename，含 UUID）而非用户上传名，
        # 确保同名文件重传后 kkFileView 缓存键随之变化，避免命中旧缓存。
        physical_name = os.path.basename(att.file_path) if att.file_path else att.file_name
        file_url = (
            f'{kkfileview_server_url}{preview_file_api_path}'
            f'?preview_token={preview_token}'
            f'&fullfilename={quote(physical_name)}'
        )
        encoded_url = base64.b64encode(file_url.encode('utf-8')).decode('utf-8')
        preview_url = f'{kkfileview_api_url}/onlinePreview?url={encoded_url}'

        return {'preview_url': preview_url, 'file_name': att.file_name}, None

    @staticmethod
    def preview_file_response(preview_token: str, attachment_id) -> Tuple[Optional[FileResponse], Optional[str]]:
        """kkFileView 回调读取文件流，返回 (response, error)

        校验流程：
        1. 验证 preview_token 签名和时效
        2. 校验 token 中的 attachment_id 与 URL 中的 attachment_id 一致
        3. 校验附件未软删除
        4. 校验附件租户、模块、业务对象信息与 token 一致
        5. 校验物理文件路径在 MEDIA_ROOT 内
        6. 返回 FileResponse，Content-Disposition: inline
        """
        token_data = validate_attachment_preview_token(preview_token)
        if not token_data:
            return None, '预览令牌无效或已过期'

        # 校验 attachment_id 一致
        if token_data['attachment_id'] != int(attachment_id):
            logger.warning(
                f'[Evidence] preview_token attachment_id mismatch: '
                f'token={token_data["attachment_id"]}, request={attachment_id}'
            )
            return None, '预览令牌与请求附件不匹配'

        att = EvidenceAttachment.objects.filter(pk=attachment_id).first()
        if not att:
            return None, '附件不存在'

        if att.is_deleted:
            return None, '附件已删除'

        # 校验 token 中的绑定信息与附件一致
        if (att.module != token_data['module']
                or att.object_type != token_data['object_type']
                or str(att.object_id) != str(token_data['object_id'])
                or str(att.tenant_id) != str(token_data['tenant_id'] or '')):
            logger.warning(
                f'[Evidence] preview_token binding mismatch for attachment {attachment_id}: '
                f'token module={token_data["module"]}/object_type={token_data["object_type"]}/'
                f'object_id={token_data["object_id"]}/tenant_id={token_data["tenant_id"]} vs '
                f'db module={att.module}/object_type={att.object_type}/'
                f'object_id={att.object_id}/tenant_id={att.tenant_id}'
            )
            return None, '预览令牌无效'

        # 路径安全校验
        full_path = os.path.join(settings.MEDIA_ROOT, att.file_path)
        safe_path = AttachmentService._safe_file_path(full_path)
        if safe_path is None:
            logger.error(f'[Evidence] 预览路径非法或不存在: {att.file_path}')
            return None, '文件不存在'

        encoded_filename = quote(att.file_name)
        response = FileResponse(
            open(safe_path, 'rb'),
            content_type='application/octet-stream',
        )
        response['Content-Disposition'] = (
            f'inline; filename="{encoded_filename}"; '
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
    def _remove_physical_file_on_commit(att: EvidenceAttachment) -> None:
        """数据库提交后删除物理文件；失败时保留文件并记录，避免数据库回滚后文件丢失。"""
        attachment_id = att.id
        file_path = att.file_path

        def remove_after_commit():
            error = AttachmentService._remove_physical_file(att)
            if error:
                logger.error(
                    f'[Evidence] 数据库已提交但物理文件清理失败，需重试: '
                    f'ID={attachment_id} path={file_path} error={error}'
                )

        transaction.on_commit(remove_after_commit, robust=True)

    @staticmethod
    def soft_delete(user, attachment_id, reason='', delete_file: bool = False) -> Optional[str]:
        """软删除附件，返回 error 或 None

        delete_file=True 时先软删除数据库记录，事务提交后再删除物理文件。
        物理删除失败仅保留孤儿文件并记录错误，不会破坏已提交的数据库一致性。
        """
        qs = apply_tenant_filter(EvidenceAttachment.objects.all(), user)
        att = qs.filter(pk=attachment_id, is_deleted=False).first()
        if not att:
            return '附件不存在或无权限删除'

        att.is_deleted = True
        att.deleted_at = timezone.now()
        att.deleted_by_id = getattr(user, 'id', None)
        att.deleted_by_name = user.nickname or user.username
        att.delete_reason = reason or ''
        att.save(update_fields=[
            'is_deleted', 'deleted_at', 'deleted_by_id',
            'deleted_by_name', 'delete_reason',
        ])
        if delete_file:
            AttachmentService._remove_physical_file_on_commit(att)
        logger.info(
            f'[Evidence] 附件软删除 ID={att.id} 文件={att.file_name} '
            f'module={att.module} 用户={user.username}'
        )
        return None

    @staticmethod
    def soft_delete_by_object(user, module: str, object_type: str, object_id, reason='', delete_file: bool = False):
        """批量软删除某业务对象下的所有附件（用于业务对象删除时联动）

        delete_file=True 时在数据库事务提交后尽力删除物理文件。失败只记错误并保留文件，
        避免数据库回滚后物理文件已经丢失。
        """
        qs = apply_tenant_filter(
            EvidenceAttachment.objects.filter(
                module=module, object_type=object_type,
                object_id=str(object_id), is_deleted=False,
            ),
            user,
        )
        now = timezone.now()
        uid = getattr(user, 'id', None)
        uname = user.nickname or user.username
        for att in qs:
            att.is_deleted = True
            att.deleted_at = now
            att.deleted_by_id = uid
            att.deleted_by_name = uname
            att.delete_reason = reason
            att.save(update_fields=[
                'is_deleted', 'deleted_at', 'deleted_by_id',
                'deleted_by_name', 'delete_reason',
            ])
            if delete_file:
                AttachmentService._remove_physical_file_on_commit(att)

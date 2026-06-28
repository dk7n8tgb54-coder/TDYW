# Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.urls import path
from django.views import View
from django.conf import settings
import os
import uuid
from libs import json_response, auth
from libs.tenant_utils import apply_tenant_filter

from .views import *
from .views import media_url_to_path
from .exporters import RunLogExcelExportView

# 创建详情视图类
class RunLogDetailView(View):
    """运行日志详情视图"""
    @auth('runlog.runlog.update_view')
    def get(self, request):
        """获取事件详情（含动态列表）"""
        from .models import RunLog, RunLogUpdate

        event_id = request.GET.get('id')
        event = apply_tenant_filter(RunLog.objects.filter(pk=event_id), request.user).first()

        if not event:
            return json_response(error='事件不存在', status=404)

        # 获取动态列表
        updates = apply_tenant_filter(
            RunLogUpdate.objects.filter(runlog_id=event_id),
            request.user
        ).order_by('update_date', 'sequence', 'id')

        result = event.to_view()
        result['updates'] = [x.to_view(request.user) for x in updates]

        return json_response(result)


class RunLogUploadAttachmentView(View):
    """运行日志附件上传视图（支持图片和Office文件）"""

    ALLOWED_TYPES = [
        'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp',
        'application/pdf', 'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.ms-excel',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/vnd.ms-powerpoint',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    ]
    MAX_SIZE = 50 * 1024 * 1024  # 50MB
    IMAGE_SUB_DIR = 'images'
    DOC_SUB_DIR = 'documents'

    @auth('runlog.runlog.update_add')
    def post(self, request):
        """上传附件（图片和Office文件）"""
        file = request.FILES.get('file')
        if not file:
            return json_response(error='请选择要上传的文件')

        if not self._validate_file(file):
            return json_response(
                error='只支持上传图片格式（JPG、PNG、GIF、WebP）或Office文件（Word、Excel、PowerPoint、PDF）'
            )

        if file.size > self.MAX_SIZE:
            return json_response(error='文件大小不能超过50MB')

        try:
            filepath, filename, file_url = self._save_file(file)
            if file.content_type.startswith('image/'):
                self._compress_image(filepath)
            return json_response({
                'url': file_url,
                'name': file.name,
                'type': file.content_type,
                'size': file.size
            })
        except Exception as e:
            logger.error(f'[RunLog] 附件上传失败: {str(e)}')
            return json_response(error=f'上传失败：{str(e)}')

    def _validate_file(self, file):
        """验证文件类型"""
        return file.content_type in self.ALLOWED_TYPES

    def _get_subdir(self, content_type):
        """根据文件类型获取存储子目录"""
        if content_type.startswith('image/'):
            return self.IMAGE_SUB_DIR
        return self.DOC_SUB_DIR

    def _generate_filename(self, original_name):
        """生成安全的文件名"""
        ext = os.path.splitext(original_name)[1]
        safe_name = "".join(
            c for c in os.path.splitext(original_name)[0]
            if c.isalnum() or c in (' ', '-', '_', '.')
        ).rstrip()
        if len(safe_name) > 50:
            safe_name = safe_name[:50]
        if not safe_name:
            safe_name = f"file_{uuid.uuid4().hex[:8]}"
        return f"{safe_name}{ext}"

    def _save_file(self, file):
        """保存文件到磁盘"""
        subdir = self._get_subdir(file.content_type)
        upload_dir = os.path.join(settings.MEDIA_ROOT, 'runlog', subdir)
        os.makedirs(upload_dir, exist_ok=True)

        filename = self._generate_filename(file.name)
        filepath = os.path.join(upload_dir, filename)

        with open(filepath, 'wb+') as f:
            for chunk in file.chunks():
                f.write(chunk)

        file_url = f"{settings.MEDIA_URL}runlog/{subdir}/{filename}"
        return filepath, filename, file_url

    def _compress_image(self, filepath):
        """压缩图片（限制尺寸）"""
        try:
            from PIL import Image
            img = Image.open(filepath)
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')
            max_width = 1920
            if img.width > max_width:
                ratio = max_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
            img.save(filepath, quality=85, optimize=True)
        except Exception as e:
            logger.warning(f'[RunLog] 图片压缩失败，已保存原始图片: {filepath}, 错误: {e}')


class RunLogAttachmentPreviewUrlView(View):
    """运行日志附件预览URL视图 - 生成kkFileView预览链接"""
    @auth('runlog.runlog.update_view')
    def get(self, request):
        """获取运行日志附件的kkFileView预览URL"""
        from django.conf import settings
        from urllib.parse import quote, urlencode
        import base64

        # 获取附件路径（相对路径，如 /media/runlog/documents/xxx.pdf）
        attachment_path = request.GET.get('path', '')
        if not attachment_path:
            return json_response(error='缺少附件路径')

        # 校验路径安全：必须位于 MEDIA_ROOT/runlog 目录下
        try:
            full_path = media_url_to_path(attachment_path)
        except ValueError:
            return json_response(error='无效的附件路径')

        if not os.path.exists(full_path):
            return json_response(error='附件文件不存在')

        # 检查kkFileView是否已配置
        kkfileview_api_url = getattr(settings, 'KKFILEVIEW_API_URL', '')
        if not kkfileview_api_url:
            return json_response(error='Office文档预览服务未配置，请联系管理员配置KKFILEVIEW_API_URL')

        kkfileview_server_url = getattr(settings, 'KKFILEVIEW_SERVER_URL', '')
        if not kkfileview_server_url:
            return json_response(error='Office文档预览服务未配置，请联系管理员配置KKFILEVIEW_SERVER_URL')

        # 构建源文件URL（kkFileView通过此URL下载文件）
        # 需要带上 x-token 用于认证
        params = {
            'path': attachment_path,
            'x-token': request.META.get('HTTP_X_TOKEN', ''),
        }
        file_url = f"{kkfileview_server_url}/api/runlog/attachment/download/?{urlencode(params)}"

        # 获取文件名
        file_name = os.path.basename(attachment_path)
        if file_name:
            file_url = f"{file_url}&fullfilename={quote(file_name)}"

        # kkFileView 要求 url 参数使用 base64 编码
        encoded_url = base64.b64encode(file_url.encode('utf-8')).decode('utf-8')
        preview_url = f"{kkfileview_api_url}/onlinePreview?url={encoded_url}"

        return json_response(data={
            'preview_url': preview_url,
            'file_name': file_name,
        })


class RunLogAttachmentDownloadView(View):
    """运行日志附件下载视图 - 供kkFileView下载文件

    该接口会被 kkFileView 作为后端回调访问，回调时会在 URL 中携带用户的
    x-token，认证中间件会据此完成用户认证并设置 request.user，因此可
    直接使用 @auth 装饰器进行权限校验。
    """
    @auth('runlog.runlog.view|runlog.runlog.update_view')
    def get(self, request):
        from django.http import StreamingHttpResponse

        # 获取附件路径
        attachment_path = request.GET.get('path', '')
        if not attachment_path:
            return HttpResponse('Missing path parameter', status=400)

        # 校验路径安全：必须位于 MEDIA_ROOT/runlog 目录下
        try:
            full_path = media_url_to_path(attachment_path)
        except ValueError:
            return HttpResponse('Invalid path', status=400)

        if not os.path.exists(full_path):
            return HttpResponse('File not found', status=404)

        # 获取文件名
        file_name = os.path.basename(attachment_path)

        # 流式响应
        def file_iterator(file_path, chunk_size=1024*1024):
            with open(file_path, 'rb') as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk

        file_size = os.path.getsize(full_path)
        content_type = 'application/octet-stream'
        # 根据扩展名推断 content-type
        ext = os.path.splitext(file_name.lower())[1]
        mime_types = {
            '.pdf': 'application/pdf',
            '.doc': 'application/msword',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.xls': 'application/vnd.ms-excel',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.ppt': 'application/vnd.ms-powerpoint',
            '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        }
        if ext in mime_types:
            content_type = mime_types[ext]

        response = StreamingHttpResponse(
            file_iterator(full_path),
            content_type=content_type
        )
        response['Content-Length'] = str(file_size)
        response['Content-Disposition'] = f"inline; filename*=UTF-8''{quote(file_name)}"
        return response


urlpatterns = [
    path('', RunLogView.as_view()),
    path('detail/', RunLogDetailView.as_view()),
    path('update/', RunLogUpdateView.as_view()),
    path('statistics/', RunLogStatisticsView.as_view()),
    path('event_types/', EventTypeConfigView.as_view()),
    path('upload/', RunLogUploadAttachmentView.as_view()),
    path('export/pdf/', RunLogExportView.as_view()),
    path('export/excel/', RunLogExcelExportView.as_view()),
    path('attachment/preview_url/', RunLogAttachmentPreviewUrlView.as_view()),
    path('attachment/download/', RunLogAttachmentDownloadView.as_view()),
    path('repair/', RunLogRepairView.as_view()),
    path('evidence/package/', RunLogEvidencePackageView.as_view()),
]

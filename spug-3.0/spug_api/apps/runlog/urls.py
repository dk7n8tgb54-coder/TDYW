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
        result['updates'] = [x.to_view() for x in updates]

        return json_response(result)


class RunLogUploadAttachmentView(View):
    """运行日志附件上传视图（支持图片和Office文件）"""
    @auth('runlog.runlog.update_add')
    def post(self, request):
        """上传附件（图片和Office文件）"""
        # 获取上传的文件
        file = request.FILES.get('file')
        if not file:
            return json_response(error='请选择要上传的文件')

        # 验证文件类型
        allowed_types = [
            # 图片格式
            'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp',
            # Office 文档格式
            'application/pdf',
            'application/msword',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/vnd.ms-excel',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'application/vnd.ms-powerpoint',
            'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        ]
        if file.content_type not in allowed_types:
            return json_response(error='只支持上传图片格式（JPG、PNG、GIF、WebP）或Office文件（Word、Excel、PowerPoint、PDF）')

        # 验证文件大小（最大50MB）
        max_size = 50 * 1024 * 1024
        if file.size > max_size:
            return json_response(error='文件大小不能超过50MB')

        try:
            # 根据文件类型选择存储目录
            if file.content_type.startswith('image/'):
                subdir = 'images'
            elif file.content_type == 'application/pdf':
                subdir = 'documents'
            elif file.content_type in ['application/msword', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document']:
                subdir = 'documents'
            elif file.content_type in ['application/vnd.ms-excel', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet']:
                subdir = 'documents'
            elif file.content_type in ['application/vnd.ms-powerpoint', 'application/vnd.openxmlformats-officedocument.presentationml.presentation']:
                subdir = 'documents'
            else:
                subdir = 'documents'

            # 创建上传目录
            upload_dir = os.path.join(settings.MEDIA_ROOT, 'runlog', subdir)
            os.makedirs(upload_dir, exist_ok=True)

            # 生成唯一文件名
            ext = os.path.splitext(file.name)[1]
            filename = f"{uuid.uuid4().hex}{ext}"
            filepath = os.path.join(upload_dir, filename)

            # 保存文件
            with open(filepath, 'wb+') as f:
                for chunk in file.chunks():
                    f.write(chunk)

            # 如果是图片，可选压缩
            if file.content_type.startswith('image/'):
                try:
                    from PIL import Image
                    img = Image.open(filepath)
                    if img.mode in ('RGBA', 'P'):
                        img = img.convert('RGB')
                    # 限制图片尺寸，最大宽度1920px
                    max_width = 1920
                    if img.width > max_width:
                        ratio = max_width / img.width
                        new_height = int(img.height * ratio)
                        img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
                    img.save(filepath, quality=85, optimize=True)
                except Exception as e:
                    logger.warning(f'[RunLog] 图片压缩失败，已保存原始图片: {filepath}, 错误: {e}')

            # 返回文件URL和原始文件名
            file_url = f"{settings.MEDIA_URL}runlog/{subdir}/{filename}"
            return json_response({
                'url': file_url,
                'name': file.name,
                'type': file.content_type,
                'size': file.size
            })

        except Exception as e:
            logger.error(f'[RunLog] 附件上传失败: {str(e)}')
            return json_response(error=f'上传失败：{str(e)}')


urlpatterns = [
    path('', RunLogView.as_view()),
    path('detail/', RunLogDetailView.as_view()),
    path('update/', RunLogUpdateView.as_view()),
    path('statistics/', RunLogStatisticsView.as_view()),
    path('upload/', RunLogUploadAttachmentView.as_view()),
    path('export/pdf/', RunLogExportView.as_view()),
]

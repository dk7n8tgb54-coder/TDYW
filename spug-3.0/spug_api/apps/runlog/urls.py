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


class RunLogUploadImageView(View):
    """运行日志图片上传视图"""
    @auth('runlog.runlog.update_add')
    def post(self, request):
        """上传图片"""
        from PIL import Image

        # 获取上传的文件
        file = request.FILES.get('file')
        if not file:
            return json_response(error='请选择要上传的图片')

        # 验证文件类型
        allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp']
        if file.content_type not in allowed_types:
            return json_response(error='只支持上传图片格式：JPG、PNG、GIF、WebP')

        # 验证文件大小（最大10MB）
        max_size = 10 * 1024 * 1024
        if file.size > max_size:
            return json_response(error='图片大小不能超过10MB')

        try:
            # 创建上传目录
            upload_dir = os.path.join(settings.MEDIA_ROOT, 'runlog', 'images')
            os.makedirs(upload_dir, exist_ok=True)

            # 生成唯一文件名
            ext = os.path.splitext(file.name)[1]
            filename = f"{uuid.uuid4().hex}{ext}"
            filepath = os.path.join(upload_dir, filename)

            # 保存文件
            with open(filepath, 'wb+') as f:
                for chunk in file.chunks():
                    f.write(chunk)

            # 可选：压缩图片
            try:
                img = Image.open(filepath)
                if img.mode in ('RGBA', 'P'):
                    img = img.convert('RGB')

                # 限制图片尺寸，最大宽度1920px
                max_width = 1920
                if img.width > max_width:
                    ratio = max_width / img.width
                    new_height = int(img.height * ratio)
                    img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)

                    # 覆盖保存
                    img.save(filepath, quality=85, optimize=True)
            except Exception as e:
                print(f'[RunLog] 图片压缩失败: {e}')

            # 返回文件URL
            file_url = f"{settings.MEDIA_URL}runlog/images/{filename}"
            return json_response({'url': file_url})

        except Exception as e:
            return json_response(error=f'上传失败：{str(e)}')


urlpatterns = [
    path('', RunLogView.as_view()),
    path('detail/', RunLogDetailView.as_view()),
    path('update/', RunLogUpdateView.as_view()),
    path('statistics/', RunLogStatisticsView.as_view()),
    path('upload/', RunLogUploadImageView.as_view()),
    path('export/pdf/', RunLogExportView.as_view()),
]

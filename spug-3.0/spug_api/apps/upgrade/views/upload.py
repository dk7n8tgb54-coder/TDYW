# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""升级模块专用附件上传"""
from django.views import View
from libs import json_response, auth
from apps.upgrade.services.attachment_service import AttachmentService


class AttachmentUploadView(View):
    """上传附件"""

    @auth('upgrade.upgrade.add')
    def post(self, request):
        file = request.FILES.get('file')
        if not file:
            return json_response(error='请选择要上传的文件')

        url, error = AttachmentService.upload_attachment(file, request.user)
        if error:
            return json_response(error=error)

        return json_response({'url': url})

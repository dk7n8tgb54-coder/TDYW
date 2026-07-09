# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""系统目录接口

GET /api/document/system-folder/?code=industry_rules

返回行业规章系统目录绑定信息，供前端初始化导航到行业规章根目录。
"""
import logging
from django.views.generic import View

from libs import json_response, JsonParser, Argument, auth
from ..services.system_folder_service import (
    get_system_folder, is_valid_system_folder_code, INDUSTRY_RULES_CODE,
)

logger = logging.getLogger(__name__)


class SystemFolderView(View):
    """系统目录查询接口"""

    @auth('document.document.view|document.industry_rule.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('code', type=str, help='请提供 code 参数'),
        ).parse(request.GET)

        if error is not None:
            return json_response(error=error)

        code = form.code
        if not is_valid_system_folder_code(code):
            return json_response(error='未知的系统目录编码')

        sf = get_system_folder(code)
        if not sf:
            return json_response(
                error='系统目录尚未初始化，请联系管理员执行 init_document_system_folders'
            )

        folder = sf.folder
        # 构建根目录路径（行业规章根目录 parent 为 null）
        path = [{'id': folder.id, 'name': folder.name}]

        return json_response({
            'code': sf.code,
            'name': sf.name,
            'is_public': sf.is_public,
            'folder_id': folder.id,
            'folder_name': folder.name,
            'protected': sf.protected,
            'description': sf.description,
            'path': path,
        })

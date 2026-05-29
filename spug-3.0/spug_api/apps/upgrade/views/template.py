# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""升级模板 CRUD 视图"""
from django.views import View
from libs import json_response, auth, Argument, JsonParser
from apps.upgrade.services.template_service import TemplateService


class TemplateListView(View):
    """获取模板列表"""

    @auth('upgrade.upgrade.view')
    def get(self, request):
        data = TemplateService.get_list(request.user)
        return json_response(data)


class TemplateCreateView(View):
    """创建模板"""

    @auth('upgrade.upgrade.add')
    def post(self, request):
        form, error = JsonParser(
            Argument('name', help='请输入模板名称'),
            Argument('system', required=False, default=''),
            Argument('upgrade_type', required=False, default=''),
            Argument('version', required=False, default=''),
            Argument('owner', required=False, default=''),
            Argument('status', required=False, default='处理中'),
            Argument('detail_content', required=False, default=''),
            Argument('is_default', type=bool, required=False, default=False),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        template, error = TemplateService.create_template(
            user=request.user,
            data=form,
        )

        if error:
            return json_response(error=error)

        return json_response({'id': template.id, 'name': template.name})


class TemplateUpdateView(View):
    """更新模板"""

    @auth('upgrade.upgrade.edit')
    def put(self, request, pk):
        form, error = JsonParser(
            Argument('name', required=False),
            Argument('system', required=False),
            Argument('upgrade_type', required=False),
            Argument('version', required=False),
            Argument('owner', required=False),
            Argument('status', required=False),
            Argument('detail_content', required=False),
            Argument('is_default', type=bool, required=False),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        template, error = TemplateService.update_template(
            template_id=pk,
            user=request.user,
            data=form,
        )

        if error:
            return json_response(error=error)

        return json_response()


class TemplateDeleteView(View):
    """删除模板"""

    @auth('upgrade.upgrade.del')
    def delete(self, request, pk):
        error = TemplateService.delete_template(pk, request.user)
        if error:
            return json_response(error=error)
        return json_response()

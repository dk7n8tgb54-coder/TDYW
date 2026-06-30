# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""升级方案 CRUD + 应用视图（合并原 template / checklist 视图）"""
from django.views import View
from libs import json_response, auth, Argument, JsonParser
from apps.upgrade.services.plan_service import PlanService


class PlanListView(View):
    """获取方案列表"""

    @auth('upgrade.upgrade.view')
    def get(self, request):
        data = PlanService.get_list(request.user)
        return json_response(data)


class PlanDetailView(View):
    """获取方案详情（含预设步骤）"""

    @auth('upgrade.upgrade.view')
    def get(self, request, pk):
        data, error = PlanService.get_detail(pk, request.user)
        if error:
            return json_response(error=error)
        return json_response(data)


class PlanCreateView(View):
    """创建方案（基本信息 + 预设步骤）"""

    @auth('upgrade.upgrade.add')
    def post(self, request):
        form, error = JsonParser(
            Argument('name', help='请输入方案名称'),
            Argument('description', required=False, default=''),
            Argument('system', required=False, default=''),
            Argument('upgrade_type', required=False, default=''),
            Argument('version', required=False, default=''),
            Argument('owner', required=False, default=''),
            Argument('status', required=False, default='处理中'),
            Argument('detail_content', required=False, default=''),
            Argument('is_default', type=bool, required=False, default=False),
            Argument('steps', type=list, required=False, default=[]),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        template, error = PlanService.create_plan(user=request.user, data=form)
        if error:
            return json_response(error=error)

        return json_response({'id': template.id, 'name': template.name})


class PlanUpdateView(View):
    """更新方案（基本信息 + 整体替换预设步骤）"""

    @auth('upgrade.upgrade.edit')
    def put(self, request, pk):
        form, error = JsonParser(
            Argument('name', required=False),
            Argument('description', required=False),
            Argument('system', required=False),
            Argument('upgrade_type', required=False),
            Argument('version', required=False),
            Argument('owner', required=False),
            Argument('status', required=False),
            Argument('detail_content', required=False),
            Argument('is_default', type=bool, required=False),
            Argument('steps', type=list, required=False),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        template, error = PlanService.update_plan(
            plan_id=pk, user=request.user, data=form
        )
        if error:
            return json_response(error=error)

        return json_response()


class PlanDeleteView(View):
    """删除方案（级联删除预设步骤）"""

    @auth('upgrade.upgrade.del')
    def delete(self, request, pk):
        error = PlanService.delete_plan(pk, request.user)
        if error:
            return json_response(error=error)
        return json_response()


class PlanApplyView(View):
    """将方案预设步骤应用到升级记录（实例化为 UpgradeRecordStep）"""

    @auth('upgrade.upgrade.add')
    def post(self, request, pk):
        form, error = JsonParser(
            Argument('upgrade_id', type=int, help='请指定升级表单ID'),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        created_count, error = PlanService.apply_to_record(
            plan_id=pk,
            upgrade_id=form.upgrade_id,
            user=request.user,
        )
        if error:
            return json_response(error=error)

        return json_response({'created_count': created_count})


class PlanReorderStepsView(View):
    """重排方案预设步骤顺序"""

    @auth('upgrade.upgrade.edit')
    def put(self, request, pk):
        form, error = JsonParser(
            Argument('step_ids', type=list, help='请提供步骤ID列表'),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        error = PlanService.reorder_steps(
            plan_id=pk, user=request.user, step_ids=form.step_ids,
        )
        if error:
            return json_response(error=error)

        return json_response()

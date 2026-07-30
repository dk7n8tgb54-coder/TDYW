# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""升级方案 CRUD + 应用视图（合并原 template / checklist 视图）"""
from django.views import View
from libs import json_response, auth, Argument, JsonParser
from apps.upgrade.services.plan_service import PlanService
from apps.logs.audit import record_audit_event


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
        from apps.upgrade.models_template import UpgradeTemplate
        plan = UpgradeTemplate.objects.filter(pk=pk).first()
        error = PlanService.delete_plan(pk, request.user)
        if error:
            return json_response(error=error)
        if plan:
            record_audit_event(
                request, 'delete', 'upgrade_plan',
                target_id=str(plan.id),
                target_name=f'方案-{plan.name}',
                detail={'id': plan.id, 'name': plan.name}
            )
        return json_response()


class PlanApplyView(View):
    """将方案预设步骤应用到升级记录（实例化为 UpgradeRecordStep）"""

    @auth('upgrade.upgrade.add')
    def post(self, request, pk):
        form, error = JsonParser(
            Argument('upgrade_id', type=int, help='请指定升级表单ID'),
            Argument('replace', type=bool, default=False),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        result, error = PlanService.apply_to_record(
            plan_id=pk,
            upgrade_id=form.upgrade_id,
            user=request.user,
            replace=form.replace,
        )
        if error:
            return json_response(error=error)

        return json_response(result)


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

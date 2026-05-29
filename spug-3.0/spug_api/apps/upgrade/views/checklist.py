# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""升级步骤清单 CRUD 视图"""
from django.views import View
from libs import json_response, auth, Argument, JsonParser
from apps.upgrade.services.checklist_service import ChecklistService


class ChecklistListView(View):
    """获取清单列表"""

    @auth('upgrade.upgrade.view')
    def get(self, request):
        data = ChecklistService.get_list(request.user)
        return json_response(data)


class ChecklistDetailView(View):
    """获取清单详情（含步骤）"""

    @auth('upgrade.upgrade.view')
    def get(self, request, pk):
        data, error = ChecklistService.get_detail(pk, request.user)
        if error:
            return json_response(error=error)
        return json_response(data)


class ChecklistCreateView(View):
    """创建清单"""

    @auth('upgrade.upgrade.add')
    def post(self, request):
        form, error = JsonParser(
            Argument('name', help='请输入清单名称'),
            Argument('description', required=False, default=''),
            Argument('is_default', type=bool, required=False, default=False),
            Argument('steps', type=list, required=False, default=[]),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        checklist, error = ChecklistService.create_checklist(
            user=request.user,
            data=form,
        )

        if error:
            return json_response(error=error)

        return json_response({'id': checklist.id, 'name': checklist.name})


class ChecklistUpdateView(View):
    """更新清单"""

    @auth('upgrade.upgrade.edit')
    def put(self, request, pk):
        form, error = JsonParser(
            Argument('name', required=False),
            Argument('description', required=False),
            Argument('is_default', type=bool, required=False),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        checklist, error = ChecklistService.update_checklist(
            checklist_id=pk,
            user=request.user,
            data=form,
        )

        if error:
            return json_response(error=error)

        return json_response()


class ChecklistDeleteView(View):
    """删除清单"""

    @auth('upgrade.upgrade.del')
    def delete(self, request, pk):
        error = ChecklistService.delete_checklist(pk, request.user)
        if error:
            return json_response(error=error)
        return json_response()


class ChecklistStepAddView(View):
    """向清单添加步骤"""

    @auth('upgrade.upgrade.add')
    def post(self, request, pk):
        form, error = JsonParser(
            Argument('title', help='请输入步骤标题'),
            Argument('description', required=False, default=''),
            Argument('sequence', type=int, required=False),
            Argument('is_required', type=bool, required=False, default=True),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        step, error = ChecklistService.add_step(
            checklist_id=pk,
            user=request.user,
            data=form,
        )

        if error:
            return json_response(error=error)

        return json_response({'id': step.id, 'title': step.title})


class ChecklistStepUpdateView(View):
    """更新清单步骤"""

    @auth('upgrade.upgrade.edit')
    def put(self, request, pk):
        form, error = JsonParser(
            Argument('title', required=False),
            Argument('description', required=False),
            Argument('sequence', type=int, required=False),
            Argument('is_required', type=bool, required=False),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        step, error = ChecklistService.update_step(
            step_id=pk,
            user=request.user,
            data=form,
        )

        if error:
            return json_response(error=error)

        return json_response()


class ChecklistStepDeleteView(View):
    """删除清单步骤"""

    @auth('upgrade.upgrade.del')
    def delete(self, request, pk):
        error = ChecklistService.delete_step(pk, request.user)
        if error:
            return json_response(error=error)
        return json_response()


class ChecklistApplyView(View):
    """将清单应用到升级表单"""

    @auth('upgrade.upgrade.add')
    def post(self, request, pk):
        form, error = JsonParser(
            Argument('upgrade_id', type=int, help='请指定升级表单ID'),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        created_count, error = ChecklistService.apply_to_record(
            checklist_id=pk,
            upgrade_id=form.upgrade_id,
            user=request.user,
        )

        if error:
            return json_response(error=error)

        return json_response({'created_count': created_count})


class ChecklistReorderStepsView(View):
    """重排清单步骤顺序"""

    @auth('upgrade.upgrade.edit')
    def put(self, request, pk):
        form, error = JsonParser(
            Argument('step_ids', type=list, help='请提供步骤ID列表'),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        error = ChecklistService.reorder_steps(
            checklist_id=pk,
            user=request.user,
            step_ids=form.step_ids,
        )

        if error:
            return json_response(error=error)

        return json_response()

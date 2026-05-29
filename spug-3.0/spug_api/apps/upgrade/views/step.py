# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""升级记录步骤视图 - 步骤执行状态管理"""
import json
from django.views import View
from libs import json_response, auth, Argument, JsonParser
from apps.upgrade.services.step_service import RecordStepService


class RecordStepListView(View):
    """获取升级表单的步骤列表"""

    @auth('upgrade.upgrade.view')
    def get(self, request, record_id):
        steps = RecordStepService.get_record_steps(record_id, request.user)
        stats = RecordStepService.get_record_step_stats(record_id, request.user)
        return json_response({'steps': steps, 'stats': stats})


class RecordStepAddView(View):
    """手动添加步骤到升级表单"""

    @auth('upgrade.upgrade.add')
    def post(self, request, record_id):
        form, error = JsonParser(
            Argument('title', help='请输入步骤标题'),
            Argument('description', required=False, default=''),
            Argument('sequence', type=int, required=False),
            Argument('is_required', type=bool, required=False, default=True),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        step, error = RecordStepService.add_manual_step(
            upgrade_id=record_id,
            user=request.user,
            data=form,
        )

        if error:
            return json_response(error=error)

        return json_response({'id': step.id, 'title': step.title})


class RecordStepUpdateView(View):
    """更新步骤执行状态"""

    @auth('upgrade.upgrade.edit')
    def put(self, request, pk):
        form, error = JsonParser(
            Argument('action', help='请指定操作: complete/skip/reset'),
            Argument('remark', required=False, default=''),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        # 重置步骤需要独立权限
        if form.action == 'reset':
            if not request.user.has_perms(['upgrade.upgrade.step_reset']):
                return json_response(error='无权执行重置步骤操作')

        step, error = RecordStepService.update_step_status(
            step_id=pk,
            user=request.user,
            data=form,
        )

        if error:
            return json_response(error=error)

        return json_response()


class RecordStepDeleteView(View):
    """删除升级记录步骤"""

    @auth('upgrade.upgrade.step_del')
    def delete(self, request, pk):
        error = RecordStepService.delete_step(pk, request.user)
        if error:
            return json_response(error=error)
        return json_response()


class RecordStepBatchUpdateView(View):
    """批量更新步骤状态"""

    @auth('upgrade.upgrade.edit')
    def put(self, request, record_id):
        form, error = JsonParser(
            Argument('steps', type=list, help='请提供步骤更新列表'),
        ).parse(request.body)

        if error:
            return json_response(error=error)

        error = RecordStepService.batch_update_status(
            upgrade_id=record_id,
            user=request.user,
            steps_data=form.steps,
        )

        if error:
            return json_response(error=error)

        return json_response()


class RecordStepClearView(View):
    """清空升级表单的所有步骤"""

    @auth('upgrade.upgrade.step_del')
    def delete(self, request, record_id):
        error = RecordStepService.clear_record_steps(record_id, request.user)
        if error:
            return json_response(error=error)
        return json_response()

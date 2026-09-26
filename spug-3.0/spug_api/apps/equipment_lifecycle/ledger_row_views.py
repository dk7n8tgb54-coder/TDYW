# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——台账行对象树视图（第一阶段）。

权限域（复用既有台账权限码，不新增）：
- 行模板节点：equipment_lifecycle.ledger_template.view|add|edit|del
- 行实例 / 单元格：equipment_lifecycle.ledger.view|edit

约定：
- HTTP 200 + error 为业务失败；写操作记录业务审计；
- 行节点树/实例树均按租户过滤后组装，不泄露跨租户结构；
- 实例与单元格写操作仅限可编辑状态（草稿/已退回）的矩阵台账。
"""
from django.views.generic import View

from libs import json_response, auth
from libs.tenant_utils import apply_tenant_filter

from apps.logs.audit import record_audit_event
from apps.equipment_lifecycle import ledger_row_services
from apps.equipment_lifecycle.ledger_row_services import LedgerValidationError
from apps.equipment_lifecycle.ledger_views import (
    AUDIT_TARGET_LEDGER, AUDIT_TARGET_TEMPLATE, _get_template_for_user,
    _get_ledger_for_user, _ledger_detail, _read_json_body,
)
from apps.equipment_lifecycle.models import (
    OperationLedger,
    OperationLedgerRowInstance,
    OperationLedgerRowTemplateNode,
)


def _get_node_for_user(template, node_pk):
    return template.row_nodes.filter(pk=node_pk).first()


def _get_editable_matrix_ledger(pk, user):
    """取当前用户可编辑（草稿/已退回）的矩阵台账，返回 (ledger, error)。"""
    ledger = _get_ledger_for_user(pk, user)
    if not ledger:
        return None, '台账不存在'
    if ledger.ledger_type == 'inspection':
        return None, '旧巡检台账（历史）已删除，巡检类型不再支持该操作'
    if ledger.status not in OperationLedger.EDITABLE_STATUSES:
        return None, '当前状态不允许编辑台账'
    if not ledger.row_instances.exists():
        return None, '历史台账未配置行实例，不能执行该操作'
    return ledger, None


# ======================================================================
# 行模板节点
# ======================================================================

class LedgerTemplateRowNodesView(View):
    """行节点树查询 + 新增。"""

    @auth('equipment_lifecycle.ledger_template.view')
    def get(self, request, pk):
        template = _get_template_for_user(pk, request.user)
        if not template:
            return json_response(error='台账模板不存在')
        nodes = ledger_row_services.load_template_nodes(template)
        return json_response({'data': ledger_row_services.build_node_tree(nodes)})

    @auth('equipment_lifecycle.ledger_template.add')
    def post(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        template = _get_template_for_user(pk, request.user)
        if not template:
            return json_response(error='台账模板不存在')
        try:
            node = ledger_row_services.create_row_node(request.user, template, body)
        except LedgerValidationError as e:
            return json_response(error=str(e))
        record_audit_event(request, 'create', AUDIT_TARGET_TEMPLATE, template.id,
                           template.name,
                           after_value={'action_kind': 'add_row_node',
                                        'node': node.to_view()})
        return json_response(node.to_view())


class LedgerTemplateRowNodeDetailView(View):
    @auth('equipment_lifecycle.ledger_template.edit')
    def put(self, request, pk, nid):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        template = _get_template_for_user(pk, request.user)
        if not template:
            return json_response(error='台账模板不存在')
        node = _get_node_for_user(template, nid)
        if not node:
            return json_response(error='行节点不存在')
        before = node.to_view()
        try:
            node = ledger_row_services.update_row_node(request.user, template, node, body)
        except LedgerValidationError as e:
            return json_response(error=str(e))
        record_audit_event(request, 'update', AUDIT_TARGET_TEMPLATE, template.id,
                           template.name,
                           before_value={'action_kind': 'edit_row_node', 'node': before},
                           after_value={'action_kind': 'edit_row_node', 'node': node.to_view()})
        return json_response(node.to_view())


class LedgerTemplateRowNodeActiveView(View):
    """行节点停用/启用（del 权限＝受控停用，不物理删除节点）。"""

    @auth('equipment_lifecycle.ledger_template.del')
    def put(self, request, pk, nid):
        body = _read_json_body(request)
        if body is None or not isinstance(body.get('is_active'), bool):
            return json_response(error='请求体格式不正确')
        template = _get_template_for_user(pk, request.user)
        if not template:
            return json_response(error='台账模板不存在')
        node = _get_node_for_user(template, nid)
        if not node:
            return json_response(error='行节点不存在')
        node = ledger_row_services.set_row_node_active(
            request.user, template, node, body['is_active'])
        record_audit_event(
            request, 'update' if node.is_active else 'delete', AUDIT_TARGET_TEMPLATE,
            template.id, template.name,
            after_value={'action_kind': 'activate_row_node' if node.is_active
                         else 'deactivate_row_node', 'node': node.to_view()})
        return json_response(node.to_view())


class LedgerTemplateRowNodeSortView(View):
    @auth('equipment_lifecycle.ledger_template.edit')
    def put(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        template = _get_template_for_user(pk, request.user)
        if not template:
            return json_response(error='台账模板不存在')
        try:
            ledger_row_services.sort_row_nodes(request.user, template, body)
        except LedgerValidationError as e:
            return json_response(error=str(e))
        record_audit_event(request, 'update', AUDIT_TARGET_TEMPLATE, template.id,
                           template.name,
                           after_value={'action_kind': 'sort_row_nodes',
                                        'parent': body.get('parent'),
                                        'ordered_ids': body.get('ordered_ids')})
        nodes = ledger_row_services.load_template_nodes(template)
        return json_response({'data': ledger_row_services.build_node_tree(nodes)})


# ======================================================================
# 行实例与单元格
# ======================================================================

class LedgerRowInstanceView(View):
    """行实例树查询 + 新增实例（可重复分组）。"""

    @auth('equipment_lifecycle.ledger.view')
    def get(self, request, pk):
        ledger = _get_ledger_for_user(pk, request.user)
        if not ledger:
            return json_response(error='台账不存在')
        return json_response({'data': ledger_row_services.load_instance_tree(ledger)})

    @auth('equipment_lifecycle.ledger.edit')
    def post(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        ledger, error = _get_editable_matrix_ledger(pk, request.user)
        if error:
            return json_response(error=error)
        try:
            ledger_row_services.add_row_instance(request.user, ledger, body)
        except LedgerValidationError as e:
            return json_response(error=str(e))
        record_audit_event(request, 'update', AUDIT_TARGET_LEDGER, ledger.id,
                           ledger.ledger_no,
                           after_value={'action_kind': 'add_row_instance',
                                        'template_node': body.get('template_node'),
                                        'name': body.get('name')})
        return json_response(_ledger_detail(ledger, request.user))


class LedgerRowInstanceDetailView(View):
    @auth('equipment_lifecycle.ledger.edit')
    def put(self, request, pk, iid):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        ledger, error = _get_editable_matrix_ledger(pk, request.user)
        if error:
            return json_response(error=error)
        instance = ledger.row_instances.filter(pk=iid).first()
        if not instance:
            return json_response(error='行实例不存在')
        before = instance.to_view()
        try:
            instance = ledger_row_services.rename_row_instance(
                request.user, ledger, instance, body.get('instance_name'))
        except LedgerValidationError as e:
            return json_response(error=str(e))
        record_audit_event(request, 'update', AUDIT_TARGET_LEDGER, ledger.id,
                           ledger.ledger_no,
                           before_value={'action_kind': 'rename_row_instance',
                                         'before': before},
                           after_value={'action_kind': 'rename_row_instance',
                                        'after': instance.to_view()})
        return json_response(_ledger_detail(ledger, request.user))

    @auth('equipment_lifecycle.ledger.edit')
    def delete(self, request, pk, iid):
        ledger, error = _get_editable_matrix_ledger(pk, request.user)
        if error:
            return json_response(error=error)
        instance = ledger.row_instances.filter(pk=iid).first()
        if not instance:
            return json_response(error='行实例不存在')
        before = instance.to_view()
        try:
            ledger_row_services.delete_row_instance(request.user, ledger, instance)
        except LedgerValidationError as e:
            return json_response(error=str(e))
        record_audit_event(request, 'delete', AUDIT_TARGET_LEDGER, ledger.id,
                           ledger.ledger_no,
                           before_value={'action_kind': 'delete_row_instance',
                                         'instance': before})
        return json_response(_ledger_detail(ledger, request.user))


class LedgerCellsView(View):
    """矩阵台账单元格批量编辑（仅更新，无删除语义）+ 可选表头字段。"""

    @auth('equipment_lifecycle.ledger.edit')
    def put(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        ledger, error = _get_editable_matrix_ledger(pk, request.user)
        if error:
            return json_response(error=error)
        try:
            ledger_row_services.edit_matrix_cells(request.user, ledger, body)
        except LedgerValidationError as e:
            return json_response(error=str(e))
        record_audit_event(request, 'update', AUDIT_TARGET_LEDGER, ledger.id,
                           ledger.ledger_no,
                           after_value={'action_kind': 'edit_matrix_cells',
                                        'values_count': len(body.get('values') or [])})
        return json_response(_ledger_detail(ledger, request.user))

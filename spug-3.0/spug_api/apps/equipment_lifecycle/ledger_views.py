# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""设备全生命周期——巡检/周月维护/季维护台账视图（步骤 3.2）。

权限域（前后端一致，后端独立校验）：
- equipment_lifecycle.ledger_template.view|add|edit|del
- equipment_lifecycle.ledger.view|add|edit|submit|review|del|export

约定：
- 所有系统关联通过系统 ID，后端重新查询系统/模板，不信任前端
  传来的名称与模板内容；
- 台账创建/提交/复核/退回/作废均考虑重复请求（状态机 + client_token）；
- HTTP 200 + error 为业务失败；写操作记录业务审计并使用状态动作接口；
- 附件走 evidence 体系，访问前校验所属台账/明细与租户归属。
"""
import csv
import io
import json

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.views.generic import View

from libs import json_response, auth
from libs.pagination import paginate
from libs.tenant_utils import apply_tenant_filter

from apps.logs.audit import record_audit_event
from apps.evidence.attachment_service import (
    AttachmentService, DefaultAttachmentConfig,
    ATTACHMENT_ACCESS_DENIED_ERROR, ATTACHMENT_DELETE_DENIED_ERROR,
)
from apps.evidence.models import EvidenceAttachment

from apps.equipment_lifecycle import ledger_services, work_order_services
from apps.equipment_lifecycle.ledger_services import ITEM_RESULT_TEXT_MAP, LedgerValidationError
from apps.equipment_lifecycle.models import (
    ITEM_RESULT_ABNORMAL,
    LEDGER_INPUT_TYPE_VALUES,
    LEDGER_STATUS_VOID,
    LEDGER_TYPE_TEXT,
    LEDGER_TYPE_VALUES,
    LEDGER_TYPE_WEEK_MONTH,
    EXEC_SCOPE_VALUES,
    LifecycleSystem,
    OperationLedger,
    OperationLedgerItem,
    OperationLedgerTemplate,
    OperationLedgerTemplateItem,
)
from apps.equipment_lifecycle.views import (
    EL_ATTACHMENT_MODULE,
    _get_system_for_user,
    _read_json_body,
)

AUDIT_TARGET_TEMPLATE = 'el_ledger_template'
AUDIT_TARGET_LEDGER = 'el_operation_ledger'

# 附件归属标识：台账表头 / 台账明细
LEDGER_ATTACHMENT_OBJECT_TYPE = 'el_operation_ledger'
LEDGER_ITEM_ATTACHMENT_OBJECT_TYPE = 'el_operation_ledger_item'


def _parse_choices_field(raw):
    """校验候选项字段：空或 JSON 字符串数组；返回 (存储串, 列表)。"""
    if raw in (None, ''):
        return '', []
    if isinstance(raw, list):
        values = raw
    else:
        try:
            values = json.loads(raw)
        except (ValueError, TypeError):
            raise LedgerValidationError('候选项格式不正确，必须为字符串数组')
    if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
        raise LedgerValidationError('候选项格式不正确，必须为字符串数组')
    return json.dumps(values, ensure_ascii=False), values


# ======================================================================
# 台账模板
# ======================================================================

def _get_template_for_user(pk, user):
    return apply_tenant_filter(OperationLedgerTemplate.objects.all(), user).filter(pk=pk).first()


def _validate_template_header(request, body, item=None):
    """模板表头字段校验，返回字段 dict 或错误信息（编号由后端自动生成）。"""
    name = str(body.get('name') or '').strip()
    if not name:
        return None, '模板名称不能为空'
    ledger_type = body.get('ledger_type')
    if ledger_type not in LEDGER_TYPE_VALUES:
        return None, '台账类型不合法'
    maintenance_cycle = body.get('maintenance_cycle') or ''
    try:
        ledger_services.validate_ledger_type_cycle(ledger_type, maintenance_cycle)
    except LedgerValidationError as e:
        return None, str(e)
    return {
        'name': name,
        'ledger_type': ledger_type,
        'maintenance_cycle': maintenance_cycle,
        'description': str(body.get('description') or '').strip(),
    }, None


def _validate_template_item_payload(request, template, body, item=None):
    """模板项目字段校验，返回字段 dict 或错误信息。"""
    name = str(body.get('name') or '').strip()
    if not name:
        return None, '项目名称不能为空'
    input_type = body.get('input_type')
    if input_type not in LEDGER_INPUT_TYPE_VALUES:
        return None, '录入类型不合法：%s' % input_type
    execution_scope = body.get('execution_scope') or 'all'
    if execution_scope not in EXEC_SCOPE_VALUES:
        return None, '执行范围不合法：%s' % execution_scope
    if template.ledger_type != LEDGER_TYPE_WEEK_MONTH:
        execution_scope = 'all'
    choices_raw, choices = '', []
    if input_type in ('choice', 'multi_choice'):
        try:
            choices_raw, choices = _parse_choices_field(body.get('choices'))
        except LedgerValidationError as e:
            return None, str(e)
        if not choices:
            return None, '单选/多选项目必须配置候选项'
    return {
        'name': name,
        'input_type': input_type,
        'unit': str(body.get('unit') or '').strip(),
        'choices': choices_raw,
        'default_value': str(body.get('default_value') or '').strip(),
        'is_required': bool(body.get('is_required', True)),
        'execution_scope': execution_scope,
        'abnormal_rule': str(body.get('abnormal_rule') or '').strip(),
        'operation_guide': str(body.get('operation_guide') or '').strip(),
        'display_order': body.get('display_order') if isinstance(body.get('display_order'), int) else 0,
    }, None


class LedgerTemplateView(View):
    @auth('equipment_lifecycle.ledger_template.view')
    def get(self, request):
        query = apply_tenant_filter(
            OperationLedgerTemplate.objects.all(), request.user)
        ledger_type = request.GET.get('ledger_type')
        if ledger_type:
            query = query.filter(ledger_type=ledger_type)
        is_active = request.GET.get('is_active')
        if is_active in ('true', 'false'):
            query = query.filter(is_active=(is_active == 'true'))
        keyword = request.GET.get('keyword')
        if keyword:
            query = query.filter(Q(name__icontains=keyword))
        data = [item.to_view(with_counts=True) for item in query]
        return json_response({'data': data})

    @auth('equipment_lifecycle.ledger_template.add')
    def post(self, request):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        header, error = _validate_template_header(request, body)
        if error:
            return json_response(error=error)
        items_payload = body.get('items') or []
        if not isinstance(items_payload, list):
            return json_response(error='items 必须为数组')
        try:
            with transaction.atomic():
                template = OperationLedgerTemplate.objects.create(
                    tenant_id=request.user.tenant_id,
                    created_by=request.user,
                    **header,
                )
                for row in items_payload:
                    fields, error = _validate_template_item_payload(request, template, row)
                    if error:
                        raise LedgerValidationError(error)
                    OperationLedgerTemplateItem.objects.create(
                        template=template, tenant_id=request.user.tenant_id,
                        created_by=request.user, **fields)
        except LedgerValidationError as e:
            return json_response(error=str(e))
        except IntegrityError:
            return json_response(error='模板保存失败，请重试')
        record_audit_event(request, 'create', AUDIT_TARGET_TEMPLATE, template.id, template.name,
                           after_value={'ledger_type': template.ledger_type,
                                        'items_count': len(items_payload)})
        return json_response(template.to_view(with_counts=True))


class LedgerTemplateAvailableView(View):
    """按台账类型/周期加载启用模板（模板不绑定系统，供录入端候选）。"""

    @auth('equipment_lifecycle.ledger.view')
    def get(self, request):
        ledger_type = request.GET.get('ledger_type')
        if ledger_type not in LEDGER_TYPE_VALUES:
            return json_response(error='台账类型不合法')
        maintenance_cycle = request.GET.get('maintenance_cycle') or ''
        try:
            ledger_services.validate_ledger_type_cycle(ledger_type, maintenance_cycle)
        except LedgerValidationError as e:
            return json_response(error=str(e))

        def _view(template):
            view = template.to_view()
            count_qs = template.items.filter(is_active=True)
            if ledger_type == LEDGER_TYPE_WEEK_MONTH:
                count_qs = count_qs.filter(execution_scope__in=[
                    'all', 'week_only' if maintenance_cycle == 'week' else 'month_only'])
            view['items_count'] = count_qs.count()
            return view

        templates = apply_tenant_filter(
            OperationLedgerTemplate.objects.all(), request.user).filter(
            ledger_type=ledger_type, is_active=True)
        return json_response({'data': [_view(t) for t in templates]})


class LedgerTemplateDetailView(View):
    @auth('equipment_lifecycle.ledger_template.view')
    def get(self, request, pk):
        template = _get_template_for_user(pk, request.user)
        if not template:
            return json_response(error='台账模板不存在')
        view = template.to_view(with_counts=True)
        view['items'] = [it.to_view() for it in template.items.all()]
        return json_response(view)

    @auth('equipment_lifecycle.ledger_template.edit')
    def put(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        template = _get_template_for_user(pk, request.user)
        if not template:
            return json_response(error='台账模板不存在')
        header, error = _validate_template_header(request, body, item=template)
        if error:
            return json_response(error=error)
        before = {'name': template.name, 'description': template.description}
        with transaction.atomic():
            for field in ('name', 'description'):
                setattr(template, field, header[field])
            template.updated_by = request.user
            template.save()
        record_audit_event(request, 'update', AUDIT_TARGET_TEMPLATE, template.id, template.name,
                           before_value=before,
                           after_value={'name': template.name, 'description': template.description})
        return json_response(template.to_view(with_counts=True))


class LedgerTemplateActiveView(View):
    """模板停用/启用（del 权限＝受控停用，不物理删除模板）。"""

    @auth('equipment_lifecycle.ledger_template.del')
    def put(self, request, pk):
        body = _read_json_body(request)
        if body is None or not isinstance(body.get('is_active'), bool):
            return json_response(error='请求体格式不正确')
        template = _get_template_for_user(pk, request.user)
        if not template:
            return json_response(error='台账模板不存在')
        template.is_active = body['is_active']
        template.updated_by = request.user
        template.save(update_fields=['is_active', 'updated_at', 'updated_by'])
        record_audit_event(
            request, 'update' if template.is_active else 'delete', AUDIT_TARGET_TEMPLATE,
            template.id, template.name,
            after_value={'is_active': template.is_active,
                         'action_kind': 'activate_template' if template.is_active else 'deactivate_template'})
        return json_response(template.to_view())


class LedgerTemplateItemView(View):
    @auth('equipment_lifecycle.ledger_template.view')
    def get(self, request, pk):
        template = _get_template_for_user(pk, request.user)
        if not template:
            return json_response(error='台账模板不存在')
        rows = template.items.all()
        execution_scope = request.GET.get('execution_scope')
        if execution_scope:
            rows = rows.filter(execution_scope=execution_scope)
        is_active = request.GET.get('is_active')
        if is_active in ('true', 'false'):
            rows = rows.filter(is_active=(is_active == 'true'))
        return json_response({'data': [it.to_view() for it in rows]})

    @auth('equipment_lifecycle.ledger_template.edit')
    def post(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        template = _get_template_for_user(pk, request.user)
        if not template:
            return json_response(error='台账模板不存在')
        fields, error = _validate_template_item_payload(request, template, body)
        if error:
            return json_response(error=error)
        item = OperationLedgerTemplateItem.objects.create(
            template=template, tenant_id=request.user.tenant_id, created_by=request.user, **fields)
        record_audit_event(request, 'create', AUDIT_TARGET_TEMPLATE, template.id, template.name,
                           after_value={'action_kind': 'add_template_item', 'item_name': item.name})
        return json_response(item.to_view())


class LedgerTemplateItemDetailView(View):
    @auth('equipment_lifecycle.ledger_template.edit')
    def put(self, request, pk, iid):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        template = _get_template_for_user(pk, request.user)
        if not template:
            return json_response(error='台账模板不存在')
        item = template.items.filter(pk=iid).first()
        if not item:
            return json_response(error='模板项目不存在')
        fields, error = _validate_template_item_payload(request, template, body, item=item)
        if error:
            return json_response(error=error)
        before = item.to_view()
        for field, value in fields.items():
            setattr(item, field, value)
        item.updated_by = request.user
        item.save()
        record_audit_event(request, 'update', AUDIT_TARGET_TEMPLATE, template.id, template.name,
                           before_value={'action_kind': 'edit_template_item', 'item': before},
                           after_value={'action_kind': 'edit_template_item', 'item': item.to_view()})
        return json_response(item.to_view())

    @auth('equipment_lifecycle.ledger_template.del')
    def delete(self, request, pk, iid):
        template = _get_template_for_user(pk, request.user)
        if not template:
            return json_response(error='台账模板不存在')
        item = template.items.filter(pk=iid).first()
        if not item:
            return json_response(error='模板项目不存在')
        before = {'item_name': item.name}
        # 历史台账明细保存全量快照（template_item SET_NULL），物理删除模板项目不影响历史
        item.delete()
        record_audit_event(request, 'delete', AUDIT_TARGET_TEMPLATE, template.id, template.name,
                           before_value={'action_kind': 'delete_template_item', **before})
        return json_response({})


# ======================================================================
# 台账
# ======================================================================

def _get_ledger_for_user(pk, user):
    return apply_tenant_filter(OperationLedger.objects.all(), user).filter(pk=pk).first()


def _ledger_detail(ledger, user=None):
    view = ledger.to_view(with_counts=True)
    items = [it.to_view() for it in ledger.items.all()]
    if user is not None:
        # 异常明细处置状态（步骤 3.3）：由来源关系动态计算，事实依据不落库
        work_order_services.append_item_disposition(ledger.tenant_id, items)
    view['items'] = items
    view['corrections'] = [c.to_view() for c in ledger.corrections.all()]
    return view


class LedgerView(View):
    @auth('equipment_lifecycle.ledger.view')
    def get(self, request):
        query = apply_tenant_filter(OperationLedger.objects.all(), request.user)
        ledger_type = request.GET.get('ledger_type')
        if ledger_type:
            query = query.filter(ledger_type=ledger_type)
        maintenance_cycle = request.GET.get('maintenance_cycle')
        if maintenance_cycle:
            query = query.filter(maintenance_cycle=maintenance_cycle)
        status = request.GET.get('status')
        if status:
            query = query.filter(status=status)
        system_id = request.GET.get('system')
        if system_id and str(system_id).isdigit():
            query = query.filter(items__system_id=system_id).distinct()
        keyword = request.GET.get('keyword')
        if keyword:
            query = query.filter(ledger_no__icontains=keyword)
        executed_from = request.GET.get('executed_from')
        if executed_from:
            query = query.filter(executed_date__gte=executed_from)
        executed_to = request.GET.get('executed_to')
        if executed_to:
            query = query.filter(executed_date__lte=executed_to)
        query = query.annotate(
            items_count=Count('items', distinct=True),
            abnormal_count=Count('items', filter=Q(items__result=ITEM_RESULT_ABNORMAL), distinct=True),
        )
        page, page_size = paginate(request)
        total = query.count()
        records = query[(page - 1) * page_size: page * page_size] if total else []
        return json_response({
            'data': [r.to_view(with_counts=True) for r in records],
            'total': total, 'page': page, 'page_size': page_size,
        })

    @auth('equipment_lifecycle.ledger.add')
    def post(self, request):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        ledger, error = ledger_services.create_ledger(request.user, body)
        if error:
            return json_response(error=error)
        record_audit_event(request, 'create', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
                           after_value={'ledger_type': ledger.ledger_type,
                                        'created_from': ledger.created_from,
                                        'items_count': ledger.items.count()})
        return json_response(_ledger_detail(ledger, request.user))


class LedgerPreviewView(View):
    """按 系统+模板 生成台账明细预览骨架。"""

    @auth('equipment_lifecycle.ledger.view')
    def post(self, request):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        preview, error = ledger_services.preview_entries(request.user, body)
        if error:
            return json_response(error=error)
        return json_response({'data': preview})


class LedgerDetailView(View):
    @auth('equipment_lifecycle.ledger.view')
    def get(self, request, pk):
        ledger = _get_ledger_for_user(pk, request.user)
        if not ledger:
            return json_response(error='台账不存在')
        return json_response(_ledger_detail(ledger, request.user))

    @auth('equipment_lifecycle.ledger.edit')
    def put(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        ledger, changed, error = ledger_services.update_ledger(request.user, pk, body)
        if error:
            return json_response(error=error)
        record_audit_event(request, 'update', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
                           before_value={'version': ledger.version - 1},
                           after_value={'version': ledger.version, 'changes': changed})
        return json_response(_ledger_detail(ledger, request.user))


class LedgerSubmitView(View):
    @auth('equipment_lifecycle.ledger.submit')
    def post(self, request, pk):
        ledger, error = ledger_services.submit_ledger(request.user, pk)
        if error:
            return json_response(error=error)
        record_audit_event(request, 'update', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
                           after_value={'action_kind': 'submit', 'status': ledger.status})
        return json_response(_ledger_detail(ledger, request.user))


class LedgerReturnView(View):
    @auth('equipment_lifecycle.ledger.review')
    def post(self, request, pk):
        body = _read_json_body(request) or {}
        ledger, error = ledger_services.return_ledger(request.user, pk, body.get('reason'))
        if error:
            return json_response(error=error)
        record_audit_event(request, 'update', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
                           after_value={'action_kind': 'return', 'status': ledger.status,
                                        'reason': ledger.return_reason})
        return json_response(_ledger_detail(ledger, request.user))


class LedgerReviewView(View):
    @auth('equipment_lifecycle.ledger.review')
    def post(self, request, pk):
        ledger, error = ledger_services.review_ledger(request.user, pk)
        if error:
            return json_response(error=error)
        record_audit_event(request, 'approve', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
                           after_value={'action_kind': 'review', 'status': ledger.status,
                                        'reviewer_name': ledger.reviewer_name})
        return json_response(_ledger_detail(ledger, request.user))


class LedgerVoidView(View):
    @auth('equipment_lifecycle.ledger.del')
    def post(self, request, pk):
        body = _read_json_body(request) or {}
        ledger, error = ledger_services.void_ledger(request.user, pk, body.get('reason'))
        if error:
            return json_response(error=error)
        # 受控作废（不物理删除），审计用 delete 大类 + action_kind 标注
        record_audit_event(request, 'delete', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
                           after_value={'action_kind': 'void_ledger', 'status': ledger.status,
                                        'reason': ledger.void_reason})
        return json_response(_ledger_detail(ledger, request.user))


class LedgerCorrectView(View):
    @auth('equipment_lifecycle.ledger.edit')
    def post(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        correction, changes, error = ledger_services.correct_ledger(request.user, pk, body)
        if error:
            return json_response(error=error)
        record_audit_event(request, 'update', AUDIT_TARGET_LEDGER, correction.ledger_id,
                           correction.ledger.ledger_no,
                           after_value={'action_kind': 'correct', 'reason': correction.reason,
                                        'changes': changes})
        return json_response(correction.to_view())


class LedgerConfirmNormalView(View):
    @auth('equipment_lifecycle.ledger.edit')
    def post(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        ledger, error = ledger_services.confirm_normal(request.user, pk, body.get('item_ids'))
        if error:
            return json_response(error=error)
        record_audit_event(request, 'update', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
                           after_value={'action_kind': 'confirm_normal',
                                        'item_ids': body.get('item_ids')})
        return json_response(_ledger_detail(ledger, request.user))


class LedgerAbnormalItemsView(View):
    """异常明细查询（排除已作废台账；支持类型/系统/日期范围过滤）。"""

    @auth('equipment_lifecycle.ledger.view')
    def get(self, request):
        query = OperationLedgerItem.objects.filter(
            tenant_id=request.user.tenant_id, result=ITEM_RESULT_ABNORMAL,
            ledger__isnull=False).exclude(ledger__status=LEDGER_STATUS_VOID)
        ledger_type = request.GET.get('ledger_type')
        if ledger_type:
            query = query.filter(ledger__ledger_type=ledger_type)
        system_id = request.GET.get('system')
        if system_id and str(system_id).isdigit():
            query = query.filter(system_id=system_id)
        date_from = request.GET.get('date_from')
        if date_from:
            query = query.filter(ledger__executed_date__gte=date_from)
        date_to = request.GET.get('date_to')
        if date_to:
            query = query.filter(ledger__executed_date__lte=date_to)
        query = query.select_related('ledger', 'system').order_by('-ledger__executed_date', '-id')
        page, page_size = paginate(request)
        total = query.count()
        records = query[(page - 1) * page_size: page * page_size] if total else []
        data = []
        for item in records:
            view = item.to_view()
            view['ledger_no'] = item.ledger.ledger_no
            view['ledger_type'] = item.ledger.ledger_type
            view['ledger_executed_date'] = item.ledger.executed_date
            view['ledger_status'] = item.ledger.status
            data.append(view)
        # 异常明细处置状态（步骤 3.3）：由来源关系动态计算
        work_order_services.append_item_disposition(request.user.tenant_id, data)
        return json_response({'data': data, 'total': total, 'page': page, 'page_size': page_size})


class SystemLedgerItemsView(View):
    """系统详情台账明细查询：仅当前系统（租户内）的台账明细，排除已作废台账。

    一张台账可能包含其他系统，本端点只返回当前系统对应的明细，
    不泄露无权限系统的数据。
    """

    @auth('equipment_lifecycle.ledger.view')
    def get(self, request, pk):
        system = _get_system_for_user(pk, request.user)
        if not system:
            return json_response(error='系统不存在')
        query = OperationLedgerItem.objects.filter(
            tenant_id=request.user.tenant_id, system=system,
            ledger__isnull=False).exclude(ledger__status=LEDGER_STATUS_VOID)
        ledger_type = request.GET.get('ledger_type')
        if ledger_type:
            query = query.filter(ledger__ledger_type=ledger_type)
        result = request.GET.get('result')
        if result:
            query = query.filter(result=result)
        date_from = request.GET.get('date_from')
        if date_from:
            query = query.filter(ledger__executed_date__gte=date_from)
        date_to = request.GET.get('date_to')
        if date_to:
            query = query.filter(ledger__executed_date__lte=date_to)
        query = query.select_related('ledger').order_by('-ledger__executed_date', '-id')
        page, page_size = paginate(request)
        total = query.count()
        records = query[(page - 1) * page_size: page * page_size] if total else []
        data = []
        for item in records:
            view = item.to_view()
            view['ledger_no'] = item.ledger.ledger_no
            view['ledger_type'] = item.ledger.ledger_type
            view['ledger_status'] = item.ledger.status
            view['ledger_executed_date'] = item.ledger.executed_date
            data.append(view)
        return json_response({'data': data, 'total': total, 'page': page, 'page_size': page_size})


class LedgerExportView(View):
    """台账明细级 CSV 导出：重新执行查询与租户过滤，不信任前端明细 ID。"""

    @auth('equipment_lifecycle.ledger.export')
    def get(self, request):
        query = OperationLedgerItem.objects.filter(
            tenant_id=request.user.tenant_id, ledger__isnull=False)
        ledger_type = request.GET.get('ledger_type')
        if ledger_type:
            query = query.filter(ledger__ledger_type=ledger_type)
        maintenance_cycle = request.GET.get('maintenance_cycle')
        if maintenance_cycle:
            query = query.filter(ledger__maintenance_cycle=maintenance_cycle)
        status = request.GET.get('status')
        if status:
            query = query.filter(ledger__status=status)
        system_id = request.GET.get('system')
        if system_id and str(system_id).isdigit():
            query = query.filter(system_id=system_id)
        date_from = request.GET.get('executed_from')
        if date_from:
            query = query.filter(ledger__executed_date__gte=date_from)
        date_to = request.GET.get('executed_to')
        if date_to:
            query = query.filter(ledger__executed_date__lte=date_to)
        keyword = request.GET.get('keyword')
        if keyword:
            query = query.filter(ledger__ledger_no__icontains=keyword)
        rows = query.select_related('ledger', 'system').order_by('-ledger__executed_date', '-id')
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([
            '台账编号', '台账类型', '维护周期', '实际执行日期', '状态', '系统编号', '系统名称',
            '项目名称', '录入类型', '填写值', '单位',
            '结果', '异常说明', '不适用原因', '现场处理内容', '明细执行人',
            '明细执行时间', '录入渠道', '录入时间'])
        count = 0
        for item in rows:
            ledger = item.ledger
            if item.input_type == 'number':
                value = '' if item.value_number is None else item.value_number
            elif item.input_type == 'boolean':
                value = '' if item.value_bool is None else ('是' if item.value_bool else '否')
            else:
                value = item.get_value_list() if item.input_type == 'multi_choice' and item.value_text \
                    else item.value_text
                if isinstance(value, list):
                    value = '、'.join(map(str, value))
            writer.writerow([
                ledger.ledger_no, LEDGER_TYPE_TEXT.get(ledger.ledger_type, ledger.ledger_type),
                ledger.maintenance_cycle, ledger.executed_date,
                ledger.status, item.system_code_snapshot, item.system_name_snapshot,
                item.item_name_snapshot,
                item.input_type, value, item.unit_snapshot,
                ITEM_RESULT_TEXT_MAP.get(item.result, item.result),
                item.abnormal_desc, item.na_reason, item.onsite_action, item.executor_name,
                item.executed_at or '', ledger.entry_channel,
                ledger.created_at])
            count += 1
        response = HttpResponse(buffer.getvalue().encode('utf-8-sig'), content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=operation_ledgers.csv'
        record_audit_event(request, 'export', AUDIT_TARGET_LEDGER, None, '运维台账明细',
                           after_value={'rows': count, 'ledger_type': ledger_type or 'all'})
        return response


# ======================================================================
# 台账附件（表头 / 明细）
# ======================================================================

def _get_ledger_item_for_user(ledger, item_pk):
    return ledger.items.filter(pk=item_pk).first()


def _attachment_for_user(user, attachment_id, object_type, object_id):
    """附件归属校验：存在、未删除、module/object_type/object_id 与租户全部匹配。"""
    return apply_tenant_filter(
        EvidenceAttachment.objects.filter(is_deleted=False), user
    ).filter(pk=attachment_id, module=EL_ATTACHMENT_MODULE, object_type=object_type,
             object_id=str(object_id)).first()


class LedgerAttachmentView(View):
    @auth('equipment_lifecycle.ledger.view')
    def get(self, request, pk):
        ledger = _get_ledger_for_user(pk, request.user)
        if not ledger:
            return json_response(error='台账不存在')
        return json_response({'data': AttachmentService.list(
            request.user, EL_ATTACHMENT_MODULE, LEDGER_ATTACHMENT_OBJECT_TYPE, ledger.id)})

    @auth('equipment_lifecycle.ledger.edit')
    def post(self, request, pk):
        ledger = _get_ledger_for_user(pk, request.user)
        if not ledger:
            return json_response(error='台账不存在')
        if ledger.status not in OperationLedger.EDITABLE_STATUSES:
            return json_response(error='当前状态不允许上传台账附件')
        file = request.FILES.get('file')
        if not file:
            return json_response(error='缺少上传文件')
        att, error = AttachmentService.upload(
            file, request.user, EL_ATTACHMENT_MODULE, LEDGER_ATTACHMENT_OBJECT_TYPE,
            ledger.id, config=DefaultAttachmentConfig, owner_tenant_id=ledger.tenant_id)
        if error:
            return json_response(error=error)
        record_audit_event(request, 'create', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
                           after_value={'action_kind': 'upload_ledger_attachment',
                                        'file_name': att.file_name})
        return json_response(att.to_view())


class LedgerAttachmentDetailView(View):
    @auth('equipment_lifecycle.ledger.edit')
    def delete(self, request, pk, aid):
        ledger = _get_ledger_for_user(pk, request.user)
        if not ledger:
            return json_response(error='台账不存在')
        if ledger.status not in OperationLedger.EDITABLE_STATUSES:
            return json_response(error='当前状态不允许删除台账附件')
        att = _attachment_for_user(request.user, aid, LEDGER_ATTACHMENT_OBJECT_TYPE, ledger.id)
        if not att:
            return json_response(error=ATTACHMENT_DELETE_DENIED_ERROR)
        error = AttachmentService.soft_delete(
            request.user, aid, EL_ATTACHMENT_MODULE, LEDGER_ATTACHMENT_OBJECT_TYPE,
            reason='运维台账附件删除')
        if error:
            return json_response(error=error)
        record_audit_event(request, 'delete', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
                           before_value={'action_kind': 'delete_ledger_attachment',
                                         'file_name': att.file_name})
        return json_response({})


class LedgerAttachmentDownloadView(View):
    @auth('equipment_lifecycle.ledger.view')
    def get(self, request, pk, aid):
        ledger = _get_ledger_for_user(pk, request.user)
        if not ledger:
            return json_response(error='台账不存在')
        att = _attachment_for_user(request.user, aid, LEDGER_ATTACHMENT_OBJECT_TYPE, ledger.id)
        if not att:
            return json_response(error=ATTACHMENT_ACCESS_DENIED_ERROR)
        response, error = AttachmentService.download_response(
            request.user, aid, EL_ATTACHMENT_MODULE, LEDGER_ATTACHMENT_OBJECT_TYPE)
        if error:
            return json_response(error=error)
        return response


class LedgerItemAttachmentView(View):
    def _check(self, request, pk, item_pk):
        ledger = _get_ledger_for_user(pk, request.user)
        if not ledger:
            return None, None, '台账不存在'
        item = _get_ledger_item_for_user(ledger, item_pk)
        if not item:
            return None, None, '台账明细不存在'
        return ledger, item, None

    @auth('equipment_lifecycle.ledger.view')
    def get(self, request, pk, item_pk):
        ledger, item, error = self._check(request, pk, item_pk)
        if error:
            return json_response(error=error)
        return json_response({'data': AttachmentService.list(
            request.user, EL_ATTACHMENT_MODULE, LEDGER_ITEM_ATTACHMENT_OBJECT_TYPE, item.id)})

    @auth('equipment_lifecycle.ledger.edit')
    def post(self, request, pk, item_pk):
        ledger, item, error = self._check(request, pk, item_pk)
        if error:
            return json_response(error=error)
        if ledger.status not in OperationLedger.EDITABLE_STATUSES:
            return json_response(error='当前状态不允许上传明细附件')
        file = request.FILES.get('file')
        if not file:
            return json_response(error='缺少上传文件')
        att, error = AttachmentService.upload(
            file, request.user, EL_ATTACHMENT_MODULE, LEDGER_ITEM_ATTACHMENT_OBJECT_TYPE,
            item.id, config=DefaultAttachmentConfig, owner_tenant_id=ledger.tenant_id)
        if error:
            return json_response(error=error)
        record_audit_event(request, 'create', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
                           after_value={'action_kind': 'upload_ledger_item_attachment',
                                        'item': item.item_name_snapshot, 'file_name': att.file_name})
        return json_response(att.to_view())


class LedgerItemAttachmentDetailView(View):
    def _check(self, request, pk, item_pk):
        ledger = _get_ledger_for_user(pk, request.user)
        if not ledger:
            return None, None, '台账不存在'
        item = _get_ledger_item_for_user(ledger, item_pk)
        if not item:
            return None, None, '台账明细不存在'
        return ledger, item, None

    @auth('equipment_lifecycle.ledger.edit')
    def delete(self, request, pk, item_pk, aid):
        ledger, item, error = self._check(request, pk, item_pk)
        if error:
            return json_response(error=error)
        if ledger.status not in OperationLedger.EDITABLE_STATUSES:
            return json_response(error='当前状态不允许删除明细附件')
        att = _attachment_for_user(request.user, aid, LEDGER_ITEM_ATTACHMENT_OBJECT_TYPE, item.id)
        if not att:
            return json_response(error=ATTACHMENT_DELETE_DENIED_ERROR)
        error = AttachmentService.soft_delete(
            request.user, aid, EL_ATTACHMENT_MODULE, LEDGER_ITEM_ATTACHMENT_OBJECT_TYPE,
            reason='运维台账明细附件删除')
        if error:
            return json_response(error=error)
        record_audit_event(request, 'delete', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
                           before_value={'action_kind': 'delete_ledger_item_attachment',
                                         'item': item.item_name_snapshot, 'file_name': att.file_name})
        return json_response({})


class LedgerItemAttachmentDownloadView(View):
    @auth('equipment_lifecycle.ledger.view')
    def get(self, request, pk, item_pk, aid):
        ledger = _get_ledger_for_user(pk, request.user)
        if not ledger:
            return json_response(error='台账不存在')
        item = _get_ledger_item_for_user(ledger, item_pk)
        if not item:
            return json_response(error='台账明细不存在')
        att = _attachment_for_user(request.user, aid, LEDGER_ITEM_ATTACHMENT_OBJECT_TYPE, item.id)
        if not att:
            return json_response(error=ATTACHMENT_ACCESS_DENIED_ERROR)
        response, error = AttachmentService.download_response(
            request.user, aid, EL_ATTACHMENT_MODULE, LEDGER_ITEM_ATTACHMENT_OBJECT_TYPE)
        if error:
            return json_response(error=error)
        return response

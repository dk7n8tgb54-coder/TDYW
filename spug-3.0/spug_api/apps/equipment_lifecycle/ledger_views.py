# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""设备全生命周期——周月维护/季维护台账视图（步骤 3.2）。

权限域（前后端一致，后端独立校验）：
- equipment_lifecycle.ledger.view|add|edit|submit|del|export
  （submit=完成填写；del=作废/删除）
- Excel 模板管理使用 equipment_lifecycle.ledger_template.view|add|edit|del
  （见 excel_template_views），旧可视化模板台账路线已删除（2026-10）

约定：
- 台账系统关联通过系统 ID，后端重新查询系统，不信任前端传来的名称；
- 正式新增台账统一走 Excel/WPS 模板路线（/excel-ledgers/），
  POST /ledgers/ 仅保留手工补录（created_from=manual）能力；
- 流程简化（2026-10-16）：完成填写（complete）为流程终点，不再提交复核；
  删除为物理删除（草稿，审计留痕）；台账创建/完成/作废/删除均考虑重复
  请求（状态机 + client_token）；
- 列表默认视图（2026-10-17）：状态筛选为空时不展示已作废（默认隐藏只是
  筛选），status=void 主动查看、status=all 明确包含已作废；四个查询入口
  （统一列表/周期分组/模板分组/明细导出）共用同一口径；
- HTTP 200 + error 为业务失败；写操作记录业务审计并使用状态动作接口；
- 附件走 evidence 体系，访问前校验所属台账/明细与租户归属。
"""
import csv
import io
from urllib.parse import quote

from django.db.models import Q
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

from apps.equipment_lifecycle import ledger_period_services, ledger_services, ledger_template_group_services
from apps.equipment_lifecycle.ledger_services import (
    LEDGER_STATUS_FILTER_ALL,
    LedgerValidationError, legacy_inspection_error,
    append_item_disposition,
)
from apps.equipment_lifecycle.models import (
    ITEM_RESULT_ABNORMAL,
    ITEM_RESULT_TEXT_MAP_FULL,
    LEDGER_FROM_EXCEL,
    LEDGER_FROM_MANUAL,
    LEDGER_STATUS_VOID,
    LEDGER_TYPE_TEXT,
    LifecycleSystem,
    OperationLedger,
    OperationLedgerItem,
)
from apps.equipment_lifecycle.views import (
    EL_ATTACHMENT_MODULE,
    _read_json_body,
)

AUDIT_TARGET_LEDGER = 'el_operation_ledger'

# 附件归属标识：台账表头 / 台账明细
LEDGER_ATTACHMENT_OBJECT_TYPE = 'el_operation_ledger'
LEDGER_ITEM_ATTACHMENT_OBJECT_TYPE = 'el_operation_ledger_item'

# 统一列表详情路由（与前端 routes.js 的正式台账路径一致）
LEDGER_TYPE_DETAIL_PATH = {
    'week_month': '/el/week-month-ledgers',
    'seasonal': '/el/seasonal-ledgers',
}

# 统一列表来源类型（由 created_from 派生；旧可视化模板来源已随路线删除）
LEDGER_FROM_SOURCE_TYPE = {
    LEDGER_FROM_MANUAL: 'manual',
    LEDGER_FROM_EXCEL: 'excel',
}


# ======================================================================
# 台账
# ======================================================================

def _get_ledger_for_user(pk, user):
    return apply_tenant_filter(OperationLedger.objects.all(), user).filter(pk=pk).first()


def _ledger_detail(ledger, user=None):
    if ledger.created_from == LEDGER_FROM_EXCEL:
        # Excel 路线台账没有普通 OperationLedgerItem 明细，按 created_from
        # 分支返回 Excel 详情（版本快照 + 绑定 + 布局 + 填写值 + 编辑状态）
        from apps.equipment_lifecycle import excel_ledger_services

        try:
            return excel_ledger_services.ledger_detail(ledger)
        except excel_ledger_services.ExcelLedgerError:
            # 缺少填写记录的异常数据降级为基础视图，不让统一详情整体失败
            pass
    view = ledger.to_view(with_counts=True)
    items = [it.to_view() for it in ledger.items.all()]
    if user is not None:
        # 异常明细处置状态：由来源故障关系动态计算，事实依据不落库
        append_item_disposition(ledger.tenant_id, items)
    view['items'] = items
    view['corrections'] = [c.to_view() for c in ledger.corrections.all()]
    return view


def _ledger_source_fields(ledger):
    """统一列表来源字段：source_type + Excel 路线模板/版本 + 详情路由。

    Excel 路线台账的来源版本经 select_related('excel_record__version')
    读取；记录缺失（异常数据）时来源信息降级为空，不影响列表返回。
    """
    source_type = LEDGER_FROM_SOURCE_TYPE.get(ledger.created_from, ledger.created_from)
    fields = {
        'source_type': source_type,
        'source_template_name': '',
        'source_version_no': None,
        'detail_route': '',
    }
    if source_type == 'excel':
        record = getattr(ledger, 'excel_record', None)
        version = record.version if record is not None else None
        fields['source_template_name'] = version.template_name_snapshot if version else ''
        fields['source_version_no'] = version.version_no if version else None
    path = LEDGER_TYPE_DETAIL_PATH.get(ledger.ledger_type)
    if path:
        fields['detail_route'] = '%s?detail=%d&source=%s' % (
            path, ledger.id, source_type)
    return fields


def _ledger_row_fields(ledger):
    """统一列表行附加字段：来源（source_type/模板/版本/详情路由）+ 期次展示。

    期次展示字段（period_label/period_is_derived/period_source_text）由
    ledger_period_services.ledger_period_display 提供，历史台账兼容标注来源。
    """
    fields = _ledger_source_fields(ledger)
    fields.update(ledger_period_services.ledger_period_display(ledger))
    return fields


class LedgerView(View):
    @auth('equipment_lifecycle.ledger.view')
    def get(self, request):
        query = apply_tenant_filter(OperationLedger.objects.all(), request.user)
        # 统一维护台账列表（2026-10）：Excel 模板 / 手工补录一并返回，
        # 前端按 source_type 区分来源与详情路由（旧可视化模板路线已删除）
        ledger_type = request.GET.get('ledger_type')
        if ledger_type:
            query = query.filter(ledger_type=ledger_type)
        # 状态筛选统一口径（2026-10-17）：默认视图不含已作废；
        # status=void 主动查看已作废，status=all 明确包含已作废
        query = ledger_services.apply_ledger_status_filter(
            query, request.GET.get('status'))
        system_id = request.GET.get('system')
        if system_id and str(system_id).isdigit():
            # 表头级系统（周期批量台账）与明细系统（手工/历史台账）均命中
            query = query.filter(
                Q(items__system_id=system_id) | Q(system_id=system_id)).distinct()
        keyword = request.GET.get('keyword')
        if keyword:
            query = query.filter(ledger_no__icontains=keyword)
        executed_from = request.GET.get('executed_from')
        if executed_from:
            query = query.filter(executed_date__gte=executed_from)
        executed_to = request.GET.get('executed_to')
        if executed_to:
            query = query.filter(executed_date__lte=executed_to)
        query = query.select_related('system', 'excel_record__version')
        page, page_size = paginate(request)
        total = query.count()
        records = query[(page - 1) * page_size: page * page_size] if total else []
        data = []
        for record in records:
            view = record.to_view()
            view.update(_ledger_row_fields(record))
            data.append(view)
        return json_response({
            'data': data,
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


class LedgerBatchCreateView(View):
    """本租户系统选项（"按系统查看"筛选与模板配置共用，仅 GET）。

    原按类型+周期批量创建手工壳的 POST 已下线（2026-10-14）：批量生成
    统一走 /ledgers/period-generate/（按 Excel 模板生成可填写的应填台账）。
    """

    @auth('equipment_lifecycle.ledger.view')
    def get(self, request):
        systems = apply_tenant_filter(LifecycleSystem.objects.all(), request.user).order_by(
            '-is_active', 'system_code', 'id')
        return json_response({'data': [{
            'id': s.id,
            'system_code': s.system_code,
            'name': s.name,
            'install_location': s.install_location,
            'is_active': s.is_active,
        } for s in systems]})


class LedgerPeriodGenerateView(View):
    """本期应填台账生成（2026-10-14）：

    - GET 预览：按当前日期逐模板判定 将新建/已存在跳过/缺少可用版本/
      需人工处理（待配置/系统停用/作废或历史草稿占用），含期次与版本；
    - POST 确认生成：按预览同口径重算并创建缺项，返回实际新增/跳过/
      失败（不以预览数量冒充实际结果）。
    """

    @auth('equipment_lifecycle.ledger.view')
    def get(self, request):
        result, error = ledger_period_services.period_generate_preview(
            request.user, request.GET.get('ledger_type'))
        if error:
            return json_response(error=error)
        return json_response(result)

    @auth('equipment_lifecycle.ledger.add')
    def post(self, request):
        body = _read_json_body(request) or {}
        result, error = ledger_period_services.period_generate(request.user, body.get('ledger_type'))
        if error:
            return json_response(error=error)
        record_audit_event(
            request, 'create', AUDIT_TARGET_LEDGER, None,
            '生成本期应填台账（%s）' % result['ledger_type'],
            after_value={
                'action_kind': 'period_generate',
                'created': [row['ledger_no'] for row in result['created']],
                'skipped': len(result['skipped']),
                'failed': len(result['failed']),
            })
        return json_response(result)


class LedgerPeriodGenerateRebuildView(View):
    """明确补建（2026-10-16）：POST /ledgers/period-generate/rebuild/。

    body: {"template_id": <id>}——为"已作废占用"的本期槽位重新生成应填
    台账（作废台账保留不动）；本期已存在有效台账时拒绝。
    """

    @auth('equipment_lifecycle.ledger.add')
    def post(self, request):
        body = _read_json_body(request) or {}
        row, error = ledger_period_services.period_generate_rebuild(
            request.user, body.get('template_id'))
        if error:
            return json_response(error=error)
        record_audit_event(
            request, 'create', AUDIT_TARGET_LEDGER, row['id'], row['ledger_no'],
            after_value={
                'action_kind': 'period_generate_rebuild',
                'template_id': row['template_id'],
                'maintenance_period': row['maintenance_period'],
            })
        return json_response(row)


class LedgerPeriodOverviewView(View):
    """本期工作概览（2026-10-14）：周月维护展示 本周+本月，季维护展示本航季。

    返回 应填/待生成/待填写/已完成 等真实数量；待生成依据模板生成
    规则计算（与 period-generate 预览同口径），不统计已有台账冒充、不在
    前端伪造数字。
    """

    @auth('equipment_lifecycle.ledger.view')
    def get(self, request):
        result, error = ledger_period_services.period_overview(
            request.user, request.GET.get('ledger_type'))
        if error:
            return json_response(error=error)
        return json_response(result)


class LedgerPeriodGroupsView(View):
    """按 维护类型+周期 分组的台账列表：组内含各系统台账、来源与填写状态。

    - keyword 按台账编号模糊筛选（此前前端已发送但本视图未读取，导致
      "按周期查看"搜索无效，2026-10-14 修复）；
    - 分页按期次组切片，组内统计与可见行一致。
    """

    @auth('equipment_lifecycle.ledger.view')
    def get(self, request):
        page, page_size = paginate(request)
        try:
            data = ledger_period_services.list_period_groups(
                request.user, request.GET.get('ledger_type'),
                status=request.GET.get('status') or '',
                system_id=request.GET.get('system'),
                keyword=request.GET.get('keyword') or '',
                page=page, page_size=page_size,
                row_serializer=_ledger_row_fields)
        except LedgerValidationError as e:
            return json_response(error=str(e))
        return json_response(data)


class LedgerTemplateGroupsView(View):
    """按模板身份分组的台账统计（"按模板查看"视图，2026-10-11）。

    - 组 = Excel 模板组（模板主键为组键）+ 无模板/临时补录组（manual）；
    - 统计（总数/各状态/最近执行日期）在数据库端按组聚合，不受组内分页影响；
    - 仅返回有历史台账的组；支持与组内列表同口径的筛选参数。
    """

    @auth('equipment_lifecycle.ledger.view')
    def get(self, request):
        page, page_size = paginate(request)
        try:
            data = ledger_template_group_services.list_template_groups(
                request.user, request.GET.get('ledger_type'),
                status=request.GET.get('status') or '',
                keyword=request.GET.get('keyword') or '',
                executed_from=request.GET.get('executed_from') or '',
                executed_to=request.GET.get('executed_to') or '',
                page=page, page_size=page_size)
        except LedgerValidationError as e:
            return json_response(error=str(e))
        return json_response(data)


class LedgerTemplateGroupLedgersView(View):
    """模板组内台账分页列表（group_key=模板主键 或 manual）。

    行结构与统一列表一致并携带来源字段（source_version_no 为创建时版本）；
    模板归属与台账类型由后端独立校验，跨租户组键一律拒绝。
    """

    @auth('equipment_lifecycle.ledger.view')
    def get(self, request, group_key):
        page, page_size = paginate(request)
        try:
            data = ledger_template_group_services.list_group_ledgers(
                request.user, group_key, request.GET.get('ledger_type'),
                status=request.GET.get('status') or '',
                keyword=request.GET.get('keyword') or '',
                executed_from=request.GET.get('executed_from') or '',
                executed_to=request.GET.get('executed_to') or '',
                page=page, page_size=page_size,
                row_serializer=_ledger_row_fields)
        except LedgerValidationError as e:
            return json_response(error=str(e))
        return json_response(data)


class LedgerTemplateGroupBrowseView(View):
    """模板组翻阅清单（"翻阅台账"，2026-10-18）：组内符合筛选的台账有序清单。

    - 筛选口径与组内列表一致（默认不含已作废，status=void/all 显式放宽）；
    - 一次性返回全部条目（ID+期次/状态/版本元数据），前端"上一张/下一张/
      期次跳转"在该清单内移动，可跨组内列表分页边界逐张查看；
    - 排序以计划维护期次为主（起始日期升序），无期次标记的历史台账回退
      按执行日期、ID 兜底稳定；同一期次补建并存的多张台账全部保留；
    - 每张台账版式回放仍走既有 Excel 详情端点（创建时版本快照）。
    """

    @auth('equipment_lifecycle.ledger.view')
    def get(self, request, group_key):
        try:
            data = ledger_template_group_services.browse_group_ledgers(
                request.user, group_key, request.GET.get('ledger_type'),
                status=request.GET.get('status') or '',
                keyword=request.GET.get('keyword') or '',
                executed_from=request.GET.get('executed_from') or '',
                executed_to=request.GET.get('executed_to') or '')
        except LedgerValidationError as e:
            return json_response(error=str(e))
        return json_response(data)


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

    @auth('equipment_lifecycle.ledger.del')
    def delete(self, request, pk):
        """物理删除台账（草稿；已完成与已作废拒绝）。

        删除与审计事件同事务写入；附件走 evidence 软删除留痕。
        """
        info, error = ledger_services.delete_ledger(request.user, pk)
        if error:
            return json_response(error=error)
        record_audit_event(request, 'delete', AUDIT_TARGET_LEDGER, info['id'], info['ledger_no'],
                           before_value={'status': info['status'],
                                         'ledger_type': info['ledger_type'],
                                         'created_from': info['created_from']},
                           after_value={'action_kind': 'delete_ledger'})
        return json_response({})


class LedgerCompleteView(View):
    """完成填写（流程终点）：先保存未保存内容（前端保证），后端校验必填后
    草稿 → 已完成。Excel 路线台账在服务层内委派 Excel 专用校验。"""

    @auth('equipment_lifecycle.ledger.submit')
    def post(self, request, pk):
        body = _read_json_body(request) or {}
        ledger = _get_ledger_for_user(pk, request.user)
        if not ledger:
            return json_response(error='台账不存在')
        if ledger.created_from == LEDGER_FROM_EXCEL:
            from apps.equipment_lifecycle import excel_ledger_services
            ledger, error = excel_ledger_services.complete_ledger(request.user, pk)
        else:
            ledger, error = ledger_services.complete_ledger(request.user, pk)
        if error:
            return json_response(error=error)
        record_audit_event(request, 'update', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
                           after_value={'action_kind': 'complete_ledger',
                                        'status': ledger.status,
                                        'source': body.get('source') or ''})
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
        # 异常明细处置状态：由来源故障关系动态计算
        append_item_disposition(request.user.tenant_id, data)
        return json_response({'data': data, 'total': total, 'page': page, 'page_size': page_size})


def _apply_ledger_item_filters(query, params):
    """导出/明细查询共用过滤（GET 参数 → ORM 条件，日期用范围查询）。

    状态筛选与列表同口径（apply_ledger_status_filter）：默认视图排除
    已作废，status=void/all 显式调整范围。返回 (query, applied_filters)：
    applied_filters 只记录实际生效的筛选（system 仅在为数字时生效；状态
    默认口径也如实记录），供导出审计如实记录真实筛选范围。
    """
    applied = {}
    ledger_type = params.get('ledger_type')
    if ledger_type:
        query = query.filter(ledger__ledger_type=ledger_type)
        applied['ledger_type'] = ledger_type
    status = params.get('status')
    query = ledger_services.apply_ledger_status_filter(query, status, field='ledger__status')
    applied['status'] = status if status else '默认(不含已作废)'
    system_id = params.get('system')
    if system_id and str(system_id).isdigit():
        query = query.filter(system_id=system_id)
        applied['system'] = system_id
    date_from = params.get('executed_from')
    if date_from:
        query = query.filter(ledger__executed_date__gte=date_from)
        applied['executed_from'] = date_from
    date_to = params.get('executed_to')
    if date_to:
        query = query.filter(ledger__executed_date__lte=date_to)
        applied['executed_to'] = date_to
    keyword = params.get('keyword')
    if keyword:
        query = query.filter(ledger__ledger_no__icontains=keyword)
        applied['keyword'] = keyword
    return query, applied


def _format_ledger_item_value(item):
    """明细填写值的 CSV 展示文本（按录入类型分列取值）。"""
    if item.input_type == 'number':
        return '' if item.value_number is None else item.value_number
    if item.input_type == 'boolean':
        return '' if item.value_bool is None else ('是' if item.value_bool else '否')
    value = item.get_value_list() if item.input_type == 'multi_choice' and item.value_text \
        else item.value_text
    if isinstance(value, list):
        return '、'.join(map(str, value))
    return value


class LedgerExportView(View):
    """台账明细级 CSV 导出：重新执行查询与租户过滤，不信任前端明细 ID。

    - 筛选参数（ledger_type/status/system/日期范围/keyword）原样重新执行
      ORM 过滤，状态口径与列表一致（默认视图不含已作废，status=void/all
      显式调整），租户边界由 tenant_id 过滤独立保证；
    - 审计记录真实生效的筛选范围与导出行数；
    - Excel 模板路线台账没有普通明细行，天然不出现在本导出中（其完整
      填写内容走详情内导出 Excel/PDF）。
    """

    @auth('equipment_lifecycle.ledger.export')
    def get(self, request):
        query, applied_filters = _apply_ledger_item_filters(
            OperationLedgerItem.objects.filter(
                tenant_id=request.user.tenant_id, ledger__isnull=False),
            request.GET)
        rows = query.select_related('ledger', 'system').order_by('-ledger__executed_date', '-id')
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([
            '台账编号', '台账类型', '实际执行日期', '状态', '系统编号', '系统名称',
            '项目名称', '录入类型', '填写值', '单位',
            '结果', '异常说明', '不适用原因', '现场处理内容',
            '明细执行时间', '录入渠道', '录入时间'])
        count = 0
        for item in rows:
            ledger = item.ledger
            value = _format_ledger_item_value(item)
            writer.writerow([
                ledger.ledger_no, LEDGER_TYPE_TEXT.get(ledger.ledger_type, ledger.ledger_type),
                ledger.executed_date,
                ledger.status, item.system_code_snapshot, item.system_name_snapshot,
                item.item_name_snapshot,
                item.input_type, value, item.unit_snapshot,
                ITEM_RESULT_TEXT_MAP_FULL.get(item.result, item.result),
                item.abnormal_desc, item.na_reason, item.onsite_action,
                item.executed_at or '', ledger.entry_channel,
                ledger.created_at])
            count += 1
        type_label = LEDGER_TYPE_TEXT.get(request.GET.get('ledger_type'))
        filename = ('%s台账明细.csv' % type_label) if type_label else '维护台账明细.csv'
        response = HttpResponse(buffer.getvalue().encode('utf-8-sig'), content_type='text/csv')
        response['Content-Disposition'] = "attachment; filename*=UTF-8''%s" % quote(filename)
        record_audit_event(request, 'export', AUDIT_TARGET_LEDGER, None, '运维台账明细',
                           after_value={'rows': count, 'filters': applied_filters})
        return response


# ======================================================================
# 台账附件（表头 / 明细）
# ======================================================================

def _get_ledger_item_for_user(ledger, item_pk):
    return ledger.items.filter(pk=item_pk).first()


def _reject_inspection_ledger(ledger):
    """已删除的旧巡检类型统一拦截：附件上传/删除等写操作在此拒绝（查看/下载不受限）。"""
    return legacy_inspection_error(ledger)


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
        error = _reject_inspection_ledger(ledger)
        if error:
            return json_response(error=error)
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
        error = _reject_inspection_ledger(ledger)
        if error:
            return json_response(error=error)
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
        error = _reject_inspection_ledger(ledger)
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
        error = _reject_inspection_ledger(ledger)
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

# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——原生维护台账模板/台账视图（2026-10-18 接入）。

权限域（复用既有权限码，不新增；与 Excel 路线同码同权）：
- equipment_lifecycle.ledger_template.view：模板列表 / 详情 / 版本 / 可用模板
- equipment_lifecycle.ledger_template.add：创建模板
- equipment_lifecycle.ledger_template.edit：保存草稿 / 发布版本 / 修改基础信息
- equipment_lifecycle.ledger_template.del：停用 / 删除模板
- equipment_lifecycle.ledger.view：原生台账列表 / 详情
- equipment_lifecycle.ledger.add：按模板版本创建台账
- equipment_lifecycle.ledger.edit：保存填写值 / 完成后更正
- equipment_lifecycle.ledger.submit：完成填写（流程终点）
- equipment_lifecycle.ledger.export：导出 PDF

约定：
- View 层只做参数解析、权限检查、调用 Service、组装响应；HTTP 200 + error
  为业务失败（前端拦截器统一提示，调用方不得当成功）；
- 已发布版本只读：版本详情视图不定义 PUT/POST/DELETE（写方法缺失即 405）；
  发布版本无修改/删除路径，历史台账引用的版本快照永不漂移；
- 台账读取全部经租户过滤 + created_from=native_template 双重限定，
  跨租户访问与不存在同样返回"台账不存在"；作废/删除沿用既有 /ledgers/<pk>/
  端点（与 Excel 路线一致）；
- PDF 导出为文件副作用视图，使用 transaction.non_atomic_requests。
"""
from django.db import transaction
from django.views.generic import View

from libs import auth, json_response

from apps.logs.audit import record_audit_event
from apps.equipment_lifecycle import native_ledger_services, native_template_services
from apps.equipment_lifecycle.excel_template_views import (
    PDF_CONTENT_TYPE,
    _na,
    file_response,
)
from apps.equipment_lifecycle.ledger_views import (
    AUDIT_TARGET_LEDGER,
    _read_json_body,
)
from apps.equipment_lifecycle.native_template_services import NativeTemplateError

AUDIT_TARGET_TEMPLATE = 'el_ledger_native_template'

PERM_TPL_VIEW = 'equipment_lifecycle.ledger_template.view'
PERM_TPL_ADD = 'equipment_lifecycle.ledger_template.add'
PERM_TPL_EDIT = 'equipment_lifecycle.ledger_template.edit'
PERM_TPL_DEL = 'equipment_lifecycle.ledger_template.del'

# 导出文件名状态后缀（与前端 constants.js 的状态文案一致）
LEDGER_STATUS_SUFFIX = {
    'draft': '草稿', 'completed': '已完成', 'void': '已作废',
}


def _get_template_or_none(pk, user):
    return native_template_services.get_template(pk, user)


# ======================================================================
# 原生台账模板
# ======================================================================

class NativeTemplateView(View):
    """模板列表（GET）/ 创建模板（POST JSON：name + ledger_type + description）。"""

    @auth(PERM_TPL_VIEW)
    def get(self, request):
        return json_response({'data': native_template_services.list_templates(request.user)})

    @auth(PERM_TPL_ADD)
    def post(self, request):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        try:
            template = native_template_services.create_template(request.user, body)
        except NativeTemplateError as e:
            return json_response(error=str(e))
        record_audit_event(
            request, 'create', AUDIT_TARGET_TEMPLATE, template.pk, template.name,
            after_value={'ledger_type': template.ledger_type})
        return json_response({'data': native_template_services.template_detail(template)})


class NativeTemplateDetailView(View):
    """模板详情（含草稿内容与版本列表）/ 修改基础信息 / 物理删除。"""

    @auth(PERM_TPL_VIEW)
    def get(self, request, pk):
        template = _get_template_or_none(pk, request.user)
        if not template:
            return json_response(error='原生台账模板不存在')
        return json_response({'data': native_template_services.template_detail(template)})

    @auth(PERM_TPL_EDIT)
    def put(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        template = _get_template_or_none(pk, request.user)
        if not template:
            return json_response(error='原生台账模板不存在')
        try:
            template = native_template_services.update_template_meta(
                request.user, template, body)
        except NativeTemplateError as e:
            return json_response(error=str(e))
        record_audit_event(
            request, 'update', AUDIT_TARGET_TEMPLATE, template.pk, template.name,
            after_value={'action_kind': 'update_template_meta'})
        return json_response({'data': native_template_services.template_detail(template)})

    @auth(PERM_TPL_DEL)
    def delete(self, request, pk):
        """物理删除模板（行锁内复查引用；被台账引用只能停用）。"""
        template = _get_template_or_none(pk, request.user)
        if not template:
            return json_response(error='模板不存在或无权限访问')
        try:
            info = native_template_services.destroy_template(request.user, template)
        except NativeTemplateError as e:
            return json_response(error=str(e))
        record_audit_event(
            request, 'delete', AUDIT_TARGET_TEMPLATE, info['id'], info['name'],
            after_value={'action_kind': 'destroy_template',
                         'versions_count': info['versions_count']})
        return json_response({})


class NativeTemplateDeactivateView(View):
    """停用模板（逻辑停用，幂等）；停用后不能用于新台账与编辑草稿。"""

    @auth(PERM_TPL_DEL)
    def post(self, request, pk):
        template = _get_template_or_none(pk, request.user)
        if not template:
            return json_response(error='模板不存在或无权限访问')
        template, deactivated_now = native_template_services.deactivate_template(
            request.user, template)
        if deactivated_now:
            record_audit_event(
                request, 'delete', AUDIT_TARGET_TEMPLATE, template.pk, template.name,
                after_value={'action_kind': 'deactivate_template', 'is_active': False})
        return json_response({'data': native_template_services.template_detail(template)})


class NativeTemplateDraftView(View):
    """保存草稿（PUT 整体替换：snapshot + bindings + paper）。"""

    @auth(PERM_TPL_EDIT)
    def put(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        template = _get_template_or_none(pk, request.user)
        if not template:
            return json_response(error='原生台账模板不存在')
        try:
            template = native_template_services.save_draft(request.user, template, body)
        except NativeTemplateError as e:
            return json_response(error=str(e))
        record_audit_event(
            request, 'update', AUDIT_TARGET_TEMPLATE, template.pk, template.name,
            after_value={'action_kind': 'save_native_draft'})
        return json_response({'data': native_template_services.template_detail(template)})


class NativeTemplatePublishView(View):
    """发布版本：草稿快照为不可变版本（只增不改；重复发布产生新版本号）。"""

    @auth(PERM_TPL_EDIT)
    def post(self, request, pk):
        template = _get_template_or_none(pk, request.user)
        if not template:
            return json_response(error='原生台账模板不存在')
        try:
            version = native_template_services.publish_version(request.user, template)
        except NativeTemplateError as e:
            return json_response(error=str(e))
        record_audit_event(
            request, 'update', AUDIT_TARGET_TEMPLATE, template.pk, template.name,
            after_value={'action_kind': 'publish_native_version',
                         'version_no': version.version_no,
                         'field_count': version.field_count})
        return json_response({'data': native_template_services.template_detail(template)})


class NativeTemplateVersionsView(View):
    """版本列表（只读；版本不可变，无写方法）。"""

    @auth(PERM_TPL_VIEW)
    def get(self, request, pk):
        template = _get_template_or_none(pk, request.user)
        if not template:
            return json_response(error='原生台账模板不存在')
        return json_response({'data': [v.to_view() for v in template.versions.all()]})


class NativeTemplateVersionDetailView(View):
    """版本详情（含快照内容；只读，供版式回放与打印）。"""

    @auth(PERM_TPL_VIEW)
    def get(self, request, pk, version_no):
        template = _get_template_or_none(pk, request.user)
        if not template:
            return json_response(error='原生台账模板不存在')
        version = template.versions.filter(version_no=version_no).first()
        if not version:
            return json_response(error='模板版本不存在')
        return json_response({'data': version.to_view(with_content=True)})


class NativeTemplateAvailableView(View):
    """台账创建用：启用且有已发布版本的原生模板（可按类型过滤）。"""

    @auth('equipment_lifecycle.ledger.view')
    def get(self, request):
        items = native_template_services.available_templates(
            request.user, request.GET.get('ledger_type') or None)
        return json_response({'data': items})


# ======================================================================
# 原生路线台账
# ======================================================================

class NativeLedgerView(View):
    """原生路线台账列表（GET）/ 按模板版本创建（POST）。"""

    @auth('equipment_lifecycle.ledger.view')
    def get(self, request):
        return json_response(native_ledger_services.list_ledgers(request.user, request))

    @auth('equipment_lifecycle.ledger.add')
    def post(self, request):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        ledger, error = native_ledger_services.create_ledger(request.user, body)
        if error:
            return json_response(error=error)
        record_audit_event(
            request, 'create', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
            after_value={'ledger_type': ledger.ledger_type,
                         'created_from': ledger.created_from,
                         'native_version_id': ledger.native_record.version_id})
        return json_response({'data': native_ledger_services.ledger_detail(ledger)})


class NativeLedgerDetailView(View):
    """台账详情（表头 + 版本快照 + 填写值）/ 保存填写值。"""

    @auth('equipment_lifecycle.ledger.view')
    def get(self, request, pk):
        ledger = native_ledger_services.get_ledger(pk, request.user)
        if not ledger:
            return json_response(error='台账不存在')
        return json_response({'data': native_ledger_services.ledger_detail(ledger)})

    @auth('equipment_lifecycle.ledger.edit')
    def put(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        ledger = native_ledger_services.get_ledger(pk, request.user)
        if not ledger:
            return json_response(error='台账不存在')
        try:
            # 填写值整体替换（仅草稿可编辑）
            if 'values' in body:
                native_ledger_services.update_values(request.user, ledger, body.get('values'))
        except native_ledger_services.NativeLedgerError as e:
            return json_response(error=str(e))
        record_audit_event(
            request, 'update', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
            after_value={'action_kind': 'save_native_values',
                         'version_id': ledger.native_record.version_id})
        return json_response({'data': native_ledger_services.ledger_detail(ledger)})


class NativeLedgerCompleteView(View):
    """完成填写（流程终点）：必填校验通过后 草稿 → 已完成。"""

    @auth('equipment_lifecycle.ledger.submit')
    def post(self, request, pk):
        ledger, error = native_ledger_services.complete_ledger(request.user, pk)
        if error:
            return json_response(error=error)
        record_audit_event(
            request, 'update', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
            after_value={'action_kind': 'complete_native_ledger',
                         'status': ledger.status})
        return json_response({'data': native_ledger_services.ledger_detail(ledger)})


class NativeLedgerCorrectView(View):
    """已完成台账更正：POST /native-ledgers/<pk>/correct/（须填原因，记录前后值）。"""

    @auth('equipment_lifecycle.ledger.edit')
    def post(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        ledger = native_ledger_services.get_ledger(pk, request.user)
        if not ledger:
            return json_response(error='台账不存在')
        ledger, correction, changes, error = native_ledger_services.correct_completed_ledger(
            request.user, ledger, body)
        if error:
            return json_response(error=error)
        record_audit_event(
            request, 'update', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
            after_value={'action_kind': 'correct_native_ledger',
                         'reason': correction.reason, 'changes': changes})
        return json_response({'data': native_ledger_services.ledger_detail(ledger)})


class NativeLedgerExportPdfView(View):
    """导出 PDF：POST /native-ledgers/<pk>/export/pdf/。

    服务端按台账引用版本快照 + 填写值生成分页 HTML 后经 Chromium 转换；
    必填未填/引擎不可用转业务错误。文件副作用视图（non_atomic）。
    """

    @_na
    @auth('equipment_lifecycle.ledger.export')
    def post(self, request, pk):
        ledger = native_ledger_services.get_ledger(pk, request.user)
        if not ledger:
            return json_response(error='台账不存在')
        try:
            content = native_ledger_services.export_pdf_file(request.user, ledger)
        except native_ledger_services.NativeLedgerError as e:
            return json_response(error=str(e))
        record_audit_event(
            request, 'export', AUDIT_TARGET_LEDGER, ledger.id, ledger.ledger_no,
            after_value={'format': 'pdf',
                         'version_id': ledger.native_record.version_id})
        base_name = native_ledger_services.export_base_name(ledger)
        suffix = LEDGER_STATUS_SUFFIX.get(ledger.status, ledger.status)
        filename = '%s-%s.pdf' % (base_name, suffix)
        return file_response(filename, content, PDF_CONTENT_TYPE)

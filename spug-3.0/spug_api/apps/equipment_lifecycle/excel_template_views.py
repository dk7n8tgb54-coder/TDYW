# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""设备全生命周期——Excel 上传版维护台账模板视图（2026-09-28 试点）。

权限域（复用既有台账模板权限码，不新增）：
- equipment_lifecycle.ledger_template.view：列表 / 详情 / 版本 / 可用模板 /
  验收样例下载 / 草稿 PDF 预览 / 生成配置查看
- equipment_lifecycle.ledger_template.add：上传创建模板（含重新上传草稿）
- equipment_lifecycle.ledger_template.edit：保存绑定 / 发布版本 /
  保存 PDF 打印参数 / 保存生成配置（适用系统+生成周期，2026-10-14）
- equipment_lifecycle.ledger_template.del：删除模板（逻辑删除/停用，幂等）

约定：
- View 层只做参数解析、权限检查、调用 Service、组装响应；解析/校验/
  文件副作用全部在 excel_template_manage / excel_template_storage；
- HTTP 200 + error 为业务失败（前端拦截器统一提示，调用方不得当成功）；
- 已发布版本只读：版本详情视图不定义 PUT/POST/DELETE（写方法缺失即 405）；
- 模板/版本读取全部经租户过滤，跨租户访问与不存在同样返回
  "Excel台账模板不存在"，不泄露目标是否存在；删除接口统一返回
  "模板不存在或无权限访问"（不存在与跨租户同文案）；
- 上传/发布为文件副作用视图，使用 transaction.non_atomic_requests。
"""
import json
from urllib.parse import quote

from django.db import transaction
from django.http import HttpResponse
from django.views.generic import View

from libs import auth, json_response

from apps.logs.audit import record_audit_event
from apps.equipment_lifecycle import excel_sample_template, excel_template_manage
from apps.equipment_lifecycle.excel_template_manage import ExcelTemplateError
from apps.equipment_lifecycle.ledger_views import _read_json_body

AUDIT_TARGET = 'el_ledger_excel_template'

PERM_TPL_VIEW = 'equipment_lifecycle.ledger_template.view'
PERM_TPL_ADD = 'equipment_lifecycle.ledger_template.add'
PERM_TPL_EDIT = 'equipment_lifecycle.ledger_template.edit'
PERM_TPL_DEL = 'equipment_lifecycle.ledger_template.del'

XLSX_CONTENT_TYPE = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
PDF_CONTENT_TYPE = 'application/pdf'


def _na(view):
    """文件副作用视图装配：关闭请求级原子事务（文件操作不可回滚）。"""
    return transaction.non_atomic_requests(view)


def file_response(filename, content, content_type):
    response = HttpResponse(content, content_type=content_type)
    response['Content-Disposition'] = "attachment; filename*=UTF-8''%s" % quote(filename)
    return response


def _binding_count(template):
    if not template.draft_bindings:
        return 0
    try:
        return len(json.loads(template.draft_bindings))
    except (ValueError, TypeError):
        return 0


def _get_template_or_none(pk, user):
    return excel_template_manage.get_excel_template(pk, user)


class ExcelTemplateView(View):
    """模板列表 / 上传 .xlsx 创建模板（multipart：file + name + ledger_type + description）。"""

    @auth(PERM_TPL_VIEW)
    def get(self, request):
        return json_response({'data': excel_template_manage.list_templates(request.user)})

    @_na
    @auth(PERM_TPL_ADD)
    def post(self, request):
        file = request.FILES.get('file')
        if not file:
            return json_response(error='缺少上传文件')
        body = {
            'name': request.POST.get('name'),
            'ledger_type': request.POST.get('ledger_type'),
            'description': request.POST.get('description'),
        }
        data = file.read()
        try:
            template = excel_template_manage.create_template(
                request.user, file.name, data, body)
        except ExcelTemplateError as e:
            return json_response(error=str(e))
        record_audit_event(
            request, 'create', AUDIT_TARGET, template.pk, template.name,
            after_value={'ledger_type': template.ledger_type,
                         'source_filename': template.draft_source_filename,
                         'source_hash': template.draft_source_hash})
        return json_response({'data': excel_template_manage.template_detail(template)})


class ExcelTemplateDetailView(View):
    """模板详情（含草稿布局与绑定，供绑定工作区恢复）；DELETE 为逻辑删除。"""

    @auth(PERM_TPL_VIEW)
    def get(self, request, pk):
        template = _get_template_or_none(pk, request.user)
        if not template:
            return json_response(error='Excel台账模板不存在')
        return json_response({'data': excel_template_manage.template_detail(template)})

    @auth(PERM_TPL_DEL)
    def delete(self, request, pk):
        """删除模板（逻辑删除/停用，幂等）；版本与历史台账全部保留。

        不存在与跨租户统一返回"模板不存在或无权限访问"；重复删除不报错、
        不重复记审计（仅实际发生停用变更时记录 delete 事件）。
        """
        template = _get_template_or_none(pk, request.user)
        if not template:
            return json_response(error='模板不存在或无权限访问')
        template, deleted_now = excel_template_manage.delete_template(
            request.user, template)
        if deleted_now:
            record_audit_event(
                request, 'delete', AUDIT_TARGET, template.pk, template.name,
                after_value={'action_kind': 'delete_template', 'is_active': False})
        return json_response({'data': excel_template_manage.template_detail(template)})


class ExcelTemplateDraftFileView(View):
    """重新上传草稿源文件：布局重建、原绑定清空（multipart：file）。"""

    @_na
    @auth(PERM_TPL_ADD)
    def post(self, request, pk):
        file = request.FILES.get('file')
        if not file:
            return json_response(error='缺少上传文件')
        template = _get_template_or_none(pk, request.user)
        if not template:
            return json_response(error='Excel台账模板不存在')
        data = file.read()
        try:
            excel_template_manage.replace_draft_file(request.user, template, file.name, data)
        except ExcelTemplateError as e:
            return json_response(error=str(e))
        record_audit_event(
            request, 'update', AUDIT_TARGET, template.pk, template.name,
            after_value={'action_kind': 'replace_draft_file',
                         'source_filename': template.draft_source_filename,
                         'source_hash': template.draft_source_hash})
        return json_response({'data': excel_template_manage.template_detail(template)})


class ExcelTemplateBindingsView(View):
    """保存字段绑定（整体替换，全量校验通过才落库）。"""

    @auth(PERM_TPL_EDIT)
    def put(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        template = _get_template_or_none(pk, request.user)
        if not template:
            return json_response(error='Excel台账模板不存在')
        try:
            excel_template_manage.save_bindings(request.user, template, body.get('field_bindings'))
        except ExcelTemplateError as e:
            return json_response(error=str(e))
        record_audit_event(
            request, 'update', AUDIT_TARGET, template.pk, template.name,
            after_value={'action_kind': 'save_bindings',
                         'binding_count': _binding_count(template)})
        return json_response({'data': excel_template_manage.template_detail(template)})


class ExcelTemplateGenerationConfigView(View):
    """模板生成配置（适用系统 + 生成周期，2026-10-14 本期应填台账生成）。

    - GET /excel-templates/<pk>/generation-config/：当前配置 + 可选项
      （本租户系统清单、按台账类型收敛的生成周期候选）；
    - PUT：整体校验后保存（空值显式清空回"待配置"）；配置只影响自动
      生成，不影响手工创建，已生成台账不回溯。
    """

    @auth(PERM_TPL_VIEW)
    def get(self, request, pk):
        template = _get_template_or_none(pk, request.user)
        if not template:
            return json_response(error='Excel台账模板不存在')
        options = excel_template_manage.generation_config_options(request.user)
        return json_response({'data': {
            'template_id': template.id,
            'system': template.system_id,
            'generation_period': template.generation_period,
            'systems': options['systems'],
            'periods': options['periods'],
        }})

    @auth(PERM_TPL_EDIT)
    def put(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        template = _get_template_or_none(pk, request.user)
        if not template:
            return json_response(error='Excel台账模板不存在')
        try:
            excel_template_manage.save_generation_config(request.user, template, body)
        except ExcelTemplateError as e:
            return json_response(error=str(e))
        record_audit_event(
            request, 'update', AUDIT_TARGET, template.pk, template.name,
            after_value={'action_kind': 'save_generation_config',
                         'system': template.system_id,
                         'generation_period': template.generation_period})
        return json_response({'data': excel_template_manage.template_detail(template)})


class ExcelTemplatePublishView(View):
    """发布：草稿通过发布级校验后快照为新的不可变版本。"""

    @_na
    @auth(PERM_TPL_EDIT)
    def post(self, request, pk):
        template = _get_template_or_none(pk, request.user)
        if not template:
            return json_response(error='Excel台账模板不存在')
        try:
            version = excel_template_manage.publish_version(request.user, template)
        except ExcelTemplateError as e:
            return json_response(error=str(e))
        record_audit_event(
            request, 'create', AUDIT_TARGET, template.pk, template.name,
            after_value={'action_kind': 'publish_version',
                         'version_no': version.version_no,
                         'field_count': version.field_count,
                         'source_hash': version.source_hash})
        return json_response({'data': version.to_view()})


class ExcelTemplatePdfPreviewView(View):
    """模板草稿 PDF 预览（发布前真实打印效果；未填写字段保持空白）。

    URL：POST /excel-templates/<pk>/preview/pdf/（POST 语义：触发生成，
    幂等只读，可重复调用）。只读草稿源文件与当前绑定，不改草稿文件、
    不创建版本、不改变绑定；文件副作用仅限临时目录（自动清理）。
    """

    @_na
    @auth(PERM_TPL_VIEW)
    def post(self, request, pk):
        template = _get_template_or_none(pk, request.user)
        if not template:
            return json_response(error='Excel台账模板不存在')
        try:
            content = excel_template_manage.preview_draft_pdf(template)
        except ExcelTemplateError as e:
            return json_response(error=str(e))
        base_name = (template.draft_source_filename or '模板').rsplit('.', 1)[0]
        return file_response('%s-模板预览.pdf' % base_name, content, PDF_CONTENT_TYPE)


class ExcelTemplatePdfParamsView(View):
    """保存模板级 PDF 打印参数（草稿级；发布时随版本快照固定）。

    PUT /excel-templates/<pk>/pdf-params/，body: {"pdf_params": {...}}；
    参数保存在草稿布局 JSON 内（零迁移），校验失败整体不落库。
    """

    @auth(PERM_TPL_EDIT)
    def put(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        template = _get_template_or_none(pk, request.user)
        if not template:
            return json_response(error='Excel台账模板不存在')
        try:
            excel_template_manage.save_pdf_params(
                request.user, template, body.get('pdf_params'))
        except ExcelTemplateError as e:
            return json_response(error=str(e))
        record_audit_event(
            request, 'update', AUDIT_TARGET, template.pk, template.name,
            after_value={'action_kind': 'save_pdf_params'})
        return json_response({'data': excel_template_manage.template_detail(template)})


class ExcelTemplateVersionListView(View):
    """已发布版本列表（元信息，不含布局内容）。"""

    @auth(PERM_TPL_VIEW)
    def get(self, request, pk):
        template = _get_template_or_none(pk, request.user)
        if not template:
            return json_response(error='Excel台账模板不存在')
        return json_response({'data': [v.to_view() for v in template.versions.all()]})


class ExcelTemplateVersionDetailView(View):
    """已发布版本详情（含布局与绑定快照；只读，写方法缺失即 405）。"""

    @auth(PERM_TPL_VIEW)
    def get(self, request, pk, version_no):
        template = _get_template_or_none(pk, request.user)
        if not template:
            return json_response(error='Excel台账模板不存在')
        version = template.versions.filter(version_no=version_no).first()
        if not version:
            return json_response(error='模板版本不存在')
        return json_response({'data': version.to_view(with_content=True)})


class ExcelTemplateAvailableView(View):
    """台账创建用：启用且有已发布版本的模板（可按 ledger_type 过滤）。"""

    @auth('equipment_lifecycle.ledger.view')
    def get(self, request):
        data = excel_template_manage.available_templates(
            request.user, request.GET.get('ledger_type') or None)
        return json_response({'data': data})


class ExcelTemplateSampleView(View):
    """下载验收样例模板（含合并/边框/行高列宽/打印设置/页眉页脚/双工作表）。"""

    @auth(PERM_TPL_VIEW)
    def get(self, request):
        content = excel_sample_template.build_acceptance_sample_xlsx()
        return file_response('信道维护台账验收样例.xlsx', content, XLSX_CONTENT_TYPE)

# Copyright: (c) OpenSpug Organization. https://github.com/openspug
# Released under the AGPL-3.0 License.
"""数字表单台账模板管理视图（2026-10-21）。

权限域与 Excel 模板管理一致（不新增权限码）：
- equipment_lifecycle.ledger_template.view|add|edit|del
- available 端点（台账创建数据源）使用台账域 equipment_lifecycle.ledger.view
  （与 Excel 模板 available 同口径）。

约定：HTTP 200 + error 为业务失败；写操作记录业务审计；发布/删除在服务
层行锁内执行；版本只读（无修改/删除端点，写方法缺失即 405）。
"""
import json

from django.views.generic import View

from libs import json_response, auth

from apps.logs.audit import record_audit_event
from apps.equipment_lifecycle import form_pdf_service, form_template_manage
from apps.equipment_lifecycle.excel_template_views import _na, file_response
from apps.equipment_lifecycle.views import _read_json_body

AUDIT_TARGET_FORM_TEMPLATE = 'el_form_ledger_template'

PDF_CONTENT_TYPE = 'application/pdf'

PERM_TPL_VIEW = 'equipment_lifecycle.ledger_template.view'
PERM_TPL_ADD = 'equipment_lifecycle.ledger_template.add'
PERM_TPL_EDIT = 'equipment_lifecycle.ledger_template.edit'
PERM_TPL_DEL = 'equipment_lifecycle.ledger_template.del'


def _get_template_or_error(pk, request, for_update=False):
    """按租户取模板；不存在统一返回 (None, 错误响应)。"""
    template = form_template_manage.get_form_template(pk, request.user, for_update=for_update)
    if template is None:
        return None, json_response(error='模板不存在')
    return template, None


class FormTemplateView(View):
    @auth(PERM_TPL_VIEW)
    def get(self, request):
        return json_response({'data': form_template_manage.list_templates(request.user)})

    @auth(PERM_TPL_ADD)
    def post(self, request):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        try:
            template = form_template_manage.create_template(request.user, body)
        except form_template_manage.FormTemplateError as e:
            return json_response(error=str(e))
        record_audit_event(request, 'create', AUDIT_TARGET_FORM_TEMPLATE, template.id,
                           template.name,
                           after_value={'ledger_type': template.ledger_type,
                                        'template_kind': 'form'})
        return json_response(form_template_manage.template_detail(template))


class FormTemplateCreateOptionsView(View):
    """创建/配置弹窗数据源：本租户系统清单 + 生成周期选项（复用同构服务）。"""

    @auth(PERM_TPL_ADD)
    def get(self, request):
        from apps.equipment_lifecycle.excel_template_manage import generation_config_options
        return json_response(generation_config_options(request.user))


class FormTemplateDetailView(View):
    @auth(PERM_TPL_VIEW)
    def get(self, request, pk):
        template, error = _get_template_or_error(pk, request)
        if error:
            return error
        return json_response(form_template_manage.template_detail(template))

    @auth(PERM_TPL_EDIT)
    def put(self, request, pk):
        """保存草稿表单定义（全量校验后整体替换）。"""
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        template, error = _get_template_or_error(pk, request)
        if error:
            return error
        try:
            form_template_manage.save_draft_form(
                request.user, template, body.get('form'))
        except form_template_manage.FormTemplateError as e:
            return json_response(error=str(e))
        record_audit_event(request, 'update', AUDIT_TARGET_FORM_TEMPLATE, template.id,
                           template.name,
                           after_value={'action_kind': 'save_draft_form'})
        return json_response(form_template_manage.template_detail(template))

    @auth(PERM_TPL_DEL)
    def delete(self, request, pk):
        """物理删除（仅限未被任何台账引用；被引用模板只能停用）。"""
        template, error = _get_template_or_error(pk, request)
        if error:
            return error
        try:
            info = form_template_manage.destroy_template(request.user, template)
        except form_template_manage.FormTemplateError as e:
            return json_response(error=str(e))
        record_audit_event(request, 'delete', AUDIT_TARGET_FORM_TEMPLATE, info['id'],
                           info['name'],
                           before_value={'latest_version_no': info['latest_version_no']},
                           after_value={'action_kind': 'destroy_form_template'})
        return json_response({})


class FormTemplateDeactivateView(View):
    @auth(PERM_TPL_DEL)
    def post(self, request, pk):
        template, error = _get_template_or_error(pk, request)
        if error:
            return error
        form_template_manage.deactivate_template(request.user, template)
        record_audit_event(request, 'update', AUDIT_TARGET_FORM_TEMPLATE, template.id,
                           template.name,
                           after_value={'action_kind': 'deactivate_form_template'})
        return json_response(form_template_manage.template_detail(template))


class FormTemplateActivateView(View):
    @auth(PERM_TPL_DEL)
    def post(self, request, pk):
        template, error = _get_template_or_error(pk, request)
        if error:
            return error
        form_template_manage.activate_template(request.user, template)
        record_audit_event(request, 'update', AUDIT_TARGET_FORM_TEMPLATE, template.id,
                           template.name,
                           after_value={'action_kind': 'activate_form_template'})
        return json_response(form_template_manage.template_detail(template))


class FormTemplateGenerationConfigView(View):
    @auth(PERM_TPL_VIEW)
    def get(self, request, pk):
        template, error = _get_template_or_error(pk, request)
        if error:
            return error
        return json_response({
            'system': template.system_id,
            'generation_period': template.generation_period,
        })

    @auth(PERM_TPL_EDIT)
    def put(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        template, error = _get_template_or_error(pk, request)
        if error:
            return error
        try:
            form_template_manage.save_generation_config(request.user, template, body)
        except form_template_manage.FormTemplateError as e:
            return json_response(error=str(e))
        record_audit_event(request, 'update', AUDIT_TARGET_FORM_TEMPLATE, template.id,
                           template.name,
                           after_value={'action_kind': 'save_generation_config',
                                        'system': template.system_id,
                                        'generation_period': template.generation_period})
        return json_response(form_template_manage.template_detail(template))


class FormTemplatePublishView(View):
    """发布：草稿表单快照为不可变版本（发布级校验在服务层行锁内执行）。"""

    @auth(PERM_TPL_EDIT)
    def post(self, request, pk):
        template, error = _get_template_or_error(pk, request)
        if error:
            return error
        try:
            version = form_template_manage.publish_version(request.user, template)
        except form_template_manage.FormTemplateError as e:
            return json_response(error=str(e))
        record_audit_event(request, 'update', AUDIT_TARGET_FORM_TEMPLATE, template.id,
                           template.name,
                           after_value={'action_kind': 'publish_form_version',
                                        'version_no': version.version_no,
                                        'field_count': version.field_count})
        return json_response(version.to_view())


class FormTemplatePublishCheckView(View):
    """发布检查（无状态提示，2026-10-23 P2）：POST /form-templates/<pk>/publish-check/。

    请求体可携带 {form: {...}}（编辑器当前未保存内容——解决"非法未保存
    草稿无法先保存因此无法显示发布检查错误"的流程矛盾）；缺省时检查已
    保存草稿。返回 {errors, warnings}，每项 {code, message, anchor}，anchor
    与编辑器 selection 同构可点击定位。无状态：不写草稿、不创建版本、
    不产生任何"预检通过"标记——发布永远在行锁内重新执行全量校验。
    """

    @auth(PERM_TPL_EDIT)
    def post(self, request, pk):
        body = _read_json_body(request)
        if body is None:
            return json_response(error='请求体格式不正确')
        template, error = _get_template_or_error(pk, request)
        if error:
            return error
        form = body.get('form')
        if not isinstance(form, dict):
            if not template.draft_form:
                return json_response({
                    'errors': [{'code': 'no_draft',
                                'message': '请先编辑并保存表单草稿再发布',
                                'anchor': None}],
                    'warnings': []})
            try:
                form = json.loads(template.draft_form)
            except (ValueError, TypeError):
                form = None
            if not isinstance(form, dict):
                return json_response({
                    'errors': [{'code': 'draft_damaged',
                                'message': '草稿表单内容已损坏，请重新编辑保存后再发布',
                                'anchor': None}],
                    'warnings': []})
        return json_response(form_template_manage.collect_publish_issues(form))


class FormTemplateVersionListView(View):
    @auth(PERM_TPL_VIEW)
    def get(self, request, pk):
        template, error = _get_template_or_error(pk, request)
        if error:
            return error
        versions = template.versions.all().order_by('-version_no')
        return json_response({'data': [v.to_view() for v in versions]})


class FormTemplateVersionDetailView(View):
    @auth(PERM_TPL_VIEW)
    def get(self, request, pk, version_no):
        template, error = _get_template_or_error(pk, request)
        if error:
            return error
        version = template.versions.filter(version_no=version_no).first()
        if version is None:
            return json_response(error='版本不存在')
        return json_response(form_template_manage.version_content_view(version))


class FormTemplateAvailableView(View):
    """台账创建数据源：启用且有发布版本的数字表单模板（台账域权限）。"""

    @auth('equipment_lifecycle.ledger.view')
    def get(self, request):
        return json_response({'data': form_template_manage.available_templates(
            request.user, request.GET.get('ledger_type'))})


class FormTemplateSampleView(View):
    """内置示例表单（"载入示例"数据源，只读）。"""

    @auth(PERM_TPL_VIEW)
    def get(self, request):
        return json_response(form_template_manage.sample_form())


class FormTemplatePdfPreviewView(View):
    """模板样张 PDF 预览（当前草稿结构的空白样例，不要求先发布）。

    URL：POST /form-templates/<pk>/preview/pdf/（POST 语义：触发生成）。
    与数字表单台账 PDF（form_pdf_service.ledger_pdf）共用同一套版式渲染
    函数，保证样张与真实台账同版式；样张明确标注"模板样张"，不混入
    任何真实台账数据。幂等只读：不写草稿、不创建版本、不产生写库
    副作用；文件副作用仅限临时目录（自动清理）。响应为二进制 PDF
    （附件下发）并携带真实反馈头：X-El-Pdf-Pages（页数）、
    X-El-Pdf-Paper（如 "A4 210x297mm"，由生成的 PDF 读取）。
    """

    @_na
    @auth(PERM_TPL_VIEW)
    def post(self, request, pk):
        template, error = _get_template_or_error(pk, request)
        if error:
            return error
        try:
            content, info = form_pdf_service.template_sample_pdf(
                request.user, template)
        except (form_template_manage.FormTemplateError,
                form_pdf_service.FormPdfError) as e:
            return json_response(error=str(e))
        record_audit_event(
            request, 'export', AUDIT_TARGET_FORM_TEMPLATE, template.id,
            template.name,
            after_value={'action_kind': 'preview_form_template_pdf'})
        response = file_response(
            '%s-模板样张.pdf' % template.name, content, PDF_CONTENT_TYPE)
        if info.get('pages') is not None:
            response['X-El-Pdf-Pages'] = str(info['pages'])
        if info.get('paper'):
            response['X-El-Pdf-Paper'] = info['paper']
        return response

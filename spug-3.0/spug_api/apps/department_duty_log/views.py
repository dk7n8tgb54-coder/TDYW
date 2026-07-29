# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""部门值班日志 - HTTP 视图

方法级精确权限，每个方法使用单一权限装饰器。
可见性和所有权由后端 QuerySet 和状态检查保证。
"""
import logging
import os
import json
import uuid
from urllib.parse import quote

from django.conf import settings
from django.http import FileResponse, HttpResponse
from django.views.generic import View

from django.utils import timezone
from libs import JsonParser, Argument, json_response, auth
from apps.signature import services as signature_services
from libs.export_utils import build_export_error_response

from . import services
from .models import DepartmentDutyLog, STATUS_DRAFT, STATUS_SIGNED

logger = logging.getLogger(__name__)


class DepartmentDutyLogListCreateView(View):
    """GET 列表（服务端分页）/ POST 新建草稿"""

    @auth('department_duty_log.department_duty_log.view')
    def get(self, request):
        params, error = services.parse_list_params(request)
        if error:
            return json_response(error=error)

        qs = services.get_list_queryset(request.user, params)
        total = qs.count()

        page = params['page']
        page_size = params['page_size']
        offset = (page - 1) * page_size

        records = (
            qs.select_related('duty_person', 'signed_by')
            .order_by('-duty_date', '-id')[offset:offset + page_size]
        )
        items = [services.serialize_list_item(r, request.user) for r in records]

        return json_response({
            'records': items,
            'total': total,
            'page': page,
            'page_size': page_size,
        })

    @auth('department_duty_log.department_duty_log.add')
    def post(self, request):
        try:
            raw = json.loads(request.body) if request.body else {}
        except (ValueError, TypeError):
            return json_response(error='请求体格式不正确')

        form, error = services.validate_payload(raw, is_create=True)
        if error:
            return json_response(error=error)

        record, error = services.create_draft(request.user, form, request=request)
        if error:
            return json_response(error=error)

        return json_response(services.serialize_department_duty_log(record, request.user))


class DepartmentDutyLogDetailView(View):
    """GET 详情 / PUT 编辑本人草稿 / DELETE 软删除本人草稿"""

    @auth('department_duty_log.department_duty_log.view')
    def get(self, request, pk):
        qs = services.get_visible_department_duty_logs(request.user)
        record = qs.filter(pk=pk).first()
        if not record:
            return json_response(error='记录不存在')
        return json_response(services.serialize_department_duty_log(record, request.user))

    @auth('department_duty_log.department_duty_log.edit')
    def put(self, request, pk):
        try:
            raw = json.loads(request.body) if request.body else {}
        except (ValueError, TypeError):
            return json_response(error='请求体格式不正确')

        form, error = services.validate_payload(raw, is_create=False)
        if error:
            return json_response(error=error)

        record, error = services.update_draft(pk, request.user, form, request=request)
        if error:
            return json_response(error=error)

        return json_response(services.serialize_department_duty_log(record, request.user))

    @auth('department_duty_log.department_duty_log.del')
    def delete(self, request, pk):
        _, error = services.soft_delete_draft(pk, request.user, request=request)
        if error:
            return json_response(error=error)
        return json_response({'success': True})


class DepartmentDutyLogSignView(View):
    """POST 签署本人草稿"""

    @auth('department_duty_log.department_duty_log.sign')
    def post(self, request, pk):
        # 先检测原始 JSON 中的受保护字段
        try:
            raw = json.loads(request.body) if request.body else {}
        except (ValueError, TypeError):
            return json_response(error='请求体格式不正确')

        violations = services._detect_protected_fields(raw)
        if violations:
            logger.warning('[DepartmentDutyLog] sign protected fields rejected: %s', violations)
            return json_response(error=f'请求包含不允许提交的字段: {", ".join(sorted(violations))}')

        form, error = JsonParser(
            Argument('version', type=int, required=False, help='版本号'),
            Argument('confirm', type=bool, required=False, default=False, help='请确认签署'),
            Argument('request_id', required=False, help='请求 ID'),
        ).parse(request.body)
        if error:
            return json_response(error=error)

        # 客户端未传 request_id 时生成 UUID
        request_id = form.request_id
        if not request_id:
            request_id = uuid.uuid4().hex

        record, error = services.sign_draft(
            record_id=pk,
            user=request.user,
            client_version=form.version,
            request_id=request_id,
            confirm=form.confirm,
            request=request,
        )
        if error:
            return json_response(error=error)

        return json_response(services.serialize_department_duty_log(record, request.user))


class DepartmentDutyLogReturnView(View):
    """POST 退回已签记录到草稿"""

    @auth('department_duty_log.department_duty_log.return')
    def post(self, request, pk):
        record, error = services.return_signed_record(
            record_id=pk,
            user=request.user,
            request=request,
        )
        if error:
            return json_response(error=error)

        return json_response(services.serialize_department_duty_log(record, request.user))


class DepartmentDutyLogSignatureImageView(View):
    """GET 鉴权读取签署时固定版本签名图片

    先校验 view 权限和业务记录可见性，
    再传入 signature_usage_id 和业务对象坐标读取固定版本签名。
    """

    @auth('department_duty_log.department_duty_log.view')
    def get(self, request, pk):
        # 校验业务记录可见性
        qs = services.get_visible_department_duty_logs(request.user)
        record = qs.filter(pk=pk).first()
        if not record:
            return self._reject('记录不存在')

        if not record.signature_usage_id:
            return self._reject('该记录未签署')

        if record.status != STATUS_SIGNED:
            return self._reject('该记录未签署')

        # 调用受控全局业务签名读取
        info, error = signature_services.get_signature_image_for_global_business(
            usage_id=record.signature_usage_id,
            module=services.MODULE,
            object_type=services.OBJECT_TYPE,
            object_id=str(record.id),
            scene_code=services.SCENE_CODE,
        )
        if error:
            return self._reject(error)

        try:
            response = FileResponse(open(info['file_path'], 'rb'), content_type='image/png')
        except OSError:
            return self._reject('签名文件读取失败')

        response['Content-Disposition'] = 'inline; filename="signature.png"'
        response['Content-Length'] = info['file_size']
        response['X-Content-Type-Options'] = 'nosniff'
        response['Cache-Control'] = 'private, no-store, max-age=0'
        return response

    @staticmethod
    def _reject(message):
        response = HttpResponse(message, content_type='text/plain; charset=utf-8', status=403)
        response['X-Content-Type-Options'] = 'nosniff'
        return response


class DepartmentDutyLogOptionsView(View):
    """GET 选项接口"""

    @auth('department_duty_log.department_duty_log.view')
    def get(self, request):
        data = services.get_options(request.user)
        return json_response(data)


class DepartmentDutyLogDutyDatesView(View):
    """GET 已有值班日志日期列表

    返回当前用户可见的某月内已有值班日志的 duty_date 列表（YYYY-MM-DD）。
    供前端日期选择器在面板上标记"已有值班日志"的日期，避免重复登记。

    查询参数：
        year:  必填，4 位整数，如 2026
        month: 必填，1-12 整数，如 7
    """

    @auth('department_duty_log.department_duty_log.view')
    def get(self, request):
        form, error = JsonParser(
            Argument('year', type=int, help='请提供 year'),
            Argument('month', type=int, help='请提供 month'),
        ).parse(request.GET)
        if error:
            return json_response(error=error)

        if not (1 <= form.month <= 12):
            return json_response(error='month 必须在 1-12 之间')

        if not (1900 <= form.year <= 9999):
            return json_response(error='year 取值范围 1900-9999')

        dates = services.list_duty_dates(request.user, form.year, form.month)
        return json_response({'dates': dates})


class DepartmentDutyLogPdfExportView(View):
    """POST 导出已签部门值班日志 PDF

    请求体只接受筛选条件，不接受记录内容、签名内容、文件路径或客户端生成的 PDF 数据。
    只导出 view 可见的已签记录，永不导出草稿。
    """

    @auth('department_duty_log.department_duty_log.export')
    def post(self, request):
        try:
            raw = json.loads(request.body) if request.body else {}
        except (ValueError, TypeError):
            return build_export_error_response('请求体格式不正确')

        pdf_bytes, filename, error = services.export_pdf(request.user, raw, request=request)
        if error:
            return build_export_error_response(error)

        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        # 中文文件名使用 RFC 5987 编码，兼容主流浏览器
        response['Content-Disposition'] = "attachment; filename*=UTF-8''%s" % quote(filename)
        response['Content-Length'] = len(pdf_bytes)
        response['X-Content-Type-Options'] = 'nosniff'
        return response

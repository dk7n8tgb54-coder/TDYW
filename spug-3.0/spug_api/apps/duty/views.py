# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under AGPL-3.0 License.
from django.views.generic import View
from django.http import HttpResponse
from libs import json_response, JsonParser, Argument, human_datetime, auth
from libs.tenant_utils import apply_tenant_filter, assign_tenant_id
from apps.logs.audit import record_audit_event
from apps.duty.models import DutyRecord
import json
import logging

logger = logging.getLogger(__name__)


def tenant_operation_check(request, model, record_id, operation='操作'):
    """
    租户操作检查通用函数
    验证记录是否存在且属于当前租户

    参数：
        request: 请求对象
        model: 数据模型类
        record_id: 记录ID
        operation: 操作名称（用于日志）

    返回：
        (queryset, None) - 检查通过，返回过滤后的queryset
        (None, error_response) - 检查失败，返回错误响应

    租户过滤规则（30人内网团队核心场景）：
    1. 通过PK直接操作记录 → 必须加租户过滤（无上下文，易跨租户）
    2. 基于已过滤的record查关联表 → 不加（record已限定租户）
    3. 批量操作ID列表 → 验证"过滤后数量=原数量"（避免混有跨租户ID）
    4. 所有过滤失败场景 → 统一返回"记录不存在或无权操作"
    """
    queryset = apply_tenant_filter(model.objects.filter(pk=record_id), request.user)
    if not queryset.exists():
        logger.warning(
            f'用户{request.user.username}尝试{operation}跨租户/不存在的{model.__name__}记录{record_id} | '
            f'IP：{request.META.get("REMOTE_ADDR")} | 时间：{human_datetime()}'
        )
        return None, json_response(error='记录不存在或无权操作')
    return queryset, None


class DutyImportView(View):
    """值班日志引入数据 - 聚合运行日志、干扰记录

    按《模块间调用规范方案.md》：跨模块数据统一通过各模块 services.py 获取，
    视图层不直接 import 其他业务模块的 models。运行日志已迁移至
    ``apps.runlog.services.get_duty_import_items``，由本模块的
    ``apps.duty.import_services.get_import_records`` 负责聚合。
    """
    @auth('duty.duty.view')
    def get(self, request):
        from datetime import datetime
        from apps.duty.import_services import get_import_records

        date_str = request.GET.get('date')
        target_date = date_str if date_str else datetime.now().strftime('%Y-%m-%d')

        return json_response(get_import_records(target_date, request.user))


class DutyRecordView(View):
    @auth('duty.duty.view')
    def get(self, request):
        records = apply_tenant_filter(DutyRecord.objects.all(), request.user)
        duty_persons = [x['duty_person'] for x in records.order_by('duty_person').values('duty_person').distinct()]
        departments = [x['department'] for x in records.order_by('department').values('department').distinct()]
        return json_response({
            'duty_persons': duty_persons,
            'departments': departments,
            'records': [x.to_view() for x in records]
        })

    @auth('duty.duty.add|duty.duty.edit|duty.duty.del')
    def post(self, request):
        try:
            req_data = json.loads(request.body)
        except:
            req_data = {}

        # 先判断是否是删除操作
        if req_data.get('action') == 'delete':
            # 统一接口二次校验：删除分支必须单独拥有 del 权限
            if not request.user.has_perms({'duty.duty.del'}):
                return json_response(error='权限拒绝：缺少删除值班记录权限')
            form, error = JsonParser(
                Argument('id', type=int, help='请提供记录ID')
            ).parse(request.body)
            if error is None:
                queryset, error_resp = tenant_operation_check(request, DutyRecord, form.id, '删除')
                if error_resp:
                    return error_resp
                queryset.delete()
            return json_response(error=error)

        form, error = JsonParser(
            Argument('id', type=int, required=False),
            Argument('duty_person', help='请输入值班人员'),
            Argument('reporter', required=False),
            Argument('department', help='请输入所属科室'),
            Argument('duty_date', help='请选择值班日期'),
            Argument('duty_situation', required=False),
        ).parse(request.body)
        if error is None:
            if form.id:
                # 统一接口二次校验：编辑分支必须单独拥有 edit 权限
                if not request.user.has_perms({'duty.duty.edit'}):
                    return json_response(error='权限拒绝：缺少编辑值班记录权限')
                queryset = apply_tenant_filter(DutyRecord.objects.filter(pk=form.id), request.user)
                if not queryset.exists():
                    return json_response(error='记录不存在或无权操作')
                queryset.update(
                    duty_person=form.duty_person,
                    department=form.department,
                    duty_date=form.duty_date,
                    duty_situation=form.duty_situation,
                    updated_at=human_datetime()
                )
            else:
                # 统一接口二次校验：新增分支必须单独拥有 add 权限
                if not request.user.has_perms({'duty.duty.add'}):
                    return json_response(error='权限拒绝：缺少新增值班记录权限')
                form.reporter = request.user.nickname
                form.created_by = request.user
                assign_tenant_id(form, request.user)
                DutyRecord.objects.create(**form)
        return json_response(error=error)

    @auth('duty.duty.del')
    def delete(self, request):
        form, error = JsonParser(Argument('id', type=int, help='请提供记录ID')).parse(request.GET)
        if error is None:
            queryset, error_resp = tenant_operation_check(request, DutyRecord, form.id, '删除')
            if error_resp:
                return error_resp
            queryset.delete()
        return json_response(error=error)


@auth('duty.duty.view')
def export_pdf(request):
    """导出值班日志PDF - 支持GET和POST"""
    try:
        # 获取租户过滤后的记录
        records = apply_tenant_filter(DutyRecord.objects.all(), request.user)

        # 日期范围过滤 - 兼容GET和POST
        if request.method == 'POST':
            try:
                body = json.loads(request.body) if request.body else {}
            except Exception:
                body = {}
            start_date = body.get('start_date')
            end_date = body.get('end_date')
        else:
            start_date = request.GET.get('start_date')
            end_date = request.GET.get('end_date')

        date_range_text = ''
        filters = {
            'start_date': start_date,
            'end_date': end_date,
        }

        if start_date and end_date:
            records = records.filter(duty_date__gte=start_date, duty_date__lte=end_date)
            date_range_text = f'{start_date}-{end_date}'
        elif start_date:
            records = records.filter(duty_date__gte=start_date)
            date_range_text = f'{start_date}起'
        elif end_date:
            records = records.filter(duty_date__lte=end_date)
            date_range_text = f'至{end_date}'

        records = records.order_by('-duty_date', '-id')
        data = [r.to_view() for r in records]

        if not data:
            if request.method == 'POST':
                record_audit_event(
                    request=request,
                    action='export',
                    target_type='duty',
                    target_name='Duty PDF export',
                    detail={'format': 'pdf', 'filters': filters, 'count': 0},
                    error='no exportable data',
                )
            return json_response(error='没有可导出的数据')

        # 生成PDF
        from .pdf_export import generate_duty_log_pdf
        pdf_output = generate_duty_log_pdf(data, date_range_text)

        # 构建文件名
        from datetime import datetime
        now = datetime.now().strftime('%Y%m%d_%H%M%S')
        if date_range_text:
            filename = f'值班日志_{date_range_text}_{now}.pdf'
        else:
            filename = f'值班日志_全部_{now}.pdf'

        response = HttpResponse(pdf_output.read(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        if request.method == 'POST':
            record_audit_event(
                request=request,
                action='export',
                target_type='duty',
                target_name='Duty PDF export',
                detail={'format': 'pdf', 'filters': filters, 'count': len(data)},
            )
        return response

    except Exception as e:
        if request.method == 'POST':
            record_audit_event(
                request=request,
                action='export',
                target_type='duty',
                target_name='Duty PDF export',
                detail={'format': 'pdf', 'filters': locals().get('filters', {})},
                error=f'{type(e).__name__}: {str(e)[:80]}',
            )
        logger.error(f'导出值班日志PDF失败：{e}', exc_info=True)
        return json_response(error='导出PDF失败，请重试')

# Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.http import JsonResponse, HttpResponse
from django.db import transaction, IntegrityError
from django.views import View
from libs import json_response, JsonParser, Argument
from libs.decorators import auth
from libs.utils import human_datetime, get_request_real_ip
from .models import (
    CheckSheetTemplate, CheckSheetRecord, CheckSheetDailySummary,
    CheckSheetSubmission, SUBMISSION_TRANSITIONS, SUBMISSION_STATUS_CHOICES,
)
from apps.evidence.services import record_evidence_event
from apps.evidence.models import EvidenceEvent, EvidenceAttachment
from apps.logs.models import AuditLog
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, PageBreak, Spacer

# 配置ReportLab处理中文字符
import reportlab.rl_config
reportlab.rl_config.TTFSearchPath.append('/data/spug/spug_api/apps/checksheet/fonts')

from io import BytesIO
import json
import logging

logger = logging.getLogger(__name__)


# P2-7 复杂度优化：提取记录校验逻辑为独立函数，降低 RecordListView.post 圈复杂度
def _validate_records_input(records):
    """校验 records 参数，返回 None（通过）或错误消息字符串（失败）"""
    VALID_STATUSES = {'NORMAL', 'ABNORMAL', 'UNCHECKED'}
    if not isinstance(records, list):
        return 'records 必须是列表'
    if len(records) > 500:
        return '单次提交记录数不能超过500条'
    for idx, record_data in enumerate(records):
        if not isinstance(record_data, dict):
            return f'第 {idx + 1} 条记录格式错误'
        status = record_data.get('status')
        if status and status not in VALID_STATUSES:
            return f'第 {idx + 1} 条记录状态无效: {status}'
        item_index = record_data.get('item_index')
        if not isinstance(item_index, int) or item_index < 0:
            return f'第 {idx + 1} 条记录 item_index 无效'
        rec_day = record_data.get('day')
        if not isinstance(rec_day, int) or rec_day < 1 or rec_day > 31:
            return f'第 {idx + 1} 条记录 day 无效: {rec_day}'
    return None


def _parse_int(value, name, min_value=None, max_value=None):
    """P1-2 修复：通用整数参数解析与校验，返回 (result, error)。

    非法输入返回 (None, 'xxx 必须是整数')，通过校验返回 (int, None)。
    """
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None, f'{name} 必须是整数'
    if min_value is not None and result < min_value:
        return None, f'{name} 不能小于 {min_value}'
    if max_value is not None and result > max_value:
        return None, f'{name} 不能大于 {max_value}'
    return result, None


class RecordListView(View):
    """检查记录视图 - 处理查询和创建"""

    @auth('checksheet.checksheet.view')
    def get(self, request):
        """获取检查记录"""
        year = request.GET.get('year')
        month = request.GET.get('month')
        day = request.GET.get('day')
        project = request.GET.get('project')

        if not all([year, month, project]):
            return JsonResponse({'error': '缺少必要参数'}, status=400)

        # P1-2 修复：day 参数类型与范围校验，非法输入返回友好错误而非 500
        day_value = None
        if day:
            day_value, error = _parse_int(day, 'day', min_value=1, max_value=31)
            if error:
                return json_response(error=error)

        try:
            template = CheckSheetTemplate.objects.get(project=project)

            # 获取指定日期的检查记录
            day_filter = {}
            if day_value is not None:
                day_filter['day'] = day_value

            records = CheckSheetRecord.objects.filter(
                template=template,
                year=year,
                month=month,
                **day_filter
            ).order_by('day', 'item_index')

            records_data = []
            for r in records:
                records_data.append({
                    'id': r.id,
                    'item_index': r.item_index,
                    'day': r.day,
                    'status': r.status,
                    # P1-1 修复：返回实际的 remark/rectification 数据（原代码硬编码为空字符串）
                    'remark': r.remark or '',
                    'rectification': r.rectification or ''
                })

            # 获取每日汇总（包含 operator、remark 和 rectification）
            summary_filter = {}
            if day_value is not None:
                summary_filter['day'] = day_value

            daily_summaries = {}
            for summary in CheckSheetDailySummary.objects.filter(
                year=year,
                month=month,
                **summary_filter
            ):
                daily_summaries[summary.day] = {
                    'operator': summary.operator or '',
                    'remark': summary.remark or '',
                    'rectification': summary.rectification or ''
                }

            return json_response({
                'template': {
                    'id': template.id,
                    'project': template.project,
                    'check_items': template.get_check_items()
                },
                'records': records_data,
                'daily_summaries': daily_summaries
            })
        except CheckSheetTemplate.DoesNotExist:
            return JsonResponse({'error': '模板不存在'}, status=400)

    @auth('checksheet.checksheet.edit')
    def post(self, request):
        """保存检查记录"""
        try:
            form, error = JsonParser(
                Argument('year', help='请输入年份'),
                Argument('month', help='请输入月份'),
                Argument('project', help='请输入项目名称'),
                Argument('day', help='请输入日期'),
                Argument('records', type=list, default=[]),
                Argument('signatures', type=dict, default={}),
                Argument('daily_summary', type=dict, default={})
            ).parse(request.body)
        except Exception as e:
            logger.error(f'CheckSheet RecordListView post JsonParser error: {e}')
            return json_response(error=str(e))

        if error:
            logger.warning(f'CheckSheet RecordListView post parse error: {error}')
            return json_response(error=error)

        year = form.year
        month = form.month
        day = form.day
        project = form.project
        records = form.records
        signatures = form.signatures
        daily_summary = form.daily_summary

        # P1-3 修复 & P2-7 复杂度优化：提取校验逻辑为独立函数
        validate_error = _validate_records_input(records)
        if validate_error:
            return json_response(error=validate_error)

        try:
            with transaction.atomic():
                # 获取或创建模板
                template, _ = CheckSheetTemplate.objects.get_or_create(
                    project=project,
                    defaults={'check_items': '[]'}
                )

                # 证据闭环：获取或创建提交批次（状态流转功能已暂停，不再阻止保存）
                tenant_id = getattr(request.user, 'tenant_id', 'default')
                submission = CheckSheetSubmission.objects.filter(
                    tenant_id=tenant_id, project=project, year=year, month=month,
                    status__in=['draft', 'submitted', 'reviewed', 'closed'],
                ).order_by('-id').first()

                # 无批次则自动创建 draft 批次
                if not submission:
                    submission = CheckSheetSubmission.objects.create(
                        tenant_id=tenant_id, project=project, year=year, month=month,
                        status='draft',
                    )

                # 操作人身份快照
                user = request.user
                operator_user_id = getattr(user, 'id', None)
                operator_name = getattr(user, 'nickname', '') or getattr(user, 'username', '')

                # 保存检查记录（绑定 user_id）
                for record_data in records:
                    item_index = record_data.get('item_index')
                    day = record_data.get('day')
                    status = record_data.get('status', 'UNCHECKED')

                    # P1-2 修复：保存时保留原有 remark/rectification
                    existing = CheckSheetRecord.objects.filter(
                        template=template, year=year, month=month,
                        item_index=item_index, day=day
                    ).first()
                    existing_remark = existing.remark if existing else ''
                    existing_rectification = existing.rectification if existing else ''

                    CheckSheetRecord.objects.update_or_create(
                        template=template,
                        year=year,
                        month=month,
                        item_index=item_index,
                        day=day,
                        defaults={
                            'status': status,
                            'remark': existing_remark,
                            'rectification': existing_rectification,
                            'operator': signatures.get('operator', ''),
                            'operator_user_id': operator_user_id,
                            'operator_name_snapshot': operator_name,
                        }
                    )

                # 保存每日汇总（包含 operator、remark 和 rectification）
                if daily_summary and day:
                    CheckSheetDailySummary.objects.update_or_create(
                        year=year,
                        month=month,
                        day=int(day),
                        defaults={
                            'operator': signatures.get('operator', ''),
                            'remark': daily_summary.get('remark', ''),
                            'rectification': daily_summary.get('rectification', ''),
                            'operator_user_id': operator_user_id,
                            'operator_name_snapshot': operator_name,
                        }
                    )

                submission.updated_at = human_datetime()
                submission.save(update_fields=['updated_at'])

            logger.info(f'CheckSheet saved: year={year}, month={month}, day={day}, project={project}, records_count={len(records)}')
            return json_response({'msg': '保存成功'})
        except Exception as e:
            logger.error(f'CheckSheet RecordListView post error: {e}', exc_info=True)
            return JsonResponse({'error': str(e)}, status=500)


class ProjectListView(View):
    """返回所有检查表模板的项目名称列表（不分页）。

    P0-2 修复：TemplateView.get 默认分页 50 条，导致前端 store.projects 派生时
    只能拿到前 50 个项目，第 51 个之后的项目在录入/数据查看/PDF 导出/项目筛选
    下拉框中都会缺失。本接口专门返回完整项目名列表，供前端 store.projects 使用。
    """

    @auth('checksheet.checksheet.view')
    def get(self, request):
        projects = list(
            CheckSheetTemplate.objects
            .order_by('created_at')
            .values_list('project', flat=True)
        )
        return json_response({'projects': projects})


class TemplateView(View):
    """检查表模板视图 - 处理列表查询和创建"""

    @auth('checksheet.checksheet.template_view')
    def get(self, request):
        """获取检查表模板列表（全量）"""
        # P2 修复：模板数量可控，移除分页返回全量数据。
        # 原分页（默认 page_size=50）导致前端只能拿到前 50 条，
        # 而前端 fetchTemplates 未做服务端分页，表格只能在这 50 条内翻页，
        # 第 51 条及以后的模板完全不可见。与 ProjectListView 保持一致，返回全量。
        templates = CheckSheetTemplate.objects.all().order_by('created_at')

        data = []
        for t in templates:
            data.append({
                'id': t.id,
                'project': t.project,
                'check_items': t.get_check_items(),
                'created_at': t.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'updated_at': t.updated_at.strftime('%Y-%m-%d %H:%M:%S')
            })
        logger.info(f'[CheckSheet] TemplateView.get returning {len(data)} templates')
        return json_response({'templates': data})

    @auth('checksheet.checksheet.template_add')
    def post(self, request):
        """创建检查表模板"""
        # P2-1 修复：删除方法内重复的 logging 导入，直接使用模块级 logger
        logger.info(f'[CheckSheet] TemplateView.post request.body: {request.body}')

        form, error = JsonParser(
            Argument('project', help='请输入项目名称'),
            Argument('check_items', type=list, default=[])
        ).parse(request.body)

        if error:
            logger.error(f'[CheckSheet] TemplateView.post parse error: {error}')
            return json_response(error=error)

        # P0-3 修复：创建前校验项目名唯一，避免 IntegrityError 或同名模板导致后续查询 500
        if CheckSheetTemplate.objects.filter(project=form.project).exists():
            return json_response(error='项目模板已存在')

        logger.info(f'[CheckSheet] Creating template: project={form.project}, items_count={len(form.check_items)}')

        try:
            template = CheckSheetTemplate.objects.create(
                project=form.project,
                check_items=json.dumps(form.check_items, ensure_ascii=False)
            )
        except IntegrityError:
            # 并发场景下的兜底（校验与创建之间存在竞态）
            return json_response(error='项目模板已存在')

        logger.info(f'[CheckSheet] Template created with id={template.id}')
        return json_response({'id': template.id})


class TemplateDetailView(View):
    """检查表模板详情视图 - 处理详情、更新、删除"""

    @auth('checksheet.checksheet.template_view')
    def get(self, request, pk):
        """获取检查表模板详情"""
        try:
            template = CheckSheetTemplate.objects.get(pk=pk)
            return json_response({
                'id': template.id,
                'project': template.project,
                'check_items': template.get_check_items(),
                'created_at': template.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'updated_at': template.updated_at.strftime('%Y-%m-%d %H:%M:%S')
            })
        except CheckSheetTemplate.DoesNotExist:
            return JsonResponse({'error': '模板不存在'}, status=404)

    @auth('checksheet.checksheet.template_edit')
    def put(self, request, pk):
        """更新检查表模板"""
        try:
            template = CheckSheetTemplate.objects.get(pk=pk)
            form, error = JsonParser(
                Argument('project', required=False),
                Argument('check_items', type=list, required=False)
            ).parse(request.body)
            if error:
                return json_response(error=error)
            # P0-3 修复：改名时校验项目名唯一（排除自身）
            if form.project and form.project != template.project:
                if CheckSheetTemplate.objects.filter(project=form.project).exists():
                    return json_response(error='项目模板已存在')
            if form.project:
                template.project = form.project
            if form.check_items is not None:
                template.set_check_items(form.check_items)
            try:
                template.save()
            except IntegrityError:
                # 并发场景兜底
                return json_response(error='项目模板已存在')
            return json_response({'id': template.id})
        except CheckSheetTemplate.DoesNotExist:
            return JsonResponse({'error': '模板不存在'}, status=404)

    @auth('checksheet.checksheet.template_del')
    def delete(self, request, pk):
        """删除检查表模板"""
        try:
            template = CheckSheetTemplate.objects.get(pk=pk)
            template.delete()
            return json_response({'msg': '删除成功'})
        except CheckSheetTemplate.DoesNotExist:
            return JsonResponse({'error': '模板不存在'}, status=404)


@auth('checksheet.checksheet.edit')  # P0-2 修复：导出操作使用 edit 权限（而非 view）
def export_pdf(request):
    """导出PDF - 使用前端发送的表格数据，保证PDF与前端显示一致"""
    logger.info(f'CheckSheet export_pdf: method={request.method}, user={request.user}')

    try:
        # 解析请求参数
        params = _parse_pdf_request(request)
        if 'error' in params:
            return JsonResponse({'error': params['error']}, status=400)

        # P0-2 修复：验证 table_data 内容，防止恶意构造假PDF
        if params.get('use_table_data'):
            table_data = params.get('table_data', [])
            if not isinstance(table_data, list) or len(table_data) > 500:
                return JsonResponse({'error': '表格数据行数必须在1-500之间'}, status=400)
            if len(table_data) > 0:
                for row_idx, row in enumerate(table_data):
                    if not isinstance(row, list):
                        return JsonResponse({'error': f'第 {row_idx + 1} 行数据格式错误'}, status=400)
                    for col_idx, cell in enumerate(row):
                        cell_str = str(cell) if cell is not None else ''
                        if len(cell_str) > 500:
                            return JsonResponse(
                                {'error': f'单元格数据过长（行{row_idx + 1}，列{col_idx + 1}）'},
                                status=400
                            )

        # 注册中文字体
        from .font_manager import FontManager
        font_registered = FontManager.register_chinese_font()

        # 根据请求类型生成PDF
        if params.get('use_table_data'):
            logger.info(f'CheckSheet export_pdf: generating PDF with table_data, {len(params["table_data"])} rows')
            return _generate_pdf_from_table_data(
                params['year'], params['month'], params['title'],
                params['table_data'], params['daily_summaries'], font_registered
            )

        # 否则使用旧逻辑（从数据库读取）
        logger.info(f'CheckSheet export_pdf: generating PDF from database, projects={params.get("project_list")}')
        return _generate_pdf_from_database(
            params['year'], params['month'], params['project_list'], font_registered
        )

    except Exception as e:
        logger.error(f'CheckSheet export_pdf error: {e}', exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


def _parse_pdf_request(request):
    """解析PDF导出请求参数"""
    result = {'title': '检查表'}

    if request.method == 'POST':
        try:
            import json
            data = json.loads(request.body)
            result.update({
                'year': str(data.get('year')),
                'month': str(data.get('month')).zfill(2),
                'table_data': data.get('table_data', []),
                'daily_summaries': data.get('daily_summaries', {}),
                'title': data.get('title', '检查表'),
                'use_table_data': bool(data.get('table_data'))
            })
        except Exception as e:
            return {'error': '数据解析失败'}
    else:
        # GET请求：兼容旧接口
        year = request.GET.get('year')
        month = request.GET.get('month')
        projects = request.GET.get('project', '')

        if not all([year, month, projects]):
            return {'error': '缺少必要参数'}

        result.update({
            'year': str(year),
            'month': str(month).zfill(2),
            'project_list': projects.split(',') if projects else [],
            'use_table_data': False
        })

    return result


def _generate_pdf_from_table_data(year, month, title, table_data, daily_summaries, font_registered):
    """使用前端发送的表格数据生成PDF（与前端显示完全一致）"""
    from . import pdf_utils
    logger.info(f'CheckSheet PDF generation: {len(table_data)} rows, {len(daily_summaries)} daily summaries')

    try:
        # 创建文档
        doc, output = pdf_utils.create_pdf_document()
        elements = []
        actual_font = 'SimHei' if font_registered else 'Helvetica'

        # 转换表格数据
        table_data_str = pdf_utils.convert_table_data_to_strings(table_data)

        # 转换为Paragraph并计算列宽
        paragraph_table_data = pdf_utils.convert_to_paragraphs(table_data_str, actual_font)
        col_widths = pdf_utils.calculate_column_widths(table_data_str)

        # 创建主表格
        table = pdf_utils.create_main_table(paragraph_table_data, col_widths, table_data_str)

        # 添加标题和主表格
        elements.append(pdf_utils.create_title_paragraph(title, actual_font))
        elements.append(table)

        # 添加汇总信息表格
        if daily_summaries:
            elements.append(Spacer(1, 0.5 * cm))

            days = pdf_utils.extract_days_from_headers(table_data_str)
            summary_row_data = pdf_utils.build_summary_data(daily_summaries, days)
            summary_para_data = pdf_utils.convert_summary_to_paragraphs(summary_row_data, actual_font)
            summary_table = pdf_utils.create_summary_table(summary_para_data, col_widths)
            elements.append(summary_table)

        # 生成PDF
        doc.build(elements)
        output.seek(0)

        pdf_bytes = output.getvalue()
        logger.info(f'CheckSheet PDF generated: {len(pdf_bytes)} bytes')

        # 创建PDF响应
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{title}.pdf"'
        return response

    except Exception as e:
        logger.error(f'CheckSheet PDF generation error: {e}', exc_info=True)
        raise


def _generate_pdf_from_database(year, month, project_list, font_registered):
    """从数据库读取数据生成PDF（旧逻辑，保持兼容）"""
    from .pdf_table_builder import PDFTableBuilder

    output = BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=landscape(A4),
        rightMargin=1*cm,
        leftMargin=1*cm,
        topMargin=1*cm,
        bottomMargin=1*cm
    )

    elements = []

    for project in project_list:
        try:
            template = CheckSheetTemplate.objects.get(project=project)
            check_items = template.get_check_items()

            # 获取检查记录和每日汇总
            records = _fetch_check_records(template, year, month)
            daily_summaries = _fetch_daily_summaries(year, month)

            # 使用表格构建器创建表格
            table = PDFTableBuilder.build_project_table(
                project, year, month, check_items, records, daily_summaries
            )
            elements.append(table)

            # 项目间添加分页符（除了最后一个项目）
            if project != project_list[-1]:
                elements.append(PageBreak())

        except CheckSheetTemplate.DoesNotExist:
            continue

    # 生成PDF
    if not elements:
        return JsonResponse({'error': '没有找到有效的模板数据，请检查项目名称是否正确'}, status=404)

    doc.build(elements)
    output.seek(0)

    response = HttpResponse(
        output.getvalue(),
        content_type='application/pdf'
    )
    response['Content-Disposition'] = f'attachment; filename="{year}年{month}月_检查表.pdf"'
    return response


def _fetch_check_records(template, year, month):
    """获取检查记录"""
    return {
        f"{r.item_index}_{r.day}": r
        for r in CheckSheetRecord.objects.filter(template=template, year=year, month=month)
    }


def _fetch_daily_summaries(year, month):
    """获取每日汇总数据"""
    return {
        summary.day: {
            'operator': summary.operator or '',
            'remark': summary.remark or '',
            'rectification': summary.rectification or ''
        }
        for summary in CheckSheetDailySummary.objects.filter(year=year, month=month)
    }


# ==================== 证据闭环第三阶段：提交批次 + 证据包 ====================

def _build_submission_snapshot(submission):
    """构建提交批次业务快照（用于证据事件 + 证据包）"""
    template = CheckSheetTemplate.objects.filter(project=submission.project).first()
    records = CheckSheetRecord.objects.filter(
        template=template, year=submission.year, month=submission.month
    ).order_by('day', 'item_index') if template else []
    summaries = CheckSheetDailySummary.objects.filter(
        year=submission.year, month=submission.month
    ).order_by('day')
    return {
        'submission': {
            'id': submission.id,
            'project': submission.project,
            'year': submission.year,
            'month': submission.month,
            'status': submission.status,
            'submitted_by_id': submission.submitted_by_id,
            'submitted_by_name': submission.submitted_by_name,
            'submitted_at': submission.submitted_at,
            'reviewed_by_id': submission.reviewed_by_id,
            'reviewed_by_name': submission.reviewed_by_name,
            'reviewed_at': submission.reviewed_at,
            'snapshot_hash': submission.snapshot_hash,
        },
        'check_items': template.get_check_items() if template else [],
        'records': [
            {
                'item_index': r.item_index, 'day': r.day, 'status': r.status,
                'remark': r.remark or '', 'rectification': r.rectification or '',
                'operator_user_id': r.operator_user_id,
                'operator_name_snapshot': r.operator_name_snapshot,
            }
            for r in records
        ],
        'daily_summaries': [
            {
                'day': s.day, 'operator': s.operator or '',
                'remark': s.remark or '', 'rectification': s.rectification or '',
                'operator_user_id': s.operator_user_id,
                'operator_name_snapshot': s.operator_name_snapshot,
            }
            for s in summaries
        ],
    }


def _compute_snapshot_hash(snapshot):
    """计算提交批次快照哈希"""
    import hashlib
    import json as _json
    payload = _json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _get_attachment_hashes(tenant_id, submission_id):
    """获取提交批次关联附件哈希清单"""
    atts = EvidenceAttachment.objects.filter(
        tenant_id=tenant_id, module='checksheet',
        object_type='submission', object_id=str(submission_id),
        is_deleted=False,
    )
    return [
        {
            'file_name': a.file_name, 'file_path': a.file_path,
            'sha256': a.file_hash_sha256, 'size': a.file_size,
            'uploaded_by_id': a.uploaded_by_id,
            'uploaded_by_name': a.uploaded_by_name,
            'uploaded_at': a.uploaded_at,
        }
        for a in atts
    ]


def _record_checksheet_evidence(submission, event_type, user, remark=''):
    """写入检查单证据事件（封装 record_evidence_event 调用）"""
    tenant_id = getattr(user, 'tenant_id', 'default')
    snapshot = _build_submission_snapshot(submission)
    att_hashes = _get_attachment_hashes(tenant_id, submission.id)
    actor_name = getattr(user, 'nickname', '') or getattr(user, 'username', '')
    record_evidence_event(
        tenant_id=tenant_id,
        module='checksheet',
        object_type='submission',
        object_id=submission.id,
        event_type=event_type,
        actor_user_id=getattr(user, 'id', None),
        actor_username=getattr(user, 'username', ''),
        actor_name=actor_name,
        actor_ip=get_request_real_ip(user) if hasattr(user, 'headers') else '',
        object_snapshot=snapshot,
        attachment_hashes=att_hashes,
        event_title=f'{submission.project} {submission.year}-{submission.month} {event_type}',
        remark=remark,
    )


# action → 新状态映射（供 SubmissionView.post 使用）
_SUBMISSION_ACTION_STATUS = {
    'submit': 'submitted', 'review': 'reviewed',
    'reject': 'draft', 'close': 'closed', 'void': 'voided',
}
# action → 证据事件类型映射
_SUBMISSION_EVENT_TYPE = {
    'submit': 'submit', 'review': 'approve',
    'reject': 'reject', 'close': 'close', 'void': 'void',
}


def _apply_submission_action(sub, action, new_status, user, form):
    """根据 action 更新提交批次的专属字段并完成状态流转

    从 SubmissionView.post 抽取，降低主函数圈复杂度。
    """
    actor_name = getattr(user, 'nickname', '') or getattr(user, 'username', '')
    now = human_datetime()

    if action == 'submit':
        sub.submitted_by_id = getattr(user, 'id', None)
        sub.submitted_by_name = actor_name
        sub.submitted_at = now
        snapshot = _build_submission_snapshot(sub)
        sub.snapshot_hash = _compute_snapshot_hash(snapshot)
    elif action == 'review':
        sub.reviewed_by_id = getattr(user, 'id', None)
        sub.reviewed_by_name = actor_name
        sub.reviewed_at = now
        sub.review_comment = form.review_comment or ''
    elif action == 'reject':
        sub.review_comment = form.review_comment or ''
    elif action == 'void':
        sub.voided_by_id = getattr(user, 'id', None)
        sub.voided_by_name = actor_name
        sub.voided_at = now
        sub.void_reason = form.void_reason or ''
    # close 无专属字段，仅状态流转

    sub.status = new_status
    sub.updated_at = now
    sub.save()


class SubmissionView(View):
    """检查单提交批次视图 - 查询/提交/复核/驳回/关闭/作废"""

    @auth('checksheet.checksheet.view')
    def get(self, request):
        """查询提交批次状态"""
        project = request.GET.get('project')
        year = request.GET.get('year')
        month = request.GET.get('month')
        if not all([project, year, month]):
            return json_response(error='缺少 project/year/month 参数')
        tenant_id = getattr(request.user, 'tenant_id', 'default')
        sub = CheckSheetSubmission.objects.filter(
            tenant_id=tenant_id, project=project, year=year, month=month,
        ).order_by('-id').first()
        if not sub:
            return json_response({'exists': False, 'status': 'draft'})
        return json_response({
            'exists': True, 'id': sub.id, 'status': sub.status,
            'submitted_by_id': sub.submitted_by_id,
            'submitted_by_name': sub.submitted_by_name,
            'submitted_at': sub.submitted_at,
            'reviewed_by_id': sub.reviewed_by_id,
            'reviewed_by_name': sub.reviewed_by_name,
            'reviewed_at': sub.reviewed_at,
            'review_comment': sub.review_comment,
            'snapshot_hash': sub.snapshot_hash,
            'can_edit': sub.can_edit(),
        })

    @auth('checksheet.checksheet.edit')
    def post(self, request):
        """提交/复核/驳回/关闭/作废（通过 action 参数区分）"""
        form, error = JsonParser(
            Argument('project', help='请输入项目名称'),
            Argument('year', help='请输入年份'),
            Argument('month', help='请输入月份'),
            Argument('action', help='请输入操作类型'),
            Argument('review_comment', required=False),
            Argument('void_reason', required=False),
        ).parse(request.body)
        if error:
            return json_response(error=error)

        tenant_id = getattr(request.user, 'tenant_id', 'default')
        action = form.action
        user = request.user

        new_status = _SUBMISSION_ACTION_STATUS.get(action)
        if not new_status:
            return json_response(error=f'非法操作类型: {action}')

        try:
            with transaction.atomic():
                sub = CheckSheetSubmission.objects.filter(
                    tenant_id=tenant_id, project=form.project,
                    year=form.year, month=form.month,
                ).order_by('-id').first()

                if not sub:
                    return json_response(error='提交批次不存在，请先保存检查记录')

                if not sub.can_transition_to(new_status):
                    status_label = dict(SUBMISSION_STATUS_CHOICES).get(new_status, new_status)
                    return json_response(
                        error=f'当前状态[{sub.get_status_display()}]不能转为[{status_label}]')

                # 执行 action 专属字段更新 + 状态流转
                _apply_submission_action(sub, action, new_status, user, form)

                # 写入证据事件
                _record_checksheet_evidence(
                    sub, _SUBMISSION_EVENT_TYPE[action], user,
                    remark=form.review_comment or form.void_reason or ''
                )

            return json_response({'id': sub.id, 'status': sub.status})

        except Exception as e:
            logger.error(f'CheckSheet SubmissionView.post error: {e}', exc_info=True)
            return json_response(error=str(e))


class EvidencePackageView(View):
    """检查单证据包导出 - 包含业务快照/证据事件/审计日志/附件哈希清单"""

    @auth('checksheet.checksheet.view')
    def get(self, request):
        import json as _json
        import zipfile
        from io import BytesIO

        project = request.GET.get('project')
        year = request.GET.get('year')
        month = request.GET.get('month')
        if not all([project, year, month]):
            return json_response(error='缺少 project/year/month 参数')

        tenant_id = getattr(request.user, 'tenant_id', 'default')
        sub = CheckSheetSubmission.objects.filter(
            tenant_id=tenant_id, project=project, year=year, month=month,
        ).order_by('-id').first()
        if not sub:
            return json_response(error='提交批次不存在')

        # 1. 业务快照
        snapshot = _build_submission_snapshot(sub)

        # 2. 证据事件
        events = list(EvidenceEvent.objects.filter(
            tenant_id=tenant_id, module='checksheet',
            object_type='submission', object_id=str(sub.id),
        ).order_by('id'))
        events_data = [e.to_dict() for e in events]

        # 3. 审计日志（与该提交批次相关的审计记录）
        audit_logs = list(AuditLog.objects.filter(
            tenant_id=tenant_id, target_type='checksheet',
        ).order_by('id'))
        audit_data = [l.to_dict() for l in audit_logs]

        # 4. 附件哈希清单
        att_hashes = _get_attachment_hashes(tenant_id, sub.id)

        # 打包 ZIP
        buf = BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('object_snapshot.json', _json.dumps(snapshot, ensure_ascii=False, indent=2))
            zf.writestr('evidence_events.json', _json.dumps(events_data, ensure_ascii=False, indent=2))
            zf.writestr('audit_logs.json', _json.dumps(audit_data, ensure_ascii=False, indent=2))
            zf.writestr('hashes.json', _json.dumps({
                'module': 'checksheet', 'object_id': sub.id,
                'submission_status': sub.status,
                'snapshot_hash': sub.snapshot_hash,
                'attachments': att_hashes,
                'events_count': len(events_data),
                'generated_at': human_datetime(),
            }, ensure_ascii=False, indent=2))
            zf.writestr('verify.txt', '本证据包包含业务快照JSON、证据事件JSON、审计日志JSON、附件哈希清单。\n'
                        '校验方式：重新计算 object_snapshot.json 的 SHA256，与 hashes.json 中 snapshot_hash 比对。\n'
                        '证据事件哈希链可通过 evidence_events.json 中的 prev_hash/event_hash 校验连续性。\n')

        buf.seek(0)
        resp = HttpResponse(buf.getvalue(), content_type='application/zip')
        resp['Content-Disposition'] = (
            f'attachment; filename="evidence_checksheet_{project}_{year}{month}.zip"')
        return resp

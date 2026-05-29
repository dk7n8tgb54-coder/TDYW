# Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.http import JsonResponse, HttpResponse
from django.db import transaction
from django.views import View
from libs import json_response, JsonParser, Argument
from libs.decorators import auth
from .models import CheckSheetTemplate, CheckSheetRecord, CheckSheetDailySummary
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, PageBreak, Spacer
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# 配置ReportLab处理中文字符
import reportlab.rl_config
reportlab.rl_config.TTFSearchPath.append('/data/spug/spug_api/apps/checksheet/fonts')

# 全局字体注册标志
_FONT_REGISTERED = False
from io import BytesIO
import json
import logging
import sys
import os
from datetime import datetime

# 配置专门用于调试的日志文件
DEBUG_LOG_FILE = '/data/spug/spug_api/logs/checksheet_debug.log'
os.makedirs(os.path.dirname(DEBUG_LOG_FILE), exist_ok=True)

def log_debug(message):
    """输出调试信息到文件和控制台"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_line = f'[{timestamp}] {message}\n'
    # 写入文件
    with open(DEBUG_LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_line)
    # 输出到控制台
    print(f'[CheckSheet] {message}', flush=True)
    sys.stdout.flush()


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

        try:
            template = CheckSheetTemplate.objects.get(project=project)

            # 获取指定日期的检查记录
            day_filter = {}
            if day:
                day_filter['day'] = int(day)

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
                    'remark': '',
                    'rectification': ''
                })

            # 获取每日汇总（包含 operator、remark 和 rectification）
            summary_filter = {}
            if day:
                summary_filter['day'] = int(day)

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
        print(f'[CheckSheet] RecordListView.post request.body: {request.body}')
        print(f'[CheckSheet] RecordListView.post request.body type: {type(request.body)}')
        print(f'[CheckSheet] RecordListView.post request.content_type: {request.content_type}')

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
            print(f'[CheckSheet] JsonParser exception: {type(e).__name__}: {e}')
            return json_response(error=str(e))

        if error:
            print(f'[CheckSheet] RecordListView.post parse error: {error}')
            return json_response(error=error)

        print(f'[CheckSheet] RecordListView.post parsed: year={form.year}, month={form.month}, day={form.day}, project={form.project}')
        print(f'[CheckSheet] RecordListView.post records count: {len(form.records) if form.records else 0}')
        print(f'[CheckSheet] RecordListView.post daily_summary: {form.daily_summary}')

        year = form.year
        month = form.month
        day = form.day
        project = form.project
        records = form.records
        signatures = form.signatures
        daily_summary = form.daily_summary

        try:
            with transaction.atomic():
                # 获取或创建模板
                template, _ = CheckSheetTemplate.objects.get_or_create(
                    project=project,
                    defaults={'check_items': '[]'}
                )

                # 保存检查记录（不包含 remark 和 rectification）
                for record_data in records:
                    item_index = record_data.get('item_index')
                    day = record_data.get('day')
                    status = record_data.get('status', 'UNCHECKED')

                    print(f'[CheckSheet] Saving record: item_index={item_index}, day={day}, status={status}')

                    # 使用 update_or_create
                    CheckSheetRecord.objects.update_or_create(
                        template=template,
                        year=year,
                        month=month,
                        item_index=item_index,
                        day=day,
                        defaults={
                            'status': status,
                            'remark': '',
                            'rectification': '',
                            'operator': signatures.get('operator', '')
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
                            'rectification': daily_summary.get('rectification', '')
                        }
                    )

            return json_response({'msg': '保存成功'})
        except Exception as e:
            print(f'[CheckSheet] RecordListView.post exception: {type(e).__name__}: {e}')
            import traceback
            traceback.print_exc()
            return JsonResponse({'error': str(e)}, status=500)


class TemplateView(View):
    """检查表模板视图 - 处理列表查询和创建"""

    @auth('checksheet.checksheet.template_view')
    def get(self, request):
        """获取检查表模板列表"""
        templates = CheckSheetTemplate.objects.all()
        data = []
        for t in templates:
            data.append({
                'id': t.id,
                'project': t.project,
                'check_items': t.get_check_items(),
                'created_at': t.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                'updated_at': t.updated_at.strftime('%Y-%m-%d %H:%M:%S')
            })
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f'[CheckSheet] TemplateView.get returning {len(data)} templates')
        return json_response({'templates': data})

    @auth('checksheet.checksheet.template_add')
    def post(self, request):
        """创建检查表模板"""
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f'[CheckSheet] TemplateView.post request.body: {request.body}')

        form, error = JsonParser(
            Argument('project', help='请输入项目名称'),
            Argument('check_items', type=list, default=[])
        ).parse(request.body)

        if error:
            logger.error(f'[CheckSheet] TemplateView.post parse error: {error}')
            return json_response(error=error)

        logger.info(f'[CheckSheet] Creating template: project={form.project}, items_count={len(form.check_items)}')

        template = CheckSheetTemplate.objects.create(
            project=form.project,
            check_items=json.dumps(form.check_items, ensure_ascii=False)
        )

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
            if form.project:
                template.project = form.project
            if form.check_items is not None:
                template.set_check_items(form.check_items)
            template.save()
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


@auth('checksheet.checksheet.view')
def export_pdf(request):
    """导出PDF - 使用前端发送的表格数据，保证PDF与前端显示一致"""
    log_debug(f'export_pdf called, method={request.method}')

    try:
        # 解析请求参数
        params = _parse_pdf_request(request)
        if 'error' in params:
            return JsonResponse({'error': params['error']}, status=400)

        # 注册中文字体
        from .font_manager import FontManager
        font_registered = FontManager.register_chinese_font(debug_logger=log_debug)

        # 根据请求类型生成PDF
        if params.get('use_table_data'):
            log_debug(f'Using POST table_data with {len(params["table_data"])} rows')
            return _generate_pdf_from_table_data(
                params['year'], params['month'], params['title'],
                params['table_data'], params['daily_summaries'], font_registered
            )

        # 否则使用旧逻辑（从数据库读取）
        return _generate_pdf_from_database(
            params['year'], params['month'], params['project_list'], font_registered
        )

    except Exception as e:
        log_debug(f'export_pdf error: {type(e).__name__}: {e}')
        import traceback
        traceback.print_exc()
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
    log_debug(f'_generate_pdf_from_table_data called with {len(table_data)} rows, {len(daily_summaries)} daily summaries')

    try:
        # 创建文档
        doc, output = pdf_utils.create_pdf_document()
        elements = []
        actual_font = 'SimHei' if font_registered else 'Helvetica'
        log_debug(f'Using font: {actual_font}')

        # 转换表格数据
        table_data_str = pdf_utils.convert_table_data_to_strings(table_data)
        log_debug(f'Table data converted to strings')

        # 转换为Paragraph并计算列宽
        paragraph_table_data = pdf_utils.convert_to_paragraphs(table_data_str, actual_font)
        col_widths = pdf_utils.calculate_column_widths(table_data_str)

        # 创建主表格
        log_debug(f'Creating table with {len(paragraph_table_data)} rows')
        table = pdf_utils.create_main_table(paragraph_table_data, col_widths, table_data_str)

        # 添加标题和主表格
        log_debug(f'Adding title')
        elements.append(pdf_utils.create_title_paragraph(title, actual_font))
        elements.append(table)

        # 添加汇总信息表格
        if daily_summaries:
            log_debug(f'Adding summary table with {len(daily_summaries)} days of data')
            elements.append(Spacer(1, 0.5 * cm))

            days = pdf_utils.extract_days_from_headers(table_data_str)
            summary_row_data = pdf_utils.build_summary_data(daily_summaries, days)
            summary_para_data = pdf_utils.convert_summary_to_paragraphs(summary_row_data, actual_font)
            summary_table = pdf_utils.create_summary_table(summary_para_data, col_widths)
            elements.append(summary_table)

        # 生成PDF
        log_debug(f'Building PDF')
        doc.build(elements)
        output.seek(0)

        pdf_bytes = output.getvalue()
        log_debug(f'PDF generated successfully, size: {len(pdf_bytes)} bytes')

        # 保存到临时文件以便调试
        import tempfile
        with tempfile.NamedTemporaryFile(mode='wb', delete=False, suffix='.pdf') as f:
            f.write(pdf_bytes)
            log_debug(f'PDF saved to temp file: {f.name}')

        # 创建PDF响应
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{title}.pdf"'
        return response

    except Exception as e:
        log_debug(f'Error in _generate_pdf_from_table_data: {type(e).__name__}: {e}')
        import traceback
        traceback.print_exc()
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

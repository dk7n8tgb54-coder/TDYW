# Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""PDF生成工具函数 - 从views.py拆分出来"""

import re
from io import BytesIO
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Spacer, Paragraph
from reportlab.lib.styles import ParagraphStyle

from .views import log_debug


def create_pdf_document():
    """创建PDF文档模板"""
    output = BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=landscape(A4),
        rightMargin=1.0 * cm,
        leftMargin=1.0 * cm,
        topMargin=1.0 * cm,
        bottomMargin=0.8 * cm
    )
    return doc, output


def convert_table_data_to_strings(table_data):
    """将表格数据转换为字符串格式"""
    table_data_str = []
    for row_idx, row in enumerate(table_data):
        row_str = []
        for col_idx, cell in enumerate(row):
            if cell is None:
                cell_text = ''
            else:
                cell_text = str(cell)
                if isinstance(cell_text, bytes):
                    cell_text = cell_text.decode('utf-8')
            if row_idx < 3 and col_idx < 3:
                log_debug(f'  Row {row_idx}, Col {col_idx}: {repr(cell_text)}')
            row_str.append(cell_text)
        table_data_str.append(row_str)
    return table_data_str


def create_paragraph_style(font_name, alignment=1, font_size=8):
    """创建Paragraph样式"""
    return ParagraphStyle(
        f'Cell_{alignment}',
        fontName=font_name,
        fontSize=font_size,
        alignment=alignment,
        leading=10,
        wordWrap='CJK'
    )


def convert_to_paragraphs(table_data_str, font_name):
    """将字符串数据转换为Paragraph对象"""
    cell_style_center = create_paragraph_style(font_name, alignment=1)
    cell_style_left = create_paragraph_style(font_name, alignment=0)

    paragraph_table_data = []
    for row_idx, row in enumerate(table_data_str):
        para_row = []
        for col_idx, cell in enumerate(row):
            if row_idx == 0:
                para = Paragraph(cell, cell_style_center)
            elif col_idx == 1:
                para = Paragraph(cell, cell_style_left)
            else:
                para = Paragraph(cell, cell_style_center)
            para_row.append(para)
        paragraph_table_data.append(para_row)

    return paragraph_table_data


def calculate_column_widths(table_data_str):
    """计算列宽"""
    page_width = landscape(A4)[0]
    margins = 2.0 * cm
    available_width = page_width - margins

    col_count = len(table_data_str[0])
    if col_count <= 2:
        return None

    first_col_width = 1.5 * cm
    second_col_width = 3.5 * cm
    remaining_width = available_width - first_col_width - second_col_width
    other_col_width = remaining_width / (col_count - 2)

    col_widths = [first_col_width, second_col_width] + [other_col_width] * (col_count - 2)
    col_widths = [max(w, 0.8 * cm) for w in col_widths]

    log_debug(f'Page width: {page_width}, Available: {available_width:.2f}, Col widths: {col_widths}')
    return col_widths


def build_merge_styles(table_data_str):
    """构建项目列合并样式"""
    style_list = [
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
    ]

    current_project = None
    project_start_row = 1

    for row_idx in range(1, len(table_data_str)):
        project_cell = table_data_str[row_idx][0]

        if project_cell and project_cell != current_project:
            if current_project is not None and project_start_row < row_idx:
                span_count = row_idx - project_start_row
                if span_count > 1:
                    log_debug(f'Merging project "{current_project}" from row {project_start_row} to {row_idx - 1} ({span_count} rows)')
                    style_list.append(('SPAN', (0, project_start_row), (0, row_idx - 1)))

            current_project = project_cell
            project_start_row = row_idx

    # 处理最后一个项目
    if current_project is not None and project_start_row < len(table_data_str):
        span_count = len(table_data_str) - project_start_row
        if span_count > 1:
            log_debug(f'Merging last project "{current_project}" from row {project_start_row} to end ({span_count} rows)')
            style_list.append(('SPAN', (0, project_start_row), (0, len(table_data_str) - 1)))

    style_list.append(('ALIGN', (0, 1), (0, -1), 'LEFT'))
    style_list.append(('VALIGN', (0, 1), (0, -1), 'MIDDLE'))

    return style_list


def create_main_table(paragraph_table_data, col_widths, table_data_str):
    """创建主表格"""
    table = Table(paragraph_table_data, colWidths=col_widths, repeatRows=1)
    style_list = build_merge_styles(table_data_str)
    table.setStyle(TableStyle(style_list))
    return table


def extract_days_from_headers(table_data_str):
    """从表头提取日期"""
    col_count = len(table_data_str[0])
    days = []
    for i in range(2, col_count):
        header = table_data_str[0][i]
        match = re.search(r'(\d+)', header)
        if match:
            days.append(int(match.group(1)))
    return days


def build_summary_data(daily_summaries, days):
    """构建汇总数据行"""
    summary_row_data = []

    # 第一行：发现问题及整改情况
    row1 = ['发现问题及整改情况：', '']
    for day in days:
        summary = daily_summaries.get(str(day), {})
        row1.append(summary.get('rectification', '') or '')
    summary_row_data.append(row1)

    # 第二行：值班人员签名
    row2 = ['值班人员签名：', '']
    for day in days:
        summary = daily_summaries.get(str(day), {})
        row2.append(summary.get('operator', '') or '')
    summary_row_data.append(row2)

    # 第三行：备注
    row3 = ['备注：', '']
    for day in days:
        summary = daily_summaries.get(str(day), {})
        row3.append(summary.get('remark', '') or '')
    summary_row_data.append(row3)

    return summary_row_data


def convert_summary_to_paragraphs(summary_row_data, font_name):
    """将汇总数据转换为Paragraph"""
    summary_para_data = []
    for row in summary_row_data:
        para_row = []
        for col_idx, cell in enumerate(row):
            if col_idx == 0:
                para = Paragraph(f'<b>{cell}</b>', ParagraphStyle(
                    'SummaryLabel', fontName=font_name, fontSize=9, alignment=0, leading=12
                ))
            elif col_idx == 1:
                para = Paragraph('', ParagraphStyle(
                    'EmptyCell', fontName=font_name, fontSize=9
                ))
            else:
                para = Paragraph(cell or '—', ParagraphStyle(
                    'SummaryContent', fontName=font_name, fontSize=8, alignment=0, leading=10, wordWrap='CJK'
                ))
            para_row.append(para)
        summary_para_data.append(para_row)

    return summary_para_data


def create_summary_table(summary_para_data, col_widths):
    """创建汇总表格"""
    summary_table = Table(summary_para_data, colWidths=col_widths, repeatRows=1)
    summary_table_style = TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
    ])
    summary_table.setStyle(summary_table_style)
    return summary_table


def create_title_paragraph(title, font_name):
    """创建标题段落"""
    title_style = ParagraphStyle(
        'CustomTitle',
        fontName=font_name,
        fontSize=12,
        spaceAfter=6,
        alignment=1
    )
    return Paragraph(title, title_style)

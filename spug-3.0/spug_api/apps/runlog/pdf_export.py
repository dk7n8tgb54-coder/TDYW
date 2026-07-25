# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
运行日志PDF导出模块

简洁正式风格：适合内部归档和打印。
- 主体颜色：黑、深灰、浅灰
- 表头：浅灰背景 + 加粗
- 边框：浅灰细线
- P0/P1/P2 与状态保留小范围文字颜色
- 无大面积彩色背景、无卡片化设计、无装饰符号
"""

import logging
from io import BytesIO
from datetime import datetime
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    HRFlowable
)
from libs.font_manager import FontManager, FONT_NAME

logger = logging.getLogger(__name__)


# ============ 颜色（简洁正式：黑/深灰/浅灰为主） ============

# 主体色
COLOR_TEXT = colors.HexColor('#222222')          # 正文 - 近黑
COLOR_TEXT_SECONDARY = colors.HexColor('#666666') # 次要文字 - 深灰
COLOR_LABEL = colors.HexColor('#555555')          # 标签 - 深灰
COLOR_BORDER = colors.HexColor('#cccccc')         # 边框 - 浅灰
COLOR_BORDER_LIGHT = colors.HexColor('#dddddd')   # 更浅的分隔线
COLOR_BG_HEADER = colors.HexColor('#f0f0f0')      # 表头背景 - 浅灰
COLOR_BG_LABEL = colors.HexColor('#f7f7f7')       # 标签列背景 - 极浅灰

# 小范围点缀色（仅用于 P0/P1/P2 和状态文字，不大面积铺色）
COLOR_P0 = colors.HexColor('#c0392b')   # P0 紧急 - 深红
COLOR_P1 = colors.HexColor('#d68910')   # P1 重要 - 深橙
COLOR_P2 = colors.HexColor('#1e8449')   # P2 一般 - 深绿
COLOR_STATUS_PROGRESS = colors.HexColor('#d68910')  # 处理中 - 深橙
COLOR_STATUS_RESOLVED = colors.HexColor('#1e8449')  # 已解决 - 深绿
COLOR_GRAY = colors.HexColor('#999999')             # 未知 - 灰


def _get_severity_color(severity):
    severity_colors = {'P0': COLOR_P0, 'P1': COLOR_P1, 'P2': COLOR_P2}
    return severity_colors.get(severity, COLOR_GRAY)


def _get_status_color(status):
    status_colors = {'in_progress': COLOR_STATUS_PROGRESS, 'resolved': COLOR_STATUS_RESOLVED}
    return status_colors.get(status, COLOR_GRAY)


# ============ Paragraph 样式 ============

def _title_style():
    return ParagraphStyle(
        'DocTitle', fontName=FONT_NAME, fontSize=16,
        alignment=1, spaceAfter=2, spaceBefore=0,
        textColor=COLOR_TEXT, leading=24
    )


def _subtitle_style():
    return ParagraphStyle(
        'DocSubtitle', fontName=FONT_NAME, fontSize=9,
        alignment=1, spaceAfter=10, spaceBefore=0,
        textColor=COLOR_TEXT_SECONDARY, leading=14
    )


def _section_title_style():
    return ParagraphStyle(
        'SectionTitle', fontName=FONT_NAME, fontSize=12,
        alignment=0, spaceAfter=6, spaceBefore=14,
        textColor=COLOR_TEXT, leading=18
    )


def _event_title_style():
    """单条事件的小标题（非卡片头，普通加粗标题）"""
    return ParagraphStyle(
        'EventTitle', fontName=FONT_NAME, fontSize=11,
        alignment=0, spaceAfter=4, spaceBefore=10,
        textColor=COLOR_TEXT, leading=16
    )


def _cell_style(alignment=0, font_size=9, bold=False):
    return ParagraphStyle(
        f'Cell_{alignment}_{font_size}_{bold}',
        fontName=FONT_NAME, fontSize=font_size,
        alignment=alignment, leading=14,
        wordWrap='CJK',
        textColor=COLOR_TEXT,
    )


def _label_cell_style():
    return ParagraphStyle(
        'LabelCell', fontName=FONT_NAME, fontSize=9,
        alignment=2, leading=14, wordWrap='CJK',
        textColor=COLOR_LABEL,
    )


def _empty_style():
    return ParagraphStyle(
        'Empty', fontName=FONT_NAME, fontSize=9,
        alignment=0, leading=14,
        textColor=COLOR_TEXT_SECONDARY,
        leftIndent=8,
    )


def _content_style():
    return ParagraphStyle(
        'Content', fontName=FONT_NAME, fontSize=9,
        alignment=0, leading=15,
        wordWrap='CJK',
        textColor=COLOR_TEXT,
        spaceBefore=2,
        spaceAfter=2,
    )


# ============ 布局常量 ============

# A4(21cm) - 左边距(2cm) - 右边距(2cm) = 17.0cm
PAGE_USABLE_WIDTH = 17.0 * cm


# ============ 辅助函数 ============

def _safe(text, default='-'):
    """安全文本：None/空值处理 + XML转义，专用于Paragraph"""
    if text is None or text == '' or text == 'None':
        text = default
    return xml_escape(str(text))


def _label(text):
    """创建标签单元格"""
    return Paragraph(f'{text}：', _label_cell_style())


def _value(text):
    """创建值单元格（自动处理None + 截断 + XML转义）"""
    if text is None or text == '' or text == 'None':
        text = '-'
    display_text = str(text)
    if len(display_text) > 500:
        display_text = display_text[:500] + '...'
    return Paragraph(xml_escape(display_text), _cell_style(alignment=0))


def _severity_text(severity):
    """级别文字（带小范围颜色，仅文字着色不铺背景）"""
    severity_map = {'P0': 'P0 紧急', 'P1': 'P1 重要', 'P2': 'P2 一般'}
    text = severity_map.get(severity, severity or '-')
    color = _get_severity_color(severity)
    return Paragraph(
        f'<font color="{color.hexval()}">{_safe(text)}</font>',
        _cell_style(alignment=0, font_size=9)
    )


def _status_text(status):
    """状态文字（带小范围颜色，仅文字着色不铺背景）"""
    status_map = {'in_progress': '处理中', 'resolved': '已解决'}
    text = status_map.get(status, status or '-')
    color = _get_status_color(status)
    return Paragraph(
        f'<font color="{color.hexval()}">{_safe(text)}</font>',
        _cell_style(alignment=0, font_size=9)
    )


# ============ 页脚（带页码） ============

def _on_page(canvas, doc):
    """页脚回调：底部细线 + 系统生成说明 + 页码"""
    canvas.saveState()
    page_width, page_height = A4
    # 底部细灰线
    canvas.setStrokeColor(COLOR_BORDER_LIGHT)
    canvas.setLineWidth(0.5)
    y_line = 1.2 * cm
    canvas.line(2.0 * cm, y_line, page_width - 2.0 * cm, y_line)
    # 页脚文字：仅显示页码
    canvas.setFont(FONT_NAME, 7)
    canvas.setFillColor(COLOR_TEXT_SECONDARY)
    canvas.drawCentredString(page_width / 2, 0.7 * cm, f'第 {doc.page} 页')
    canvas.restoreState()


# ============ PDF 构建 ============

def generate_runlog_pdf(events_data, date_range_text=''):
    """
    生成运行日志PDF文档（简洁正式风格）

    Args:
        events_data: list[dict] - 事件列表（每条事件需包含 updates 字段）
        date_range_text: str - 日期范围描述

    Returns:
        BytesIO: PDF文件流
    """
    FontManager.register_chinese_font(debug_logger=logger.debug)

    output = BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=2.0 * cm,
        leftMargin=2.0 * cm,
        topMargin=2.0 * cm,
        bottomMargin=1.8 * cm,
    )

    story = []

    # ---- 文档标题 ----
    story.append(Paragraph('运行日志报告', _title_style()))

    # 导出信息（一行简洁文字，不用彩色分隔线）
    export_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    subtitle_parts = [f'导出时间：{export_time}']
    if date_range_text:
        subtitle_parts.append(f'日期范围：{date_range_text}')
    in_progress_count = sum(1 for e in events_data if e.get('status') == 'in_progress')
    resolved_count = sum(1 for e in events_data if e.get('status') == 'resolved')
    total_updates = sum(len(e.get('updates', [])) for e in events_data)
    subtitle_parts.append(f'共 {len(events_data)} 条事件 / {total_updates} 条动态')
    story.append(Paragraph(xml_escape('　|　'.join(subtitle_parts)), _subtitle_style()))

    # 顶部细灰分隔线（替代原蓝色粗线）
    story.append(HRFlowable(
        width='100%', thickness=0.5, color=COLOR_BORDER,
        spaceAfter=10, spaceBefore=2
    ))

    # ---- 统计概览 ----
    story.append(Paragraph('统计概览', _section_title_style()))
    story.append(_build_stats_table(events_data, in_progress_count, resolved_count, total_updates))
    story.append(Spacer(1, 14))

    # ---- 事件汇总 ----
    story.append(Paragraph('事件汇总', _section_title_style()))

    if not events_data:
        story.append(Paragraph('暂无运行日志', _empty_style()))
    else:
        story.append(_build_summary_table(events_data))
        story.append(Spacer(1, 14))

        # ---- 动态明细 ----
        story.append(Paragraph('动态明细', _section_title_style()))

        for idx, event in enumerate(events_data):
            updates = event.get('updates', [])
            block = _build_event_detail_block(event, updates, idx + 1)
            for item in block:
                story.append(item)
            # 事件之间用细灰线分隔（不用大间距或彩色块）
            if idx < len(events_data) - 1:
                story.append(HRFlowable(
                    width='100%', thickness=0.3, color=COLOR_BORDER_LIGHT,
                    spaceBefore=8, spaceAfter=4
                ))

    doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
    output.seek(0)
    return output


def _build_stats_table(events_data, in_progress_count, resolved_count, total_updates):
    """构建统计概览表格（简洁：浅灰表头列 + 细灰边框，无蓝色 BOX）"""
    p0_count = sum(1 for e in events_data if e.get('severity') == 'P0')
    p1_count = sum(1 for e in events_data if e.get('severity') == 'P1')
    p2_count = sum(1 for e in events_data if e.get('severity') == 'P2')

    # P0/P1/P2 数字保留小范围颜色（仅数字着色）
    def _num_cell(value, color=None):
        if color:
            inner = f'<font color="{color.hexval()}"><b>{value}</b></font>'
        else:
            inner = f'<b>{value}</b>'
        return Paragraph(inner, _cell_style(alignment=1, font_size=11))

    rows = [
        [
            Paragraph('<b>事件总数</b>', _cell_style(alignment=1)),
            _num_cell(len(events_data)),
            Paragraph('<b>处理中</b>', _cell_style(alignment=1)),
            _num_cell(in_progress_count, COLOR_STATUS_PROGRESS),
            Paragraph('<b>已解决</b>', _cell_style(alignment=1)),
            _num_cell(resolved_count, COLOR_STATUS_RESOLVED),
        ],
        [
            Paragraph('<b>P0 紧急</b>', _cell_style(alignment=1)),
            _num_cell(p0_count, COLOR_P0),
            Paragraph('<b>P1 重要</b>', _cell_style(alignment=1)),
            _num_cell(p1_count, COLOR_P1),
            Paragraph('<b>P2 一般</b>', _cell_style(alignment=1)),
            _num_cell(p2_count, COLOR_P2),
        ],
    ]

    col_widths = [2.2 * cm, 2.3 * cm, 2.2 * cm, 2.3 * cm, 2.2 * cm, 2.3 * cm]
    table = Table(rows, colWidths=col_widths)
    table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        # 标签列浅灰背景
        ('BACKGROUND', (0, 0), (0, -1), COLOR_BG_LABEL),
        ('BACKGROUND', (2, 0), (2, -1), COLOR_BG_LABEL),
        ('BACKGROUND', (4, 0), (4, -1), COLOR_BG_LABEL),
        # 浅灰细边框（无蓝色 BOX）
        ('GRID', (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ('FONTNAME', (0, 0), (-1, -1), FONT_NAME),
    ]))
    return table


def _build_summary_table(events_data):
    """构建事件汇总表格（表头浅灰背景加粗 + 浅灰细边框，无隔行变色）"""
    header_row = [
        Paragraph('<b>序号</b>', _cell_style(alignment=1, font_size=9)),
        Paragraph('<b>事件标题</b>', _cell_style(alignment=1, font_size=9)),
        Paragraph('<b>类型</b>', _cell_style(alignment=1, font_size=9)),
        Paragraph('<b>级别</b>', _cell_style(alignment=1, font_size=9)),
        Paragraph('<b>状态</b>', _cell_style(alignment=1, font_size=9)),
        Paragraph('<b>系统</b>', _cell_style(alignment=1, font_size=9)),
        Paragraph('<b>责任人</b>', _cell_style(alignment=1, font_size=9)),
        Paragraph('<b>动态数</b>', _cell_style(alignment=1, font_size=9)),
    ]

    table_rows = [header_row]
    for idx, event in enumerate(events_data):
        row = [
            Paragraph(str(idx + 1), _cell_style(alignment=1)),
            Paragraph(_safe(event.get('event_title')), _cell_style()),
            Paragraph(_safe(event.get('event_type')), _cell_style()),
            _severity_text(event.get('severity', '')),
            _status_text(event.get('status', '')),
            Paragraph(_safe(event.get('system_name')), _cell_style()),
            Paragraph(_safe(event.get('responsible_user_name')), _cell_style()),
            Paragraph(str(event.get('update_count', 0)), _cell_style(alignment=1)),
        ]
        table_rows.append(row)

    col_widths = [1.0 * cm, 3.8 * cm, 1.8 * cm, 2.0 * cm, 2.0 * cm, 2.2 * cm, 2.0 * cm, 2.0 * cm]
    summary_table = Table(table_rows, colWidths=col_widths, repeatRows=1)

    summary_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        # 表头浅灰背景 + 加粗（加粗已在文字内）
        ('BACKGROUND', (0, 0), (-1, 0), COLOR_BG_HEADER),
        ('FONTNAME', (0, 0), (-1, -1), FONT_NAME),
        # 浅灰细边框
        ('GRID', (0, 0), (-1, -1), 0.5, COLOR_BORDER),
    ]))
    return summary_table


def _build_event_detail_block(event, updates, index):
    """
    构建单条事件详情（非卡片化：普通标题 + 基础信息表格 + 动态记录列表）。
    返回独立的 flowable 列表，允许自然分页。
    """
    elements = []

    # 1. 事件小标题（普通加粗标题，非卡片头）
    title_text = f'事件 {index}：{_safe(event.get("event_title"))}'
    elements.append(Paragraph(title_text, _event_title_style()))

    # 2. 基础信息表格（4列：标签-值-标签-值）
    label_w = 2.8 * cm
    value_w = (PAGE_USABLE_WIDTH - 2 * label_w) / 2

    detail_rows = [
        [_label('事件类型'), _value(event.get('event_type')),
         _label('关联系统'), _value(event.get('system_name'))],
        [_label('事件级别'), _severity_text(event.get('severity')),
         _label('责任人'), _value(event.get('responsible_user_name'))],
        [_label('当前状态'), _status_text(event.get('status')),
         _label('动态数量'), _value(str(event.get('update_count', 0)))],
        [_label('创建时间'), _value(event.get('created_at')),
         _label('更新时间'), _value(event.get('updated_at'))],
    ]

    detail_table = Table(detail_rows, colWidths=[label_w, value_w, label_w, value_w])
    detail_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        # 标签列极浅灰背景
        ('BACKGROUND', (0, 0), (0, -1), COLOR_BG_LABEL),
        ('BACKGROUND', (2, 0), (2, -1), COLOR_BG_LABEL),
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
        # 浅灰细边框
        ('GRID', (0, 0), (-1, -1), 0.5, COLOR_BORDER),
        ('FONTNAME', (0, 0), (-1, -1), FONT_NAME),
    ]))
    elements.append(detail_table)

    # 3. 处理措施（已解决时显示）
    if event.get('resolution'):
        elements.append(Spacer(1, 6))
        elements.append(Paragraph(
            '<b>处理措施：</b>',
            ParagraphStyle('ResLabel', fontName=FONT_NAME, fontSize=9,
                           alignment=0, leading=14, textColor=COLOR_LABEL)
        ))
        elements.append(Paragraph(_safe(event['resolution']), _content_style()))

    # 4. 动态记录列表（编号 + 日期 + 记录人 + 内容，无装饰符号）
    if updates:
        elements.append(Spacer(1, 6))
        elements.append(Paragraph(
            f'<b>动态记录（{len(updates)} 条）：</b>',
            ParagraphStyle('UpdatesLabel', fontName=FONT_NAME, fontSize=9,
                           alignment=0, leading=14, textColor=COLOR_LABEL)
        ))
        for u_idx, update in enumerate(updates):
            elements.extend(_build_update_block(update, u_idx + 1))
    elif event.get('update_count', 0) == 0:
        elements.append(Spacer(1, 4))
        elements.append(Paragraph('暂无动态记录', _empty_style()))

    return elements


def _build_update_block(update, seq_index):
    """构建单条动态记录（编号 + 日期 + 记录人 + 内容，无彩色装饰符号）"""
    elements = []

    # 动态头部：编号 + 日期 + 记录人（+ 值班人，有值才显示）
    header_parts = [f'#{seq_index}', _safe(update.get("update_date")), f'记录人：{_safe(update.get("recorder"))}']
    duty_person = update.get('duty_person')
    if duty_person:
        header_parts.append(f'值班人：{_safe(duty_person)}')
    header = Paragraph(
        '　'.join(header_parts),
        ParagraphStyle('UpdateHeader', fontName=FONT_NAME, fontSize=9,
                       alignment=0, leading=14, textColor=COLOR_TEXT,
                       leftIndent=8, spaceBefore=4)
    )
    elements.append(header)

    # 详细内容
    content = update.get('detail_content', '')
    if content:
        elements.append(Paragraph(
            _safe(content),
            ParagraphStyle('UpdateContent', parent=_content_style(),
                           leftIndent=16)
        ))

    return elements

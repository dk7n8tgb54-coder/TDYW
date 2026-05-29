# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
运行日志PDF导出模块
生成包含事件汇总 + 动态明细的精美PDF文档
"""

import os
import logging
from io import BytesIO
from datetime import datetime
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    HRFlowable, KeepTogether, PageBreak
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

logger = logging.getLogger(__name__)

# ============ 字体管理 ============

_FONT_REGISTERED = False
FONT_NAME = 'SimHei'


def _register_chinese_font():
    """注册中文字体，复用checksheets模块的FontManager逻辑"""
    global _FONT_REGISTERED, FONT_NAME

    if _FONT_REGISTERED:
        return True

    # 优先尝试复用checksheet的FontManager
    try:
        from apps.checksheet.font_manager import FontManager
        if FontManager.register_chinese_font(debug_logger=logger.debug):
            _FONT_REGISTERED = True
            FONT_NAME = 'SimHei'
            return True
    except Exception:
        pass

    # 回退：手动搜索字体
    font_paths = []

    # 1. 项目内嵌字体
    checksheet_fonts = os.path.join(os.path.dirname(__file__), '..', 'checksheet', 'fonts')
    if os.path.exists(checksheet_fonts):
        for f in ['simhei.ttf', 'simhei.otf']:
            fp = os.path.join(checksheet_fonts, f)
            if os.path.exists(fp):
                font_paths.append(fp)

    # 2. 容器字体
    container_dir = '/data/spug/spug_api/apps/checksheet/fonts'
    if os.path.exists(container_dir):
        for f in ['simhei.ttf', 'simhei.otf']:
            fp = os.path.join(container_dir, f)
            if os.path.exists(fp):
                font_paths.append(fp)

    # 3. 系统字体
    if os.name == 'nt':
        font_paths.extend([
            r'C:\Windows\Fonts\simhei.ttf',
            r'C:\Windows\Fonts\simsun.ttc',
            r'C:\Windows\Fonts\msyh.ttc',
        ])
    else:
        font_paths.extend([
            '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf',
            '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc',
            '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
        ])

    for fp in font_paths:
        if os.path.exists(fp):
            try:
                pdfmetrics.registerFont(TTFont('SimHei', fp))
                _FONT_REGISTERED = True
                FONT_NAME = 'SimHei'
                logger.info(f'RunLog PDF: Registered font {fp}')
                return True
            except Exception as e:
                logger.warning(f'RunLog PDF: Failed to register font {fp}: {e}')

    logger.warning('RunLog PDF: No Chinese font found, text may display incorrectly')
    return False


# ============ 颜色主题 ============

THEME_PRIMARY = colors.HexColor('#1890ff')
THEME_PRIMARY_DARK = colors.HexColor('#096dd9')
THEME_SUCCESS = colors.HexColor('#52c41a')
THEME_ERROR = colors.HexColor('#ff4d4f')
THEME_WARNING = colors.HexColor('#faad14')
THEME_GRAY = colors.HexColor('#999999')
THEME_BG_LIGHT = colors.HexColor('#fafafa')
THEME_BG_HEADER = colors.HexColor('#e6f7ff')
THEME_BORDER = colors.HexColor('#d9d9d9')
THEME_TEXT = colors.HexColor('#333333')
THEME_TEXT_SECONDARY = colors.HexColor('#666666')
THEME_WHITE = colors.white


def _get_severity_color(severity):
    """根据事件级别返回颜色"""
    severity_colors = {
        'P0': THEME_ERROR,    # 紧急 - 红
        'P1': THEME_WARNING,  # 重要 - 橙
        'P2': THEME_SUCCESS,  # 一般 - 绿
    }
    return severity_colors.get(severity, THEME_GRAY)


def _get_status_color(status):
    """根据事件状态返回颜色"""
    status_colors = {
        'in_progress': THEME_WARNING,   # 处理中 - 橙
        'resolved': THEME_SUCCESS,       # 已解决 - 绿
    }
    return status_colors.get(status, THEME_GRAY)


# ============ Paragraph 样式 ============

def _title_style():
    return ParagraphStyle(
        'DocTitle', fontName=FONT_NAME, fontSize=18,
        alignment=1, spaceAfter=4, spaceBefore=0,
        textColor=THEME_PRIMARY_DARK, leading=26
    )


def _subtitle_style():
    return ParagraphStyle(
        'DocSubtitle', fontName=FONT_NAME, fontSize=10,
        alignment=1, spaceAfter=12, spaceBefore=0,
        textColor=THEME_TEXT_SECONDARY, leading=16
    )


def _section_title_style():
    return ParagraphStyle(
        'SectionTitle', fontName=FONT_NAME, fontSize=13,
        alignment=0, spaceAfter=8, spaceBefore=16,
        textColor=THEME_PRIMARY_DARK, leading=20
    )


def _cell_style(alignment=0, font_size=9, bold=False):
    return ParagraphStyle(
        f'Cell_{alignment}_{font_size}_{bold}',
        fontName=FONT_NAME, fontSize=font_size,
        alignment=alignment, leading=14,
        wordWrap='CJK',
        textColor=THEME_TEXT,
    )


def _label_cell_style():
    return ParagraphStyle(
        'LabelCell', fontName=FONT_NAME, fontSize=9,
        alignment=2, leading=14, wordWrap='CJK',
        textColor=THEME_TEXT_SECONDARY,
    )


def _empty_style():
    return ParagraphStyle(
        'Empty', fontName=FONT_NAME, fontSize=10,
        alignment=1, leading=16,
        textColor=THEME_TEXT_SECONDARY,
    )


def _content_style():
    return ParagraphStyle(
        'Content', fontName=FONT_NAME, fontSize=10,
        alignment=0, leading=18,
        wordWrap='CJK',
        textColor=THEME_TEXT,
        spaceBefore=4,
        spaceAfter=4,
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


def _severity_tag(severity):
    """生成带颜色的级别标签"""
    severity_map = {'P0': 'P0 紧急', 'P1': 'P1 重要', 'P2': 'P2 一般'}
    text = severity_map.get(severity, severity)
    color = _get_severity_color(severity)
    return Paragraph(
        f'<font color="{color.hexval()}">● {text}</font>',
        _cell_style(alignment=0, font_size=9)
    )


def _status_tag(status):
    """生成带颜色的状态标签"""
    status_map = {'in_progress': '处理中', 'resolved': '已解决'}
    text = status_map.get(status, status)
    color = _get_status_color(status)
    return Paragraph(
        f'<font color="{color.hexval()}">● {text}</font>',
        _cell_style(alignment=0, font_size=9)
    )


# ============ PDF 构建 ============

def generate_runlog_pdf(events_data, date_range_text=''):
    """
    生成运行日志PDF文档

    Args:
        events_data: list[dict] - 事件列表（每条事件需包含 updates 字段）
        date_range_text: str - 日期范围描述

    Returns:
        BytesIO: PDF文件流
    """
    _register_chinese_font()

    output = BytesIO()
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=2.0 * cm,
        leftMargin=2.0 * cm,
        topMargin=2.0 * cm,
        bottomMargin=1.5 * cm,
    )

    story = []

    # ---- 文档标题 ----
    story.append(Paragraph('运行日志报告', _title_style()))

    # 导出信息
    export_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    subtitle_parts = [f'导出时间：{export_time}']
    if date_range_text:
        subtitle_parts.append(f'日期范围：{date_range_text}')
    # 统计
    in_progress_count = sum(1 for e in events_data if e.get('status') == 'in_progress')
    resolved_count = sum(1 for e in events_data if e.get('status') == 'resolved')
    total_updates = sum(len(e.get('updates', [])) for e in events_data)
    subtitle_parts.append(f'共 {len(events_data)} 条事件 / {total_updates} 条动态')
    story.append(Paragraph(xml_escape('　|　'.join(subtitle_parts)), _subtitle_style()))

    # 分隔线
    story.append(HRFlowable(
        width='100%', thickness=1.5, color=THEME_PRIMARY,
        spaceAfter=12, spaceBefore=4
    ))

    # ---- 统计概览 ----
    story.append(Paragraph('统计概览', _section_title_style()))
    story.append(_build_stats_table(events_data, in_progress_count, resolved_count, total_updates))
    story.append(Spacer(1, 16))

    # ---- 事件汇总表 ----
    story.append(Paragraph('事件汇总', _section_title_style()))

    if not events_data:
        story.append(Paragraph('暂无运行日志', _empty_style()))
    else:
        story.append(_build_summary_table(events_data))
        story.append(Spacer(1, 16))

        # ---- 动态明细 ----
        story.append(Paragraph('动态明细', _section_title_style()))

        for idx, event in enumerate(events_data):
            updates = event.get('updates', [])
            block = _build_event_detail_block(event, updates, idx + 1)
            # 不使用 KeepTogether：事件卡片可能很长（多条动态），必须允许分页
            for item in block:
                story.append(item)
            if idx < len(events_data) - 1:
                story.append(Spacer(1, 10))

    # ---- 页脚 ----
    story.append(Spacer(1, 20))
    story.append(HRFlowable(
        width='100%', thickness=0.5, color=THEME_BORDER,
        spaceAfter=6, spaceBefore=6
    ))
    footer_style = ParagraphStyle(
        'Footer', fontName=FONT_NAME, fontSize=7,
        alignment=1, textColor=THEME_TEXT_SECONDARY
    )
    story.append(Paragraph('本报告由系统自动生成，仅供参考', footer_style))

    doc.build(story)
    output.seek(0)
    return output


def _build_stats_table(events_data, in_progress_count, resolved_count, total_updates):
    """构建统计概览表格"""
    p0_count = sum(1 for e in events_data if e.get('severity') == 'P0')
    p1_count = sum(1 for e in events_data if e.get('severity') == 'P1')
    p2_count = sum(1 for e in events_data if e.get('severity') == 'P2')

    rows = [
        [
            Paragraph('<b>事件总数</b>', _cell_style(alignment=1)),
            Paragraph(f'<b>{len(events_data)}</b>', _cell_style(alignment=1, font_size=12)),
            Paragraph('<b>处理中</b>', _cell_style(alignment=1)),
            Paragraph(f'<font color="{THEME_WARNING.hexval()}"><b>{in_progress_count}</b></font>',
                      _cell_style(alignment=1, font_size=12)),
            Paragraph('<b>已解决</b>', _cell_style(alignment=1)),
            Paragraph(f'<font color="{THEME_SUCCESS.hexval()}"><b>{resolved_count}</b></font>',
                      _cell_style(alignment=1, font_size=12)),
        ],
        [
            Paragraph('<b>P0 紧急</b>', _cell_style(alignment=1)),
            Paragraph(f'<font color="{THEME_ERROR.hexval()}"><b>{p0_count}</b></font>',
                      _cell_style(alignment=1, font_size=12)),
            Paragraph('<b>P1 重要</b>', _cell_style(alignment=1)),
            Paragraph(f'<font color="{THEME_WARNING.hexval()}"><b>{p1_count}</b></font>',
                      _cell_style(alignment=1, font_size=12)),
            Paragraph('<b>P2 一般</b>', _cell_style(alignment=1)),
            Paragraph(f'<font color="{THEME_SUCCESS.hexval()}"><b>{p2_count}</b></font>',
                      _cell_style(alignment=1, font_size=12)),
        ],
    ]

    col_widths = [2.2 * cm, 2.3 * cm, 2.2 * cm, 2.3 * cm, 2.2 * cm, 2.3 * cm]
    table = Table(rows, colWidths=col_widths)
    table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('BACKGROUND', (0, 0), (0, -1), THEME_BG_LIGHT),
        ('BACKGROUND', (2, 0), (2, -1), THEME_BG_LIGHT),
        ('BACKGROUND', (4, 0), (4, -1), THEME_BG_LIGHT),
        ('GRID', (0, 0), (-1, -1), 0.5, THEME_BORDER),
        ('FONTNAME', (0, 0), (-1, -1), FONT_NAME),
        ('BOX', (0, 0), (-1, -1), 1, THEME_PRIMARY),
    ]))
    return table


def _build_summary_table(events_data):
    """构建事件汇总表格"""
    header_row = [
        Paragraph('序号', _cell_style(alignment=1, font_size=9)),
        Paragraph('事件标题', _cell_style(alignment=1, font_size=9)),
        Paragraph('类型', _cell_style(alignment=1, font_size=9)),
        Paragraph('级别', _cell_style(alignment=1, font_size=9)),
        Paragraph('状态', _cell_style(alignment=1, font_size=9)),
        Paragraph('系统', _cell_style(alignment=1, font_size=9)),
        Paragraph('责任人', _cell_style(alignment=1, font_size=9)),
        Paragraph('动态数', _cell_style(alignment=1, font_size=9)),
    ]

    table_rows = [header_row]
    for idx, event in enumerate(events_data):
        row = [
            Paragraph(str(idx + 1), _cell_style(alignment=1)),
            Paragraph(_safe(event.get('event_title')), _cell_style()),
            Paragraph(_safe(event.get('event_type')), _cell_style()),
            _severity_tag(event.get('severity', '')),
            _status_tag(event.get('status', '')),
            Paragraph(_safe(event.get('system_name')), _cell_style()),
            Paragraph(_safe(event.get('responsible_user_name')), _cell_style()),
            Paragraph(str(event.get('update_count', 0)), _cell_style(alignment=1)),
        ]
        table_rows.append(row)

    col_widths = [1.0 * cm, 3.8 * cm, 1.8 * cm, 2.0 * cm, 2.0 * cm, 2.2 * cm, 2.0 * cm, 2.0 * cm]
    summary_table = Table(table_rows, colWidths=col_widths)

    table_style_cmds = [
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        # 表头样式
        ('BACKGROUND', (0, 0), (-1, 0), THEME_BG_HEADER),
        ('FONTNAME', (0, 0), (-1, -1), FONT_NAME),
        # 边框
        ('GRID', (0, 0), (-1, -1), 0.5, THEME_BORDER),
    ]
    # 隔行变色
    for i in range(1, len(table_rows)):
        if i % 2 == 0:
            table_style_cmds.append(('BACKGROUND', (0, i), (-1, i), THEME_BG_LIGHT))

    summary_table.setStyle(TableStyle(table_style_cmds))
    return summary_table


def _build_event_detail_block(event, updates, index):
    """
    构建单条事件详情卡片。
    返回独立的 flowable 列表（不嵌套包装），允许自然分页。
    用顶部彩色粗线 + 浅色表头区代替左侧色条卡片效果。
    """
    severity_map = {'P0': 'P0 紧急', 'P1': 'P1 重要', 'P2': 'P2 一般'}
    status_map = {'in_progress': '处理中', 'resolved': '已解决'}

    severity_text = severity_map.get(event.get('severity', ''), event.get('severity', '-'))
    severity_color = _get_severity_color(event.get('severity'))
    status_text = status_map.get(event.get('status', ''), event.get('status_text', '-'))
    status_color = _get_status_color(event.get('status'))

    # ===== 宽度（直接用于 story，无需嵌套） =====
    content_w = PAGE_USABLE_WIDTH - 4  # 4pt 安全边距

    header_left_w = content_w - 6.0 * cm
    header_right_w = 6.0 * cm

    label_w = 2.8 * cm
    value_w = (content_w - 2 * label_w) / 2

    elements = []

    # 1. 顶部彩色粗线（severity 色条替代）
    elements.append(HRFlowable(
        width='100%', thickness=3, color=severity_color,
        spaceBefore=10, spaceAfter=0
    ))

    # 2. 头部信息栏（浅色背景）
    header_left = Paragraph(
        f'<b>事件 {index}</b>　'
        f'<font color="{severity_color.hexval()}">[{_safe(severity_text)}]</font>　'
        f'<font color="{status_color.hexval()}">[{_safe(status_text)}]</font>',
        ParagraphStyle('EventHeader', fontName=FONT_NAME, fontSize=11,
                       alignment=0, leading=18, textColor=THEME_TEXT)
    )
    header_right = Paragraph(
        _safe(event.get('created_at')),
        ParagraphStyle('EventTime', fontName=FONT_NAME, fontSize=9,
                       alignment=2, leading=18, textColor=THEME_TEXT_SECONDARY)
    )

    header_table = Table(
        [[header_left, header_right]],
        colWidths=[header_left_w, header_right_w]
    )
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('BACKGROUND', (0, 0), (-1, -1), THEME_BG_LIGHT),
    ]))
    elements.append(header_table)

    # 3. 事件标题
    if event.get('event_title'):
        elements.append(Paragraph(
            f'标题：{_safe(event["event_title"])}',
            ParagraphStyle('EventTitle', fontName=FONT_NAME, fontSize=10,
                           alignment=0, leading=16, spaceBefore=4,
                           textColor=THEME_TEXT)
        ))

    # 4. 事件基本信息表格
    detail_rows = [
        [_label('事件类型'), _value(event.get('event_type')),
         _label('关联系统'), _value(event.get('system_name'))],
        [_label('事件级别'), _severity_tag(event.get('severity')),
         _label('责任人'), _value(event.get('responsible_user_name'))],
        [_label('当前状态'), _status_tag(event.get('status')),
         _label('动态数量'), _value(str(event.get('update_count', 0)))],
    ]

    detail_table = Table(detail_rows, colWidths=[label_w, value_w, label_w, value_w])
    detail_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('BACKGROUND', (0, 0), (0, -1), THEME_BG_LIGHT),
        ('BACKGROUND', (2, 0), (2, -1), THEME_BG_LIGHT),
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.3, THEME_BORDER),
        ('FONTNAME', (0, 0), (-1, -1), FONT_NAME),
    ]))
    elements.append(Spacer(1, 4))
    elements.append(detail_table)

    # 5. 处理措施（已解决时显示）
    if event.get('resolution'):
        elements.append(Spacer(1, 6))
        resolution_label = Paragraph(
            '处理措施：',
            ParagraphStyle('ResLabel', fontName=FONT_NAME, fontSize=9,
                           alignment=0, leading=14, textColor=THEME_TEXT_SECONDARY)
        )
        elements.append(resolution_label)
        elements.append(Paragraph(_safe(event['resolution']), _content_style()))

    # 6. 动态记录
    if updates:
        elements.append(Spacer(1, 6))
        updates_label = Paragraph(
            f'动态记录（{len(updates)}条）：',
            ParagraphStyle('UpdatesLabel', fontName=FONT_NAME, fontSize=9,
                           alignment=0, leading=14, textColor=THEME_TEXT_SECONDARY)
        )
        elements.append(updates_label)

        for u_idx, update in enumerate(updates):
            update_items = _build_update_block(update, u_idx + 1)
            elements.extend(update_items)
            if u_idx < len(updates) - 1:
                elements.append(Spacer(1, 4))
    elif event.get('update_count', 0) == 0:
        elements.append(Spacer(1, 6))
        elements.append(Paragraph('暂无动态记录', _empty_style()))

    # 7. 底部细线
    elements.append(HRFlowable(
        width='100%', thickness=0.5, color=THEME_BORDER,
        spaceBefore=6, spaceAfter=4
    ))

    return elements


def _build_update_block(update, seq_index):
    """构建单条动态记录（使用 Paragraph + leftIndent，避免单行 Table 不可分页）"""
    update_color = THEME_PRIMARY if seq_index == 1 else THEME_BORDER

    # 动态头部：日期 + 序号 + 记录人
    header = Paragraph(
        f'<font color="{update_color.hexval()}">■</font> '
        f'#{seq_index}　'
        f'{_safe(update.get("update_date"))}　'
        f'记录人：{_safe(update.get("recorder"))}',
        ParagraphStyle('UpdateHeader', fontName=FONT_NAME, fontSize=9,
                       alignment=0, leading=14, textColor=THEME_TEXT,
                       leftIndent=8)
    )

    elements = [header]

    # 详细内容
    content = update.get('detail_content', '')
    if content:
        elements.append(Paragraph(
            _safe(content),
            ParagraphStyle('UpdateContent', parent=_content_style(),
                           leftIndent=8)
        ))

    return elements

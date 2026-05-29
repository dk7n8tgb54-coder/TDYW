# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
值班日志PDF导出模块
生成包含值班记录列表 + 值班情况详情的PDF文档
"""

import os
import logging
from io import BytesIO
from datetime import datetime

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
                logger.info(f'Duty PDF: Registered font {fp}')
                return True
            except Exception as e:
                logger.warning(f'Duty PDF: Failed to register font {fp}: {e}')

    logger.warning('Duty PDF: No Chinese font found, text may display incorrectly')
    return False


# ============ 颜色主题 ============

THEME_PRIMARY = colors.HexColor('#1890ff')
THEME_PRIMARY_DARK = colors.HexColor('#096dd9')
THEME_BG_LIGHT = colors.HexColor('#fafafa')
THEME_BG_HEADER = colors.HexColor('#e6f7ff')
THEME_BORDER = colors.HexColor('#d9d9d9')
THEME_TEXT = colors.HexColor('#333333')
THEME_TEXT_SECONDARY = colors.HexColor('#666666')
THEME_WHITE = colors.white


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


# ============ 辅助函数 ============

def _label(text):
    return Paragraph(f'{text}：', _label_cell_style())


def _value(text):
    if not text or text == 'None':
        text = '-'
    display_text = str(text)
    if len(display_text) > 500:
        display_text = display_text[:500] + '...'
    return Paragraph(display_text, _cell_style(alignment=0))


# ============ PDF 构建 ============

def generate_duty_log_pdf(records, date_range_text=''):
    """
    生成值班日志PDF文档

    Args:
        records: list[dict] - 值班记录列表
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
    story.append(Paragraph('值班日志', _title_style()))

    # 导出信息
    export_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    subtitle_parts = [f'导出时间：{export_time}']
    if date_range_text:
        subtitle_parts.append(f'日期范围：{date_range_text}')
    subtitle_parts.append(f'共 {len(records)} 条记录')
    story.append(Paragraph('　|　'.join(subtitle_parts), _subtitle_style()))

    # 分隔线
    story.append(HRFlowable(
        width='100%', thickness=1.5, color=THEME_PRIMARY,
        spaceAfter=12, spaceBefore=4
    ))

    # ---- 值班记录汇总表 ----
    story.append(Paragraph('值班记录汇总', _section_title_style()))

    if not records:
        story.append(Paragraph('暂无值班记录', _empty_style()))
    else:
        # 汇总表格
        header_row = [
            Paragraph('序号', _cell_style(alignment=1, font_size=9)),
            Paragraph('值班人员', _cell_style(alignment=1, font_size=9)),
            Paragraph('所属科室', _cell_style(alignment=1, font_size=9)),
            Paragraph('值班日期', _cell_style(alignment=1, font_size=9)),
            Paragraph('填报人', _cell_style(alignment=1, font_size=9)),
            Paragraph('创建时间', _cell_style(alignment=1, font_size=9)),
        ]

        table_rows = [header_row]
        for idx, record in enumerate(records):
            row = [
                Paragraph(str(idx + 1), _cell_style(alignment=1)),
                Paragraph(str(record.get('duty_person', '-')), _cell_style()),
                Paragraph(str(record.get('department', '-')), _cell_style()),
                Paragraph(str(record.get('duty_date', '-')), _cell_style(alignment=1)),
                Paragraph(str(record.get('reporter', '-')), _cell_style()),
                Paragraph(str(record.get('created_at', '-')), _cell_style()),
            ]
            table_rows.append(row)

        col_widths = [1.2 * cm, 3.0 * cm, 3.0 * cm, 3.0 * cm, 2.5 * cm, 4.3 * cm]
        summary_table = Table(table_rows, colWidths=col_widths)

        table_style_cmds = [
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            # 表头样式
            ('BACKGROUND', (0, 0), (-1, 0), THEME_BG_HEADER),
            ('FONTNAME', (0, 0), (-1, -1), FONT_NAME),
            # 边框
            ('GRID', (0, 0), (-1, -1), 0.5, THEME_BORDER),
            # 隔行变色
        ]
        # 隔行变色
        for i in range(1, len(table_rows)):
            if i % 2 == 0:
                table_style_cmds.append(('BACKGROUND', (0, i), (-1, i), THEME_BG_LIGHT))

        summary_table.setStyle(TableStyle(table_style_cmds))
        story.append(summary_table)

    # ---- 各条值班情况详情 ----
    story.append(Spacer(1, 16))
    story.append(Paragraph('值班情况详情', _section_title_style()))

    if not records:
        story.append(Paragraph('暂无值班情况', _empty_style()))
    else:
        for idx, record in enumerate(records):
            block = _build_duty_record_block(record, idx + 1)
            story.append(KeepTogether(block))
            if idx < len(records) - 1:
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


def _build_duty_record_block(record, index):
    """构建单条值班记录卡片"""

    # 卡片头部：序号 + 值班人员 + 日期
    header_left = Paragraph(
        f'<b>记录 {index}</b>　'
        f'<font color="{THEME_PRIMARY.hexval()}">【{record.get("duty_person", "-")}】</font>'
        f'　{record.get("duty_date", "-")}',
        ParagraphStyle('RecordHeader', fontName=FONT_NAME, fontSize=11,
                       alignment=0, leading=18, textColor=THEME_TEXT)
    )
    header_right = Paragraph(
        record.get('department', '-'),
        ParagraphStyle('RecordDept', fontName=FONT_NAME, fontSize=9,
                       alignment=2, leading=18, textColor=THEME_TEXT_SECONDARY)
    )

    header_table = Table(
        [[header_left, header_right]],
        colWidths=[12 * cm, 5 * cm]
    )
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))

    elements = [header_table]

    # 详情表格
    detail_rows = [
        [_label('值班人员'), _value(record.get('duty_person')),
         _label('填报人'), _value(record.get('reporter'))],
        [_label('所属科室'), _value(record.get('department')),
         _label('值班日期'), _value(record.get('duty_date'))],
    ]

    detail_table = Table(detail_rows, colWidths=[3.0 * cm, 5.5 * cm, 3.0 * cm, 5.5 * cm])
    detail_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (0, -1), THEME_BG_LIGHT),
        ('BACKGROUND', (2, 0), (2, -1), THEME_BG_LIGHT),
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.3, THEME_BORDER),
        ('FONTNAME', (0, 0), (-1, -1), FONT_NAME),
    ]))
    elements.append(Spacer(1, 4))
    elements.append(detail_table)

    # 值班情况
    duty_situation = record.get('duty_situation', '')
    if duty_situation:
        elements.append(Spacer(1, 6))
        situation_label = Paragraph(
            '值班情况：',
            ParagraphStyle('SituationLabel', fontName=FONT_NAME, fontSize=9,
                           alignment=0, leading=14, textColor=THEME_TEXT_SECONDARY)
        )
        elements.append(situation_label)
        elements.append(Paragraph(duty_situation, _content_style()))

    # 整体包裹：左侧色条 + 内容区
    color_bar = Paragraph('', ParagraphStyle('ColorBar', fontSize=1, leading=1))

    content_cell = Table([[e] for e in elements], colWidths=[16.5 * cm])
    content_cell.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))

    outer = Table(
        [[color_bar, content_cell]],
        colWidths=[3 * mm, 16.8 * cm]
    )
    outer.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        # 左侧色条
        ('BACKGROUND', (0, 0), (0, 0), THEME_PRIMARY),
        # 右侧内容区
        ('BACKGROUND', (1, 0), (1, 0), THEME_BG_LIGHT),
        ('BOX', (0, 0), (-1, -1), 0.5, THEME_BORDER),
        # 内容区内边距
        ('LEFTPADDING', (1, 0), (1, 0), 10),
        ('RIGHTPADDING', (1, 0), (1, 0), 10),
        ('TOPPADDING', (1, 0), (1, 0), 8),
        ('BOTTOMPADDING', (1, 0), (1, 0), 8),
    ]))

    return [outer]

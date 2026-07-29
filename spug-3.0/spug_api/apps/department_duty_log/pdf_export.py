# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""部门值班日志 - PDF 导出

使用 ReportLab 生成包含值班记录、签署信息、固定版本签名图片的 PDF。
仅用于对系统签署证据的可读归档输出，不是法定可靠电子签名凭证。

设计原则（用户反馈 2026-07-19）：
- 黑白配色，不使用彩色主题；
- 每条值班日志独占一整页，无论内容多少。

注意：
- 签名图片由调用方（services.export_pdf）通过签名公共服务的固定版本接口
  完整校验 SHA256 后传入物理路径，本模块只负责排版渲染；
- 长文本使用 Paragraph 自动换行，并对用户输入做 XML 转义；
- 签名图片等比例缩放至最大宽度 6cm。
"""
import logging
import os
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    HRFlowable, Image, KeepTogether, PageBreak, Paragraph,
    SimpleDocTemplate, Spacer, Table, TableStyle,
)
from libs.font_manager import FontManager, FONT_NAME

logger = logging.getLogger(__name__)


# ============ 颜色主题（黑白） ============

THEME_BLACK = colors.black
THEME_DARK = colors.HexColor('#1a1a1a')
THEME_GRAY = colors.HexColor('#666666')
THEME_LIGHT_GRAY = colors.HexColor('#cccccc')
THEME_BG_GRAY = colors.HexColor('#f0f0f0')
THEME_WHITE = colors.white


# ============ Paragraph 样式 ============

def _title_style():
    return ParagraphStyle(
        'DocTitle', fontName=FONT_NAME, fontSize=18,
        alignment=1, spaceAfter=4, spaceBefore=0,
        textColor=THEME_BLACK, leading=26,
    )


def _page_title_style():
    """每页顶部的文档标题样式。"""
    return ParagraphStyle(
        'PageTitle', fontName=FONT_NAME, fontSize=16,
        alignment=1, spaceAfter=10, spaceBefore=0,
        textColor=THEME_BLACK, leading=24,
    )


def _subtitle_style():
    return ParagraphStyle(
        'DocSubtitle', fontName=FONT_NAME, fontSize=10,
        alignment=1, spaceAfter=12, spaceBefore=0,
        textColor=THEME_GRAY, leading=16,
    )


def _section_title_style():
    return ParagraphStyle(
        'SectionTitle', fontName=FONT_NAME, fontSize=13,
        alignment=0, spaceAfter=8, spaceBefore=16,
        textColor=THEME_BLACK, leading=20,
    )


def _cell_style(alignment=0, font_size=12):
    return ParagraphStyle(
        f'Cell_{alignment}_{font_size}',
        fontName=FONT_NAME, fontSize=font_size,
        alignment=alignment, leading=18,
        wordWrap='CJK',
        textColor=THEME_DARK,
    )


def _label_cell_style():
    return ParagraphStyle(
        'LabelCell', fontName=FONT_NAME, fontSize=12,
        alignment=2, leading=18, wordWrap='CJK',
        textColor=THEME_GRAY,
    )


def _left_label_style():
    return ParagraphStyle(
        'LeftLabel', fontName=FONT_NAME, fontSize=12,
        alignment=0, leading=18, wordWrap='CJK',
        textColor=THEME_GRAY,
    )


def _empty_style():
    return ParagraphStyle(
        'Empty', fontName=FONT_NAME, fontSize=10,
        alignment=1, leading=16,
        textColor=THEME_GRAY,
    )


def _content_style():
    return ParagraphStyle(
        'Content', fontName=FONT_NAME, fontSize=12,
        alignment=0, leading=18,
        wordWrap='CJK',
        textColor=THEME_DARK,
        spaceBefore=4,
        spaceAfter=4,
    )


def _footer_style():
    return ParagraphStyle(
        'Footer', fontName=FONT_NAME, fontSize=7,
        alignment=1, textColor=THEME_GRAY,
    )


# ============ 辅助：XML 转义 + 长文本截断 ============

def _escape(text):
    """对用户输入做 XML 转义，避免破坏 Paragraph 解析。换行转为 <br/>。"""
    if text is None:
        return ''
    s = str(text)
    s = s.replace('\r\n', '\n').replace('\r', '\n')
    # 按行分割后逐行转义，避免转义 <br/> 中的 <>
    lines = s.split('\n')
    escaped_lines = []
    for line in lines:
        e = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        escaped_lines.append(e)
    return '<br/>'.join(escaped_lines)


def _short(text, max_len=200):
    """长文本截断（用于汇总表和 SHA256 等长字符串显示）。"""
    if text is None:
        return ''
    s = str(text)
    if len(s) > max_len:
        return s[:max_len] + '...'
    return s


def _label(text):
    return Paragraph(f'{text}：', _label_cell_style())


def _value(text):
    if text is None or text == '' or str(text) == 'None':
        text = '-'
    return Paragraph(_escape(text), _cell_style(alignment=0))


# ============ 签名图片等比例缩放 ============

def _build_signature_image(file_path, max_width_cm=6.0, max_height_cm=3.0):
    """读取 PNG 文件并等比例缩放到最大宽度/高度，返回 reportlab Image 或 None。"""
    if not file_path or not os.path.exists(file_path):
        return None
    try:
        from PIL import Image as PILImage
        with PILImage.open(file_path) as img:
            iw, ih = img.size
    except Exception:
        # PIL 不可用时使用默认比例
        iw, ih = 200, 100

    max_w = max_width_cm * cm
    max_h = max_height_cm * cm
    ratio = min(max_w / iw, max_h / ih, 1.0)
    w = iw * ratio
    h = ih * ratio
    try:
        return Image(file_path, width=w, height=h)
    except Exception:
        logger.warning('[DepartmentDutyLog PDF] build signature image failed: %s', file_path, exc_info=True)
        return None


# ============ 单条记录卡片（独占一页） ============

def _build_record_block(record, signature_image, index):
    """构建单条值班记录的 PDF block。

    每条记录独占一整页（由调用方在 block 之间插入 PageBreak 实现）。

    Args:
        record: dict，由 services 层序列化的记录（含签署信息）
        signature_image: reportlab.platypus.Image 或 None（已校验 SHA256 的固定版本签名）
        index: 序号（从 1 开始，预留）
    """
    is_signed = record.get('status') == 'signed'

    elements = []

    # 页面标题
    elements.append(Paragraph('部门值班日志', _page_title_style()))

    # 详情表格
    if is_signed:
        sig_cell = _value('-')
        if signature_image is not None:
            file_path = getattr(signature_image, 'filename', None)
            if file_path:
                small_img = _build_signature_image(file_path, max_width_cm=4.0, max_height_cm=1.5)
                if small_img:
                    sig_cell = small_img
            else:
                sig_cell = signature_image
        detail_rows = [
            [_label('值班人员'), _value(record.get('duty_person_name')),
             _label('值班日期'), _value(record.get('duty_date'))],
            [_label('天气情况'), _value(record.get('weather')),
             _label('电子签名'), sig_cell],
        ]
    else:
        detail_rows = [
            [_label('值班人员'), _value(record.get('duty_person_name')),
             _label('值班日期'), _value(record.get('duty_date'))],
            [_label('天气情况'), _value(record.get('weather')), '', ''],
        ]

    detail_table = Table(detail_rows, colWidths=[3.0 * cm, 5.5 * cm, 3.0 * cm, 5.5 * cm])
    table_style_cmds = [
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (0, -1), THEME_BG_GRAY),
        ('BACKGROUND', (2, 0), (2, -1), THEME_BG_GRAY),
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
    ]
    # 未签时天气值跨第1-3列
    if not is_signed:
        table_style_cmds.append(('SPAN', (1, 1), (3, 1)))
        table_style_cmds.append(('BACKGROUND', (2, 1), (3, 1), colors.white))
    table_style_cmds.append(('GRID', (0, 0), (-1, -1), 0.3, THEME_LIGHT_GRAY))
    table_style_cmds.append(('FONTNAME', (0, 0), (-1, -1), FONT_NAME))
    detail_table.setStyle(TableStyle(table_style_cmds))
    elements.append(Spacer(1, 4))
    elements.append(detail_table)

    # 值班记录全文
    duty_record = record.get('duty_record') or ''
    if duty_record:
        elements.append(Spacer(1, 6))
        elements.append(Paragraph('值班记录：', _left_label_style()))
        elements.append(Paragraph(_escape(duty_record), _content_style()))

    # 上级工作要求（始终显示标签，左对齐，空值显示"无"）
    remark = record.get('remark') or ''
    elements.append(Spacer(1, 4))
    elements.append(Paragraph('上级工作要求：', _left_label_style()))
    elements.append(Paragraph(_escape(remark) if remark else '无', _content_style()))

    return elements


# ============ 主入口：generate_department_duty_log_pdf ============

def generate_department_duty_log_pdf(records, *, exporter_name, filters_text,
                                      signature_images):
    """生成部门值班日志 PDF。

    布局：
    - 每页一条值班记录，页面顶部为"部门值班日志"标题；
    - 详情表格含值班人员、日期、天气、电子签名等信息。

    Args:
        records: list[dict]，每条包含完整业务字段+签署字段。
                 已按 duty_date 升序排列（从早到晚）。
        exporter_name: 导出人姓名
        filters_text: 筛选条件描述（用于副标题）
        signature_images: dict[int, reportlab.Image 或 None]，
                          key=record id，value=已校验的固定版本签名图片；
                          缺失 key 视为该记录无可用签名图片。

    Returns:
        BytesIO: PDF 文件流（指针已 seek(0)）
    """
    FontManager.register_chinese_font(debug_logger=logger.debug)

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

    if not records:
        story.append(Paragraph('暂无值班记录', _empty_style()))
    else:
        # ---- 各条值班情况详情：每条独占一整页 ----
        for idx, record in enumerate(records):
            sig_img = signature_images.get(record.get('id'))
            block_elements = _build_record_block(record, sig_img, idx + 1)

            # 第一条记录前不加 PageBreak（首页已删除），后续记录前加 PageBreak
            if idx > 0:
                story.append(PageBreak())

            for elem in block_elements:
                story.append(elem)

    doc.build(story)
    output.seek(0)
    return output

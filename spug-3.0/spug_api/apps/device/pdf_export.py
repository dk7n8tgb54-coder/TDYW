# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
设备履历PDF导出模块
生成包含设备基础信息 + 事件记录的精美PDF文档
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
    HRFlowable, KeepTogether
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
                logger.info(f'Device PDF: Registered font {fp}')
                return True
            except Exception as e:
                logger.warning(f'Device PDF: Failed to register font {fp}: {e}')

    logger.warning('Device PDF: No Chinese font found, text may display incorrectly')
    return False


# ============ 样式定义 ============

# 颜色主题
THEME_PRIMARY = colors.HexColor('#1890ff')       # 主色调 - 蓝
THEME_PRIMARY_DARK = colors.HexColor('#096dd9')   # 深蓝
THEME_SUCCESS = colors.HexColor('#52c41a')        # 正常 - 绿
THEME_ERROR = colors.HexColor('#ff4d4f')          # 故障 - 红
THEME_WARNING = colors.HexColor('#faad14')        # 维修中 - 橙
THEME_GRAY = colors.HexColor('#999999')           # 停用/报废 - 灰
THEME_BG_LIGHT = colors.HexColor('#fafafa')       # 浅背景
THEME_BG_HEADER = colors.HexColor('#e6f7ff')      # 表头背景 - 浅蓝
THEME_BORDER = colors.HexColor('#d9d9d9')         # 边框色
THEME_TEXT = colors.HexColor('#333333')            # 正文色
THEME_TEXT_SECONDARY = colors.HexColor('#666666')  # 次要文字
THEME_WHITE = colors.white                         # 白色


def _get_status_style(status):
    """根据设备状态返回颜色"""
    status_colors = {
        '1': THEME_SUCCESS,
        '2': THEME_ERROR,
        '3': THEME_WARNING,
        '4': THEME_GRAY,
        '5': THEME_GRAY,
    }
    return status_colors.get(str(status), THEME_GRAY)


def _get_event_type_color(event_type):
    """根据事件类型返回颜色"""
    event_colors = {
        1: THEME_ERROR,      # 重大故障维修 - 红
        2: THEME_WARNING,    # 设备更新 - 橙
        3: THEME_PRIMARY,    # 设备检修 - 蓝
    }
    return event_colors.get(event_type, THEME_GRAY)


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


# ============ PDF 构建 ============

def generate_device_resume_pdf(device_info, events, operator_name=None):
    """
    生成设备履历PDF文档

    Args:
        device_info: dict - 设备基础信息
        events: list[dict] - 事件列表
        operator_name: str - 导出人姓名（由后端从 request.user 注入，不信任前端传入）

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
    story.append(Paragraph('设备履历报告', _title_style()))

    # 导出时间 + 导出人
    export_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    if operator_name:
        subtitle_text = f'导出时间：{export_time}　导出人：{operator_name}'
    else:
        subtitle_text = f'导出时间：{export_time}'
    story.append(Paragraph(subtitle_text, _subtitle_style()))

    # 分隔线
    story.append(HRFlowable(
        width='100%', thickness=1.5, color=THEME_PRIMARY,
        spaceAfter=12, spaceBefore=4
    ))

    # ---- 设备基础信息 ----
    story.append(Paragraph('设备基础信息', _section_title_style()))
    story.append(_build_device_info_table(device_info))
    story.append(Spacer(1, 16))

    # ---- 设备扩展信息 ----
    story.append(Paragraph('设备扩展信息', _section_title_style()))
    story.append(_build_device_extended_table(device_info))
    story.append(Spacer(1, 16))

    # ---- 事件记录 ----
    story.append(Paragraph('设备全生命周期履历', _section_title_style()))

    if not events:
        story.append(Paragraph('暂无履历事件记录', _empty_style()))
    else:
        for idx, event in enumerate(events):
            event_block = _build_event_block(event, idx + 1)
            story.append(KeepTogether(event_block))
            if idx < len(events) - 1:
                story.append(Spacer(1, 8))

    # ---- 页脚信息 ----
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


def _build_device_info_table(device_info):
    """构建设备基础信息表格 - 两列标签+值的精美布局"""

    status_map = {'1': '正常', '2': '故障', '3': '维修中', '4': '停用', '5': '报废'}
    status_text = status_map.get(str(device_info.get('current_status', '')), '未知')
    status_color = _get_status_style(device_info.get('current_status'))

    # 使用 Paragraph 渲染带颜色的状态标签
    status_para = Paragraph(
        f'<font color="{status_color.hexval()}">● {status_text}</font>',
        _cell_style(alignment=0, font_size=10, bold=True)
    )

    rows = [
        [_label('设备资产编号'), _value(device_info.get('device_sn', '-')),
         _label('设备名称'), _value(device_info.get('device_name', '-'))],
        [_label('设备型号'), _value(device_info.get('device_model', '-')),
         _label('工作频率'), _value(device_info.get('frequency') or '-')],
        [_label('设备呼号'), _value(device_info.get('call_sign') or '-'),
         _label('安装地点'), _value(device_info.get('install_location', '-'))],
        [_label('当前设备状况'), status_para,
         _label('设备负责人'), _value(device_info.get('responsible_user_name') or '-')],
        [_label('安装时间'), _value(device_info.get('install_time', '-')),
         _label('启用时间'), _value(device_info.get('enable_time', '-'))],
    ]

    col_widths = [3.2 * cm, 5.3 * cm, 3.2 * cm, 5.3 * cm]
    table = Table(rows, colWidths=col_widths)
    table.setStyle(TableStyle([
        # 全局
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        # 标签列背景
        ('BACKGROUND', (0, 0), (0, -1), THEME_BG_LIGHT),
        ('BACKGROUND', (2, 0), (2, -1), THEME_BG_LIGHT),
        # 标签列右对齐
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
        # 边框
        ('GRID', (0, 0), (-1, -1), 0.5, THEME_BORDER),
        ('LINEBELOW', (0, 0), (-1, -2), 0.3, THEME_BORDER),
        # 标签列字体
        ('FONTNAME', (0, 0), (-1, -1), FONT_NAME),
    ]))

    return table


def _build_device_extended_table(device_info):
    """构建设备扩展信息表格"""

    rows = [
        [_label('安装经纬度'), _value(device_info.get('geo_coordinate') or '-'),
         _label('设备用途'), _value(device_info.get('device_purpose') or '-')],
        [_label('生产厂家'), _value(device_info.get('manufacturer', '-')),
         _label('安装单位'), _value(device_info.get('install_unit', '-'))],
        [_label('使用单位'), _value(device_info.get('use_unit', '-')),
         _label('备注'), _value(device_info.get('remark') or '-')],
        [_label('档案创建时间'), _value(device_info.get('created_at', '-')),
         _label('最后更新时间'), _value(device_info.get('updated_at') or '-')],
    ]

    col_widths = [3.2 * cm, 5.3 * cm, 3.2 * cm, 5.3 * cm]
    table = Table(rows, colWidths=col_widths)
    table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (0, -1), THEME_BG_LIGHT),
        ('BACKGROUND', (2, 0), (2, -1), THEME_BG_LIGHT),
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
        ('GRID', (0, 0), (-1, -1), 0.5, THEME_BORDER),
        ('FONTNAME', (0, 0), (-1, -1), FONT_NAME),
    ]))

    return table


def _build_event_block(event, index):
    """构建单个事件卡片 - 时间线风格"""

    event_type_map = {1: '重大故障维修', 2: '设备更新', 3: '设备检修'}
    event_type_text = event_type_map.get(event.get('event_type'), '未知')
    event_color = _get_event_type_color(event.get('event_type'))

    # 事件头部：序号 + 类型标签 + 标题
    header_left = Paragraph(
        f'<font color="{event_color.hexval()}">■</font> '
        f'<b>事件 {index}</b>　'
        f'<font color="{event_color.hexval()}">[{event_type_text}]</font>',
        ParagraphStyle('EventHeader', fontName=FONT_NAME, fontSize=11,
                       alignment=0, leading=18, textColor=THEME_TEXT)
    )
    header_right = Paragraph(
        f'{event.get("event_time", "-")}',
        ParagraphStyle('EventTime', fontName=FONT_NAME, fontSize=9,
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

    # 事件标题
    if event.get('event_title'):
        elements.append(Paragraph(
            f'标题：{event["event_title"]}',
            ParagraphStyle('EventTitle', fontName=FONT_NAME, fontSize=10,
                           alignment=0, leading=16, spaceBefore=4,
                           textColor=THEME_TEXT)
        ))

    # 事件详情表格
    detail_rows = []

    # 关联人
    detail_rows.append(
        [_label('关联人'), _value(event.get('related_user_name') or '-')]
    )

    # 故障件（仅检修类型显示）
    if event.get('fault_part'):
        detail_rows.append(
            [_label('故障件'), _value(event['fault_part'])]
        )

    # 故障现象及原因
    if event.get('fault_phenomenon_cause'):
        detail_rows.append(
            [_label('故障现象及原因'), _value(event['fault_phenomenon_cause'])]
        )

    # 检修措施/简要情况
    if event.get('maintenance_measures'):
        detail_rows.append(
            [_label('检修措施'), _value(event['maintenance_measures'])]
        )

    # 修复时间
    if event.get('repair_time'):
        detail_rows.append(
            [_label('修复时间'), _value(event['repair_time'])]
        )

    # 备注
    if event.get('remark'):
        detail_rows.append(
            [_label('备注'), _value(event['remark'])]
        )

    if detail_rows:
        detail_table = Table(detail_rows, colWidths=[3.5 * cm, 13.5 * cm])
        detail_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
            ('RIGHTPADDING', (0, 0), (-1, -1), 8),
            ('BACKGROUND', (0, 0), (0, -1), THEME_BG_LIGHT),
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('GRID', (0, 0), (-1, -1), 0.3, THEME_BORDER),
            ('FONTNAME', (0, 0), (-1, -1), FONT_NAME),
        ]))
        elements.append(Spacer(1, 4))
        elements.append(detail_table)

    # 整体包裹：左侧色条 + 内容区
    # 使用一个窄列（3mm）作为彩色装饰条
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
        # 左侧色条：用背景色填充窄列
        ('BACKGROUND', (0, 0), (0, 0), event_color),
        # 右侧内容区：浅灰背景+边框
        ('BACKGROUND', (1, 0), (1, 0), THEME_BG_LIGHT),
        ('BOX', (0, 0), (-1, -1), 0.5, THEME_BORDER),
        # 内容区内边距
        ('LEFTPADDING', (1, 0), (1, 0), 10),
        ('RIGHTPADDING', (1, 0), (1, 0), 10),
        ('TOPPADDING', (1, 0), (1, 0), 8),
        ('BOTTOMPADDING', (1, 0), (1, 0), 8),
    ]))

    return [outer]


# ============ 辅助函数 ============

def _label(text):
    """创建标签单元格"""
    return Paragraph(f'{text}：', _label_cell_style())


def _value(text):
    """创建值单元格"""
    if not text or text == 'None':
        text = '-'
    # 对长文本做截断保护，避免超长内容撑破表格
    display_text = str(text)
    if len(display_text) > 200:
        display_text = display_text[:200] + '...'
    return Paragraph(display_text, _cell_style(alignment=0))

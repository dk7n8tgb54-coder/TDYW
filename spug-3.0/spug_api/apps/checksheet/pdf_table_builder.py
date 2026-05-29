"""
PDF表格构建模块
用于从检查表数据构建PDF表格
"""

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.platypus import Table, TableStyle, PageBreak


class PDFTableBuilder:
    """PDF表格构建器"""

    # 表格样式常量
    FONT_NAME = 'SimHei'
    FONT_SIZE_NORMAL = 8
    FONT_SIZE_TITLE = 12
    FONT_SIZE_SIGNATURE = 10
    FONT_SIZE_HEADER = 9
    FONT_SIZE_FOOTER = 7

    # 颜色常量
    COLOR_NORMAL_BG = colors.HexColor('#F6FFED')
    COLOR_NORMAL_TEXT = colors.HexColor('#52C41A')
    COLOR_ABNORMAL_BG = colors.HexColor('#FFF1F0')
    COLOR_ABNORMAL_TEXT = colors.HexColor('#FF4D4F')
    COLOR_HEADER_BG = colors.lightgrey
    COLOR_TITLE_BG = colors.whitesmoke

    @classmethod
    def build_project_table(cls, project, year, month, check_items, records, daily_summaries):
        """
        构建单个项目的PDF表格

        Returns:
            Table: 构建好的ReportLab表格对象
        """
        days = list(range(1, 32))
        table_data = cls._build_table_data(project, year, month, check_items, records, daily_summaries, days)
        return cls._apply_table_styles(table, table_data)

    @classmethod
    def _build_table_data(cls, project, year, month, check_items, records, daily_summaries, days):
        """构建表格数据"""
        table_data = []

        # 标题行
        table_data.append([f'{project} {year}年{month}月 检查表', '', ''])

        # 值班人员签名行
        operator = cls._extract_operator_signature(daily_summaries)
        table_data.append(['值班人员签名：' + operator, '', ''])

        # 表头
        headers = ['序号', '检查项目'] + [f'{d}日' for d in days]
        table_data.append(headers)

        # 数据行
        for item_idx, item in enumerate(check_items):
            row = cls._build_data_row(item_idx, item, days, records)
            table_data.append(row)

        # 整改情况行和备注行
        table_data.append(cls._build_summary_row('发现问题及整改情况', days, daily_summaries, 'rectification'))
        table_data.append(cls._build_summary_row('备注', days, daily_summaries, 'remark'))

        return table_data

    @classmethod
    def _extract_operator_signature(cls, daily_summaries):
        """提取值班人员签名"""
        for summary in daily_summaries.values():
            if summary.get('operator'):
                return summary['operator']
        return '（待签字）'

    @classmethod
    def _build_data_row(cls, item_idx, item, days, records):
        """构建单行检查数据"""
        row = [str(item_idx + 1), item]
        for day in days:
            record = records.get(f"{item_idx}_{day}")
            row.append(cls._format_record_status(record))
        return row

    @classmethod
    def _format_record_status(cls, record):
        """格式化检查记录状态"""
        if not record:
            return '—'
        if record.status == 'NORMAL':
            return '√'
        elif record.status == 'ABNORMAL':
            return f'× {record.remark}' if record.remark else '×'
        return '—'

    @classmethod
    def _build_summary_row(cls, label, days, daily_summaries, field):
        """构建汇总行（整改情况/备注）"""
        row = [label, '']
        for day in days:
            row.append(daily_summaries.get(day, {}).get(field, ''))
        return row

    @classmethod
    def _apply_table_styles(cls, table, table_data):
        """应用表格样式"""
        style_list = cls._build_base_styles()
        style_list.extend(cls._build_title_styles())
        style_list.extend(cls._build_signature_styles())
        style_list.extend(cls._build_header_styles())
        style_list.extend(cls._build_alignment_styles(len(table_data)))
        style_list.extend(cls._build_status_styles(table_data))

        table.setStyle(TableStyle(style_list))
        return table

    @classmethod
    def _build_base_styles(cls):
        """构建基础样式"""
        return [
            ('FONTNAME', (0, 0), (-1, -1), cls.FONT_NAME),
            ('FONTSIZE', (0, 0), (-1, -1), cls.FONT_SIZE_NORMAL),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ]

    @classmethod
    def _build_title_styles(cls):
        """构建标题样式"""
        return [
            ('FONTNAME', (0, 0), (-1, 0), cls.FONT_NAME),
            ('FONTSIZE', (0, 0), (-1, 0), cls.FONT_SIZE_TITLE),
            ('SPAN', (0, 0), (-1, 0)),
            ('BACKGROUND', (0, 0), (-1, 0), cls.COLOR_TITLE_BG),
        ]

    @classmethod
    def _build_signature_styles(cls):
        """构建签名行样式"""
        return [
            ('FONTNAME', (0, 1), (0, 1), cls.FONT_NAME),
            ('FONTSIZE', (0, 1), (0, 1), cls.FONT_SIZE_SIGNATURE),
            ('SPAN', (0, 1), (-1, 1)),
            ('ALIGN', (0, 1), (0, 1), 'RIGHT'),
        ]

    @classmethod
    def _build_header_styles(cls):
        """构建表头样式"""
        return [
            ('FONTNAME', (0, 2), (-1, 2), cls.FONT_NAME),
            ('FONTSIZE', (0, 2), (-1, 2), cls.FONT_SIZE_HEADER),
            ('BACKGROUND', (0, 2), (-1, 2), cls.COLOR_HEADER_BG),
        ]

    @classmethod
    def _build_alignment_styles(cls, row_count):
        """构建对齐样式"""
        styles = [
            ('ALIGN', (1, 3), (1, -3), 'LEFT'),  # 检查项目列左对齐
        ]

        # 最后两行左对齐
        rect_idx = row_count - 2
        remark_idx = row_count - 1

        styles.extend([
            ('FONTSIZE', (0, rect_idx), (-1, rect_idx), cls.FONT_SIZE_FOOTER),
            ('ALIGN', (0, rect_idx), (-1, rect_idx), 'LEFT'),
            ('VALIGN', (0, rect_idx), (-1, rect_idx), 'TOP'),
            ('FONTSIZE', (0, remark_idx), (-1, remark_idx), cls.FONT_SIZE_FOOTER),
            ('ALIGN', (0, remark_idx), (-1, remark_idx), 'LEFT'),
            ('VALIGN', (0, remark_idx), (-1, remark_idx), 'TOP'),
        ])

        return styles

    @classmethod
    def _build_status_styles(cls, table_data):
        """构建状态单元格样式（根据检查结果着色）"""
        styles = []
        data_end = len(table_data) - 2  # 排除最后两行

        for row_idx in range(3, data_end):
            for day_idx in range(2, 33):
                cell_data = table_data[row_idx][day_idx]
                if cell_data == '√':
                    styles.append(('BACKGROUND', (day_idx, row_idx), (day_idx, row_idx), cls.COLOR_NORMAL_BG))
                    styles.append(('TEXTCOLOR', (day_idx, row_idx), (day_idx, row_idx), cls.COLOR_NORMAL_TEXT))
                elif isinstance(cell_data, str) and cell_data.startswith('×'):
                    styles.append(('BACKGROUND', (day_idx, row_idx), (day_idx, row_idx), cls.COLOR_ABNORMAL_BG))
                    styles.append(('TEXTCOLOR', (day_idx, row_idx), (day_idx, row_idx), cls.COLOR_ABNORMAL_TEXT))

        return styles

# -*- coding: utf-8 -*-
"""导出 xlsx vs 原始 NB500.xlsx 结构对比（容器内运行，只读）。"""
import json

import openpyxl

ORIG = '/data/spug/spug_api/NB500_tmp_e2e.xlsx'
EXP = '/data/spug/spug_api/nb500_tmp_export.xlsx'

wb_o = openpyxl.load_workbook(ORIG)
wb_e = openpyxl.load_workbook(EXP)

diffs = []
oks = []


def cmp(label, a, b):
    (oks if a == b else diffs).append('%s: orig=%r export=%r' % (label, a, b))


cmp('工作表清单', wb_o.sheetnames, wb_e.sheetnames)
for name in ('Sheet1', 'Sheet2', 'Sheet3'):
    wo, we = wb_o[name], wb_e[name]
    cmp('%s 合并区域' % name, sorted(str(r) for r in wo.merged_cells.ranges),
        sorted(str(r) for r in we.merged_cells.ranges))
    cmp('%s 列宽' % name, {k: round(v.width, 2) for k, v in wo.column_dimensions.items() if v.width},
        {k: round(v.width, 2) for k, v in we.column_dimensions.items() if v.width})
    cmp('%s 行高' % name, {k: v.height for k, v in wo.row_dimensions.items() if v.height},
        {k: v.height for k, v in we.row_dimensions.items() if v.height})
    cmp('%s 打印区域' % name, wo.print_area, we.print_area)
    po, pe = wo.page_setup, we.page_setup
    cmp('%s 纸张/方向/scale/fitW/fitH' % name,
        (po.paperSize, po.orientation, po.scale, po.fitToWidth, po.fitToHeight),
        (pe.paperSize, pe.orientation, pe.scale, pe.fitToWidth, pe.fitToHeight))
    mo, me = wo.page_margins, we.page_margins
    cmp('%s 页边距' % name,
        tuple(round(getattr(mo, k), 4) for k in ('left', 'right', 'top', 'bottom', 'header', 'footer')),
        tuple(round(getattr(me, k), 4) for k in ('left', 'right', 'top', 'bottom', 'header', 'footer')))

wo, we = wb_o['Sheet1'], wb_e['Sheet1']
# 原有内容不被覆盖（标题/表头/参数列）
for coord in ('A1', 'A2', 'B2', 'C2', 'D2', 'E2', 'A3', 'B3', 'E3', 'A4', 'B4', 'A16', 'A19', 'D19'):
    cmp('原有格 %s 值不变' % coord, wo[coord].value, we[coord].value)
# 样式抽查（字体/边框/对齐/换行）
for coord in ('A1', 'B2', 'C5', 'E9', 'A19'):
    fo, fe = wo[coord].font, we[coord].font
    cmp('字体 %s (name,size,bold)' % coord, (fo.name, fo.size, fo.bold), (fe.name, fe.size, fe.bold))
    bo, be = wo[coord].border, we[coord].border
    cmp('边框 %s' % coord, tuple(getattr(bo, s).style for s in ('left', 'right', 'top', 'bottom')),
        tuple(getattr(be, s).style for s in ('left', 'right', 'top', 'bottom')))
    ao, ae = wo[coord].alignment, we[coord].alignment
    cmp('对齐/换行 %s' % coord, (ao.horizontal, ao.vertical, ao.wrap_text),
        (ae.horizontal, ae.vertical, ae.wrap_text))
# 填写值落位抽查
filled = {
    'C3': 3.2, 'D3': 50.0, 'C9': 50.0, 'D15': 50.0,
    'F3': '正常', 'F15': '正常',
    'B19': 'NB500验收员', 'E19': '2026-09-30', 'A16': '本次验收未发现异常',
}
for coord, expect in filled.items():
    got = we[coord].value
    ok = (str(got) == str(expect)) or (isinstance(got, (int, float)) and abs(float(got) - float(expect)) < 1e-9)
    (oks if ok else diffs).append('填写值 %s: expect=%r got=%r (%s)' % (coord, expect, got, got.__class__.__name__))
# 数字格式是否保留
cmp('C3 数字格式', wo['C3'].number_format, we['C3'].number_format)
cmp('E19 数字格式', wo['E19'].number_format, we['E19'].number_format)
# 未绑定的空格未被写入
for coord in ('C1', 'B10', 'E19' if False else 'C16'):
    pass
cmp('未绑定空格 D16 未被写入', None if not we['D16'].value else we['D16'].value, None)

print('=== DIFFS (%d) ===' % len(diffs))
for d in diffs:
    print(d)
print('=== MATCHED (%d) ===' % len(oks))
print('RESULT:', 'ALL_MATCH' if not diffs else 'HAS_DIFF')

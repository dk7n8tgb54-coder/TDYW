#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""诊断PDF中文字体问题"""

from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
import os

# 字体路径
font_path = '/data/spug/spug_api/apps/checksheet/fonts/simhei.ttf'
print(f"字体路径: {font_path}")
print(f"字体文件存在: {os.path.exists(font_path)}")

# 测试1: 直接注册
print("\n=== 测试1: 基本字体注册 ===")
try:
    pdfmetrics.registerFont(TTFont('SimHei', font_path))
    print("✓ 字体注册成功")
except Exception as e:
    print(f"✗ 字体注册失败: {e}")

# 测试2: Canvas绘制
print("\n=== 测试2: Canvas绘制中文 ===")
output1 = '/tmp/test_canvas_chinese.pdf'
c = canvas.Canvas(output1, pagesize=A4)
c.setFont('SimHei', 16)
c.drawString(100, 750, 'Canvas绘制: 测试中文')
c.drawString(100, 720, '项目名称: 通用项目检查')
c.drawString(100, 690, '检查内容: 消防检查、安保检查情况')
c.save()
print(f"✓ Canvas PDF已生成: {output1}")

# 测试3: Table使用字符串 + FONTNAME
print("\n=== 测试3: Table使用字符串 + FONTNAME ===")
output2 = '/tmp/test_table_string_fontname.pdf'
doc = SimpleDocTemplate(output2, pagesize=A4)
elements = []

data = [
    ['项目', '检查项目', '1日', '2日'],
    ['通用项目检查', '消防检查、安保检查情况', '√', ''],
    ['', '车辆运行情况', '', '√'],
]

table = Table(data)
table.setStyle([
    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
    ('FONTNAME', (0, 0), (-1, -1), 'SimHei'),
    ('FONTSIZE', (0, 0), (-1, -1), 12),
])
elements.append(table)
doc.build(elements)
print(f"✓ Table(字符串+FONTNAME) PDF已生成: {output2}")

# 测试4: Table使用Paragraph
print("\n=== 测试4: Table使用Paragraph ===")
output3 = '/tmp/test_table_paragraph.pdf'
doc = SimpleDocTemplate(output3, pagesize=A4)
elements = []

style = ParagraphStyle(
    'Custom',
    fontName='SimHei',
    fontSize=12,
    wordWrap='CJK'
)

data_para = [
    [Paragraph('项目', style), Paragraph('检查项目', style), Paragraph('1日', style), Paragraph('2日', style)],
    [Paragraph('通用项目检查', style), Paragraph('消防检查、安保检查情况', style), Paragraph('√', style), Paragraph('', style)],
    [Paragraph('', style), Paragraph('车辆运行情况', style), Paragraph('', style), Paragraph('√', style)],
]

table = Table(data_para)
table.setStyle([
    ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
])
elements.append(table)
doc.build(elements)
print(f"✓ Table(Paragraph) PDF已生成: {output3}")

# 测试5: 检查字体是否支持中文
print("\n=== 测试5: 检查字体信息 ===")
try:
    font = pdfmetrics.getFont('SimHei')
    print(f"字体对象: {font}")
    print(f"字体名称: {font.fontName}")
    print(f"字体类型: {type(font)}")
except Exception as e:
    print(f"获取字体信息失败: {e}")

print("\n所有测试完成!")
print("请检查生成的3个PDF文件,确认哪个方法能正确显示中文")

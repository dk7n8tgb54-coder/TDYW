# -*- coding: utf-8 -*-
"""复现 preview vs export 两条 PDF 转换路径，定位 fit_width 差异（只读诊断）。"""
import io
import json
import os
import subprocess

import openpyxl
from openpyxl.worksheet.properties import PageSetupProperties

import django
django.setup()

from apps.equipment_lifecycle import excel_pdf_service
from apps.equipment_lifecycle.excel_models import OperationLedgerExcelTemplateVersion
from apps.equipment_lifecycle.excel_pdf_params import apply_pdf_params
from apps.equipment_lifecycle.excel_template_services import (
    _sanitize_print_areas, _verify_layout_matches, export_filled_excel,
    prepare_pdf_workbook,
)

ver = OperationLedgerExcelTemplateVersion.objects.get(pk=7)
part = ver.get_layout()
meta = {
    'source_filename': ver.source_filename,
    'source_file_hash': ver.source_hash,
    'sheet_name': part.get('sheet_name'),
    'layout': part.get('layout'),
    'field_bindings': ver.get_bindings(),
    'sample_values': {},
    'pdf_params': part.get('pdf_params') or {},
    'protocol_version': part.get('protocol_version', 1),
}
params = meta['pdf_params']
print('version pdf_params:', json.dumps(params, ensure_ascii=False)[:150])

from apps.equipment_lifecycle import excel_template_storage
src_path = excel_template_storage.version_path(ver.template_id, ver.version_no)
with open(src_path, 'rb') as f:
    src_bytes = f.read()

# 台账 29 的真实填写值
from apps.equipment_lifecycle.excel_models import OperationLedgerExcelRecord
rec = OperationLedgerExcelRecord.objects.get(ledger_id=29)
values = rec.get_values()

OUT = '/tmp/nb500_diag'
os.makedirs(OUT, exist_ok=True)

# 路径A：预览（无值）
wb = openpyxl.load_workbook(io.BytesIO(src_bytes))
_verify_layout_matches(wb, meta)
_sanitize_print_areas(wb)
apply_pdf_params(wb, params, meta['sheet_name'])
wb.save(OUT + '/A_preview.xlsx')

# 路径B：导出（填值→再 prepare）
filled = export_filled_excel(meta, src_path, values)
prepared = prepare_pdf_workbook(filled, params, meta['sheet_name'])
with open(OUT + '/B_export.xlsx', 'wb') as f:
    f.write(prepared)

# 路径C：导出填值但【不】prepare（对照）
with open(OUT + '/C_filled_raw.xlsx', 'wb') as f:
    f.write(filled)

def dump_setup(label, path):
    wb = openpyxl.load_workbook(path)
    for ws in wb.worksheets:
        pr = ws.sheet_properties.pageSetUpPr
        print('%s | %s | paper=%s orient=%s scale=%s fitW=%s fitH=%s fitToPage=%s area=%s titles=%s' % (
            label, ws.title, ws.page_setup.paperSize, ws.page_setup.orientation,
            ws.page_setup.scale, ws.page_setup.fitToWidth, ws.page_setup.fitToHeight,
            pr.fitToPage if pr else None, ws.print_area, ws.print_title_rows))

dump_setup('A', OUT + '/A_preview.xlsx')
dump_setup('B', OUT + '/B_export.xlsx')

# LO 转换并数页数
for name in ('A_preview', 'B_export', 'C_filled_raw'):
    subprocess.run(['soffice', '--headless', '--convert-to', 'pdf', '--outdir', OUT,
                    '%s/%s.xlsx' % (OUT, name)], capture_output=True, timeout=180)
    pdf = '%s/%s.pdf' % (OUT, name)
    if os.path.exists(pdf):
        info = subprocess.run(['pdfinfo', pdf], capture_output=True, text=True).stdout
        pages = [l for l in info.splitlines() if 'Pages' in l]
        print('%s -> %s' % (name, pages))
    else:
        print('%s -> CONVERT FAILED' % name)
print('DIAG DONE')

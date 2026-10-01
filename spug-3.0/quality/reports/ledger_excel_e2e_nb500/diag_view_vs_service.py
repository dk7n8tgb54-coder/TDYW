# -*- coding: utf-8 -*-
"""决定性实验：服务层直调 vs 视图层调用，谁产生 4 页 PDF（只读诊断）。"""
import os

import django
django.setup()

from apps.account.models import User
from apps.equipment_lifecycle import excel_ledger_services

OUT = '/data/spug/spug_api/tmp_diag'
os.makedirs(OUT, exist_ok=True)

user = User.objects.get(username='nb500_e2e')
ledger = excel_ledger_services.get_ledger(29, user)
print('ledger:', ledger.id, ledger.status, 'version:', ledger.excel_record.version_id)

# 1) 服务层直调（与 gunicorn 内完全同一函数链）
data = excel_ledger_services.export_pdf_file(user, ledger, pdf_params=None)
open(OUT + '/service_direct.pdf', 'wb').write(data)
print('service_direct bytes:', len(data))

# 2) 经 Django test Client 走视图（同 gunicorn 代码路径，同进程内）
from django.test import Client
c = Client()
c.defaults['HTTP_X_TOKEN'] = user.access_token
c.defaults['HTTP_X_FORWARDED_FOR'] = '172.19.0.1'
c.defaults['HTTP_HOST'] = 'localhost'
resp = c.post('/equipment-lifecycle/excel-ledgers/29/export/pdf/')
open(OUT + '/view_client.pdf', 'wb').write(resp.content)
print('view_client bytes:', len(resp.content))

# 3) meta 内容核对
record, version, meta = excel_ledger_services._export_meta(ledger)
print('meta pdf_params keys:', sorted((meta.get('pdf_params') or {}).keys()))
print('meta sheet_name:', meta.get('sheet_name'))

import subprocess
for name in ('service_direct', 'view_client'):
    pdf = OUT + '/%s.pdf' % name
    info = subprocess.run(['pdfinfo', pdf], capture_output=True, text=True).stdout
    pages = [l.strip() for l in info.splitlines() if 'Pages' in l]
    print(name, '->', pages, 'sha1_16:', __import__('hashlib').sha1(open(pdf, 'rb').read()).hexdigest()[:16])
print('DIAG2 DONE')

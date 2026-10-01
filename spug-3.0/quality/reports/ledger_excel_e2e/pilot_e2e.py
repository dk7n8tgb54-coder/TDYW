# -*- coding: utf-8 -*-
"""Excel 上传版维护台账端到端试点（2026-09-28）：完整 HTTP 流程验收。"""
import hashlib
import json
import os
import time
import uuid

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.account.models import User

OUT_DIR = '/data/spug/pilot_out'
os.makedirs(OUT_DIR, exist_ok=True)

PERMS = ['equipment_lifecycle.ledger_template.view', 'equipment_lifecycle.ledger_template.add',
         'equipment_lifecycle.ledger_template.edit', 'equipment_lifecycle.ledger.view',
         'equipment_lifecycle.ledger.add', 'equipment_lifecycle.ledger.edit',
         'equipment_lifecycle.ledger.submit', 'equipment_lifecycle.ledger.export',
         'equipment_lifecycle.ledger.review', 'equipment_lifecycle.ledger.del']

user = User.objects.filter(username='excel_pilot').first()
if user is None:
    user = User.objects.create(
        username='excel_pilot', nickname='Excel试点', is_active=True, is_supper=False,
        password_hash=User.make_password('Pilot#2026'),
        access_token=('excel_pilot' * 10)[:32],
        token_expired=int(time.time()) + 3600 * 24 * 30,
        last_login='2026-09-28', last_ip='172.19.0.1', type='default', tenant_id='default')
user.set_perms_cache(set(PERMS), version=0)
print('pilot user:', user.id, user.tenant_id)

# 重跑清理：删除上一轮试点模板与台账（PROTECT 版本先经台账记录解除）
from apps.equipment_lifecycle.excel_models import (
    OperationLedgerExcelRecord, OperationLedgerExcelTemplate,
)
from apps.equipment_lifecycle.models import OperationLedger
OperationLedgerExcelRecord.objects.filter(
    ledger__created_from='excel_template', ledger__client_token='pilot-e2e-20260928') \
    .delete()
OperationLedger.objects.filter(created_from='excel_template',
                               client_token='pilot-e2e-20260928').delete()
OperationLedgerExcelTemplate.objects.filter(
    name='信道维护台账（Excel上传试点）').delete()

client = Client()
client.defaults['HTTP_X_TOKEN'] = user.access_token
client.defaults['HTTP_X_FORWARDED_FOR'] = '172.19.0.1'
client.defaults['HTTP_HOST'] = 'localhost'  # testserver 不在 ALLOWED_HOSTS（shell 场景）

# 1) 下载平台生成的验收样例
resp = client.get('/equipment-lifecycle/excel-templates/sample/')
assert resp.status_code == 200, resp.status_code
sample_bytes = resp.content
with open(os.path.join(OUT_DIR, '01_信道维护台账验收样例.xlsx'), 'wb') as f:
    f.write(sample_bytes)
sample_hash = hashlib.sha256(sample_bytes).hexdigest()
print('1 sample downloaded:', len(sample_bytes), 'sha256:', sample_hash[:16])

# 2) 上传为维护台账模板
resp = client.post('/equipment-lifecycle/excel-templates/', {
    'file': SimpleUploadedFile('信道维护台账验收样例.xlsx', sample_bytes),
    'name': '信道维护台账（Excel上传试点）',
    'ledger_type': 'week_month',
    'description': 'WPS/Excel 固定版式试点验收模板',
})
payload = resp.json()
assert not payload.get('error'), payload
template = payload['data']['data']
print('2 template created:', template['id'], 'hash:', template['draft_source_hash'][:16])
assert template['draft_source_hash'] == sample_hash, '上传哈希须与原始文件一致'

# 3) 绑定可填写单元格（标题与普通单元格不可填，由服务端校验保证）
def binding(sheet, coord, name, input_type='status', required=True, options=None, default=''):
    return {'field_id': str(uuid.uuid4()), 'sheet_name': sheet, 'cell_coordinate': coord,
            'field_name': name, 'input_type': input_type, 'is_required': required,
            'unit': '', 'options': options or [], 'default_value': default,
            'operation_guide': '按巡检卡逐项检查并选择结果' if input_type == 'status' else '',
            'abnormal_rule': '', 'maintenance_cycles': ['all']}

SHEET1, SHEET2 = '信道维护记录', '维护结论'
bindings = []
for row, radio in ((3, '主电台'), (4, '备电台')):
    for col, module in (('C', 'PS模块'), ('D', 'TX模块'), ('E', 'RX模块'),
                        ('F', 'BB模块'), ('G', '显示模块')):
        bindings.append(binding(SHEET1, '%s%d' % (col, row),
                                '第1信道-%s-%s' % (radio, module)))
    bindings.append(binding(SHEET1, 'H%d' % row, '第1信道-%s-备注' % radio,
                            input_type='text', required=False))
bindings.append(binding(SHEET2, 'B2', '维护日期', input_type='date'))
bindings.append(binding(SHEET2, 'B4', '总体结论', input_type='choice',
                        options=['正常', '异常'], default='正常'))
resp = client.put('/equipment-lifecycle/excel-templates/%s/bindings/' % template['id'],
                  json.dumps({'field_bindings': bindings}), content_type='application/json')
payload = resp.json()
assert not payload.get('error'), payload
print('3 bindings saved:', len(bindings))

# 4) 发布模板版本（不可变）
resp = client.post('/equipment-lifecycle/excel-templates/%s/publish/' % template['id'])
payload = resp.json()
assert not payload.get('error'), payload
version = payload['data']['data']
print('4 published v%s fields=%s hash=%s' % (version['version_no'], version['field_count'],
                                             version['source_hash'][:16]))
assert version['source_hash'] == sample_hash

# 5) 创建维护台账（周月维护）
resp = client.post('/equipment-lifecycle/excel-ledgers/',
                   json.dumps({'version_id': version['id'], 'executed_date': '2026-09-28',
                               'executor_names': '李验收、王验收', 'ledger_type': 'week_month',
                               'client_token': 'pilot-e2e-20260928'}),
                   content_type='application/json')
payload = resp.json()
assert not payload.get('error'), payload
ledger = payload['data']['data']
ledger_id = ledger['id']
print('5 ledger created:', ledger['ledger_no'], 'created_from:', ledger['created_from'],
      'prefill keys:', list(ledger['excel']['values'].keys()))

# 6) 保存草稿后重新打开继续填写
values = dict(ledger['excel']['values'])
by_name = {b['field_name']: b for b in bindings}
values[by_name['第1信道-主电台-PS模块']['field_id']] = '正常'
values[by_name['第1信道-主电台-备注']['field_id']] = '指示灯正常'
resp = client.put('/equipment-lifecycle/excel-ledgers/%s/' % ledger_id,
                  json.dumps({'values': values}), content_type='application/json')
assert not resp.json().get('error'), resp.json()
resp = client.get('/equipment-lifecycle/excel-ledgers/%s/' % ledger_id)
values = resp.json()['data']['data']['excel']['values']
assert values.get(by_name['第1信道-主电台-备注']['field_id']) == '指示灯正常'
print('6 draft saved and reopened, values:', len(values))

# 7) 完整填写并提交（校验必填与类型）
full = {}
for name, b in by_name.items():
    if b['input_type'] == 'status':
        full[b['field_id']] = '异常' if name == '第1信道-备电台-RX模块' else '正常'
    elif b['input_type'] == 'date':
        full[b['field_id']] = '2026-09-28'
    elif b['input_type'] == 'choice':
        full[b['field_id']] = '正常'
    else:
        full[b['field_id']] = ''
full[by_name['第1信道-主电台-备注']['field_id']] = '指示灯正常'
full[by_name['第1信道-备电台-备注']['field_id']] = 'RX模块已更换'
resp = client.put('/equipment-lifecycle/excel-ledgers/%s/' % ledger_id,
                  json.dumps({'values': full}), content_type='application/json')
assert not resp.json().get('error'), resp.json()
resp = client.post('/equipment-lifecycle/excel-ledgers/%s/submit/' % ledger_id)
payload = resp.json()
assert not payload.get('error'), payload
print('7 submitted, status:', payload['data']['data']['status'])

# 8) 历史详情 + 导出 Excel/PDF
resp = client.get('/equipment-lifecycle/excel-ledgers/%s/' % ledger_id)
detail = resp.json()['data']['data']
assert detail['excel']['version']['version_no'] == 1
with open(os.path.join(OUT_DIR, '02_台账详情.json'), 'w', encoding='utf-8') as f:
    json.dump(detail, f, ensure_ascii=False, indent=1, default=str)
resp = client.post('/equipment-lifecycle/excel-ledgers/%s/export/excel/' % ledger_id)
assert resp.status_code == 200 and resp.content[:2] == b'PK', (resp.status_code, resp.content[:8])
with open(os.path.join(OUT_DIR, '03_已提交台账导出.xlsx'), 'wb') as f:
    f.write(resp.content)
print('8 excel exported:', len(resp.content))
resp = client.post('/equipment-lifecycle/excel-ledgers/%s/export/pdf/' % ledger_id)
assert resp.status_code == 200 and resp.content[:5] == b'%PDF-', (resp.status_code, resp.content[:8])
with open(os.path.join(OUT_DIR, '04_已提交台账导出.pdf'), 'wb') as f:
    f.write(resp.content)
print('8 pdf exported:', len(resp.content))

# 9) 跨租户拒绝（另一租户用户不可见）
other = User.objects.create(
    username='excel_pilot_other_%s' % uuid.uuid4().hex[:6], nickname='其他租户',
    is_active=True, is_supper=False, password_hash='x',
    access_token=(uuid.uuid4().hex * 4)[:32], token_expired=int(time.time()) + 3600,
    last_login='2026-09-28', last_ip='127.0.0.1', type='default', tenant_id='tenant_b')
other.set_perms_cache(set(PERMS), version=0)
other_client = Client()
other_client.defaults['HTTP_X_TOKEN'] = other.access_token
other_client.defaults['HTTP_X_FORWARDED_FOR'] = '127.0.0.1'  # 与 other.last_ip 一致（IP 绑定）
other_client.defaults['HTTP_HOST'] = 'localhost'
resp = other_client.get('/equipment-lifecycle/excel-ledgers/%s/' % ledger_id)
assert resp.json().get('error') == '台账不存在', resp.json()
resp = other_client.get('/equipment-lifecycle/excel-templates/%s/' % template['id'])
assert resp.json().get('error') == 'Excel台账模板不存在', resp.json()
print('9 cross-tenant rejected (fail-closed)')

# 10) 正常台账列表不返回 Excel 路线台账
resp = client.get('/equipment-lifecycle/ledgers/?ledger_type=week_month')
normal_ids = [r['id'] for r in resp.json()['data']['data']]
assert ledger_id not in normal_ids, 'Excel 台账不得出现在正式明细台账列表'
print('10 normal list excludes excel ledgers OK')

print('PILOT_LEDGER_ID=%s TEMPLATE_ID=%s VERSION_ID=%s USER_ID=%s' % (
    ledger_id, template['id'], version['id'], user.id))
print('PILOT E2E OK')

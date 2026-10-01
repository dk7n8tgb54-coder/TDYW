# -*- coding: utf-8 -*-
"""NB500.xlsx Excel 维护台账真实端到端验收（2026-09-30）。

真实 HTTP 全栈：Windows 宿主机 → nginx(8080, /api 剥离) → gunicorn → MariaDB。
账号 nb500_e2e（user 49，真实 Role 权限），只读检查与测试，不改任何业务代码。

步骤清单（对应用户要求）：
 1 上传  2 解析预览  3 单字段绑定  4 批量绑定  5 草稿保存
 6 重新打开  7 PDF 参数保存  8 发布  9 创建台账(+填写+提交)
 10 Excel 导出  11 PDF 导出
外加：草稿 PDF 预览、导出预检、防重复创建、负向校验、列表隔离。
"""
import hashlib
import io
import json
import os
import sys
import uuid

import requests

BASE = 'http://localhost:8080/api'
TOKEN = 'nb500-e2e-nb500-e2e-nb500-e2e-nb'
OUT = os.path.dirname(os.path.abspath(__file__))
SRC = r'E:/TDYW/spug-3.0/NB500.xlsx'

S = requests.Session()
S.headers.update({'x-token': TOKEN})

RESULTS = []


def step(no, name, ok, detail=''):
    RESULTS.append((no, name, 'PASS' if ok else 'FAIL', detail))
    print('[%s] %s %s %s' % ('PASS' if ok else 'FAIL', no, name, detail), flush=True)
    return ok


def body_of(resp):
    """HTTP 200 + {error, data} 协议；返回 (data, error)。"""
    try:
        payload = resp.json()
    except ValueError:
        return None, 'HTTP %s 非JSON: %s' % (resp.status_code, resp.text[:200])
    if isinstance(payload, dict):
        err = payload.get('error') or ''
        data = payload.get('data')
        # json_response({'data': x}) 的双层包装
        if isinstance(data, dict) and 'data' in data and set(data.keys()) <= {'data', 'total', 'error'}:
            data = data['data']
        return data, err
    return payload, ''


def api(method, path, expect_error=None, **kw):
    resp = S.request(method, BASE + path, timeout=120, **kw)
    data, err = body_of(resp)
    if expect_error is not None:
        return resp, data, err
    if err or resp.status_code != 200:
        raise AssertionError('%s %s -> HTTP %s error=%r data=%r'
                             % (method, path, resp.status_code, err, str(data)[:300]))
    return resp, data, err


with open(SRC, 'rb') as f:
    NB500 = f.read()
SRC_SHA = hashlib.sha256(NB500).hexdigest()
print('NB500.xlsx sha256=%s size=%d' % (SRC_SHA, len(NB500)), flush=True)

# ---------- 0 认证连通 ----------
resp, data, err = api('GET', '/equipment-lifecycle/excel-templates/')
step('0', '认证与列表连通（GET /excel-templates/）', isinstance(data, list),
     '现有模板数=%s' % len(data) if isinstance(data, list) else type(data).__name__)

# ---------- 1 上传 ----------
tpl_name = 'NB500无方向信标周月维护记录表（E2E验收）'
resp = S.post(BASE + '/equipment-lifecycle/excel-templates/',
              files={'file': ('NB500.xlsx', io.BytesIO(NB500),
                              'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')},
              data={'name': tpl_name, 'ledger_type': 'week_month',
                    'description': 'NB500.xlsx 真实 WPS/Excel 模板端到端验收（2026-09-30）'},
              timeout=120)
tpl, err = body_of(resp)
ok = step('1', '上传 NB500.xlsx 创建模板', not err and resp.status_code == 200 and bool(tpl and tpl.get('id')),
          err or 'template_id=%s hash=%s' % (tpl and tpl.get('id'), tpl and str(tpl.get('draft_source_hash'))[:16]))
if not ok:
    print('上传失败，终止'); json.dump(RESULTS, open(os.path.join(OUT, 'results.json'), 'w'), ensure_ascii=False); sys.exit(1)
TID = tpl['id']
hash_ok = tpl.get('draft_source_hash') == SRC_SHA
step('1a', '上传登记哈希 == 原始文件 SHA-256', hash_ok,
     '%s vs %s' % (str(tpl.get('draft_source_hash'))[:16], SRC_SHA[:16]))
json.dump(tpl, open(os.path.join(OUT, '01_上传后模板详情.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1, default=str)

# ---------- 2 解析预览（详情返回的草稿版式 meta） ----------
draft = tpl.get('draft') or {}
layout = (draft.get('layout') or {})
sheets = layout.get('sheets') or []
s1 = next((s for s in sheets if s.get('name') == 'Sheet1'), None)
checks = {
    '识别主工作表 Sheet1': draft.get('sheet_name') == 'Sheet1' and s1 is not None,
    '合并单元格 8 处': s1 and len(s1.get('merged_ranges') or []) == 8,
    '行高 19 行 x 40': s1 and len(s1.get('row_heights') or {}) == 19 and set(s1['row_heights'].values()) == {40.0},
    '列宽 A-F 解析': s1 and set((s1.get('column_widths') or {}).keys()) >= set('ABCDEF'),
    '单元格值+样式落 meta': s1 and len(s1.get('cells') or {}) >= 40,
    '打印设置 A4(9) 纵向': s1 and s1.get('print', {}).get('paper_size') == 9 and s1.get('print', {}).get('orientation') == 'portrait',
    'PDF 参数已播种': bool(draft.get('pdf_params')),
    '兼容性检查 ok': (tpl.get('compatibility') or {}).get('status') == 'ok',
}
step('2', '解析预览：布局 meta 完整（详情接口）', all(checks.values()),
     '; '.join('%s=%s' % (k, v) for k, v in checks.items() if not v) or '全部通过')
step('2a', '解析预览：A1:F19 标题值正确', bool(s1 and s1['cells'].get('A1', {}).get('v') == 'NDB-500无方向信标周、月维护记录表'),
     'A1=%r' % (s1 and s1['cells'].get('A1', {}).get('v')))

# ---------- 3 单字段绑定 ----------
def b(sheet, coord, name, itype, required=True, unit='', options=None):
    return {'field_id': str(uuid.uuid4()), 'sheet_name': sheet, 'cell_coordinate': coord,
            'field_name': name, 'input_type': itype, 'is_required': required,
            'unit': unit, 'options': options or []}

one = [b('Sheet1', 'C3', '天线电流-A机', 'number', True, 'A')]
resp, data, err = api('PUT', '/equipment-lifecycle/excel-templates/%s/bindings/' % TID,
                      json={'field_bindings': one})
step('3', '单字段绑定（C3 数值型）', not err and len((data.get('draft') or {}).get('field_bindings') or []) == 1,
     err or 'draft.field_bindings=1')

# 负向：已有内容表头单元格
resp, data, err = api('PUT', '/equipment-lifecycle/excel-templates/%s/bindings/' % TID,
                      expect_error=True, json={'field_bindings': [b('Sheet1', 'A2', '表头', 'text')]})
step('3a', '负向：有内容的表头格拒绝绑定', '已有内容' in err, err)
# 负向：合并区域非左上角
resp, data, err = api('PUT', '/equipment-lifecycle/excel-templates/%s/bindings/' % TID,
                      expect_error=True, json={'field_bindings': [b('Sheet1', 'F19', '日期F格', 'text')]})
step('3b', '负向：合并区非锚点格拒绝（F19∈E19:F19）', '左上角' in err, err)

# ---------- 4 批量绑定 ----------
rows = {
    3: ('伺服检测组件', '天线电流'), 4: ('监控器', '电源电流'), 5: ('监控器', '-54V'),
    6: ('监控器', '+24V'), 7: ('监控器', '+15V'), 8: ('监控器', '-15V'), 9: ('监控器', '+5V'),
    10: ('谐波滤波器', '正向功率'), 11: ('谐波滤波器', '反向功率'), 12: ('谐波滤波器', '调幅度'),
    13: ('发射机', '射频电平'), 14: ('发射机', '音频电平'), 15: ('发射机', '调制度'),
}
others = ['交流电压', 'UPS', '电池电压', '天线及拉线', '空调', '电源插座', '机房温湿度',
          '机房密封', '气体消防', '通信联系', '设备地线', '避雷器', '电磁环境']
batch = []
for r, (_comp, param) in rows.items():
    batch.append(b('Sheet1', 'C%d' % r, '%s-A机' % param, 'number', True, 'A' if r == 3 else ''))
    batch.append(b('Sheet1', 'D%d' % r, '%s-B机' % param, 'number', r in (3, 4), 'A' if r == 3 else ''))
for i, item in enumerate(others):
    batch.append(b('Sheet1', 'F%d' % (3 + i), '其他-%s' % item, 'text', False))
batch.append(b('Sheet1', 'B19', '维护人签字', 'text', True))
batch.append(b('Sheet1', 'E19', '维护日期', 'date', True))
batch.append(b('Sheet1', 'A16', '异常及处理记录', 'text', False))
step('4', '批量绑定清单生成', len(batch) == 42, '字段数=%d' % len(batch))

# 负向：批量内同一单元格重复
dup = [b('Sheet1', 'C3', '甲', 'number'), b('Sheet1', 'C3', '乙', 'number')]
resp, data, err = api('PUT', '/equipment-lifecycle/excel-templates/%s/bindings/' % TID,
                      expect_error=True, json={'field_bindings': dup})
step('4a', '负向：批量内重复单元格拒绝', '已绑定字段' in err, err)

resp, data, err = api('PUT', '/equipment-lifecycle/excel-templates/%s/bindings/' % TID,
                      json={'field_bindings': batch})
got = (data.get('draft') or {}).get('field_bindings') or []
step('4b', '批量绑定 42 字段整体落库', not err and len(got) == 42,
     err or '落库=%d' % len(got))
json.dump(data, open(os.path.join(OUT, '02_批量绑定后详情.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1, default=str)

# ---------- 5+6 草稿保存 & 重新打开（绑定工作区恢复） ----------
resp, again, err = api('GET', '/equipment-lifecycle/excel-templates/%s/' % TID)
d2 = (again.get('draft') or {})
names = {f['field_name']: f['field_id'] for f in d2.get('field_bindings') or []}
check = (names.get('维护人签字') and names.get('维护日期') and names.get('异常及处理记录')
         and names.get('天线电流-A机') and len(names) == 42)
pdfp = d2.get('pdf_params') or {}
step('5', '草稿保存（绑定+布局+PDF参数随草稿持久化）', bool(check) and bool(pdfp),
     '字段=%d, pdf_params键=%s' % (len(names), sorted(pdfp.keys())))
step('6', '重新打开：详情完整恢复绑定工作区', bool(check),
     'draft_updated_at=%s' % d2.get('draft_updated_at'))

# ---------- 7 PDF 参数保存 ----------
params = {'paper_size': 'A4', 'orientation': 'portrait',
          'margins': {'top': 1.91, 'bottom': 1.91, 'left': 1.78, 'right': 1.78,
                      'header': 0.76, 'footer': 0.76},
          'scale_mode': 'fit_width', 'scale_percent': 100,
          'repeat_header_rows': '2:2', 'row_breaks': [], 'page_order': 'down_then_over'}
resp, data, err = api('PUT', '/equipment-lifecycle/excel-templates/%s/pdf-params/' % TID,
                      json={'pdf_params': params})
saved = ((data.get('draft') or {}).get('pdf_params') or {})
ok = not err and saved.get('paper_size') == 'A4' and saved.get('repeat_header_rows') == '2:2'
step('7', 'PDF 参数保存（A4/纵向/fit_width/重复表头行2:2）', ok, err or json.dumps(saved, ensure_ascii=False)[:160])
# 负向：分页行越界
bad = dict(params); bad['row_breaks'] = [25]
resp, data, err = api('PUT', '/equipment-lifecycle/excel-templates/%s/pdf-params/' % TID,
                      expect_error=True, json={'pdf_params': bad})
step('7a', '负向：分页行越界（>19）拒绝', bool(err), err)
# 负向：未知纸张
bad2 = dict(params); bad2['paper_size'] = 'X9'
resp, data, err = api('PUT', '/equipment-lifecycle/excel-templates/%s/pdf-params/' % TID,
                      expect_error=True, json={'pdf_params': bad2})
step('7b', '负向：未知纸张规格拒绝', bool(err), err)

# ---------- 草稿 PDF 预览（发布前真实版式） ----------
resp = S.post(BASE + '/equipment-lifecycle/excel-templates/%s/preview/pdf/' % TID, timeout=300)
if resp.status_code == 200 and resp.content[:5] == b'%PDF-':
    open(os.path.join(OUT, '03_草稿PDF预览.pdf'), 'wb').write(resp.content)
    step('7c', '草稿 PDF 预览（未填写留空）', True, 'bytes=%d' % len(resp.content))
else:
    step('7c', '草稿 PDF 预览（未填写留空）', False, 'HTTP %s %s' % (resp.status_code, resp.text[:200]))

# ---------- 8 发布 ----------
resp, ver, err = api('POST', '/equipment-lifecycle/excel-templates/%s/publish/' % TID)
ok = not err and ver and ver.get('version_no') == 1 and ver.get('field_count') == 42
step('8', '发布不可变版本 v1', ok, err or 'version_id=%s field_count=%s hash=%s' % (
    ver and ver.get('id'), ver and ver.get('field_count'), ver and str(ver.get('source_hash'))[:16]))
hash_ok2 = ver and ver.get('source_hash') == SRC_SHA
step('8a', '版本快照哈希 == 原始文件', bool(hash_ok2), '')
VID = ver['id']
resp, vd, err = api('GET', '/equipment-lifecycle/excel-templates/%s/versions/1/' % TID)
vb = vd.get('field_bindings') or []
vb = vd.get('bindings') or []
step('8b', '版本详情含 42 绑定与 PDF 参数快照', len(vb) == 42 and bool(vd.get('pdf_params')),
     'bindings=%d pdf_params=%s' % (len(vb), bool(vd.get('pdf_params'))))
json.dump(vd, open(os.path.join(OUT, '04_发布版本详情.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1, default=str)
# 负向：版本只读（PUT 应 405）
resp = S.put(BASE + '/equipment-lifecycle/excel-templates/%s/versions/1/' % TID, json={})
step('8c', '负向：版本快照只读（PUT=405）', resp.status_code == 405, 'HTTP %s' % resp.status_code)

# ---------- 9 创建台账 ----------
# 负向：类型不一致
resp, data, err = api('POST', '/equipment-lifecycle/excel-ledgers/',
                      expect_error=True, json={'version_id': VID, 'executed_date': '2026-09-30',
                            'ledger_type': 'seasonal', 'client_token': 'nb500-neg-1'})
step('9a', '负向：季维护请求×周月模板拒绝', '不一致' in (err or ''), err)
resp, ledger, err = api('POST', '/equipment-lifecycle/excel-ledgers/',
                        json={'version_id': VID, 'executed_date': '2026-09-30',
                              'executor_names': 'NB500验收员', 'ledger_type': 'week_month',
                              'client_token': 'nb500-e2e-20260930'})
ok = not err and ledger and ledger.get('created_from') == 'excel_template'
step('9', '创建台账（created_from=excel_template）', ok,
     err or 'id=%s no=%s' % (ledger and ledger.get('id'), ledger and ledger.get('ledger_no')))
LID = ledger['id']
step('9b', '台账编号/类型/状态', ledger.get('ledger_type') == 'week_month' and ledger.get('status') == 'draft',
     'no=%s status=%s' % (ledger.get('ledger_no'), ledger.get('status')))
resp, dup_ledger, err = api('POST', '/equipment-lifecycle/excel-ledgers/',
                            json={'version_id': VID, 'executed_date': '2026-09-30',
                                  'executor_names': 'NB500验收员', 'ledger_type': 'week_month',
                                  'client_token': 'nb500-e2e-20260930'})
step('9c', '同 client_token 防重复创建', dup_ledger and dup_ledger.get('id') == LID,
     'id=%s' % (dup_ledger and dup_ledger.get('id')))

# 可用模板入口
resp, avail, err = api('GET', '/equipment-lifecycle/excel-templates/available/?ledger_type=week_month')
hit = any(t.get('id') == TID for t in (avail or []))
step('9d', '可用模板列表返回 NB500 模板', hit, '%s' % [t.get('name') for t in (avail or [])])

# ---------- 填写 + 重新打开 ----------
values = {}
for f in batch:
    nm, it = f['field_name'], f['input_type']
    if it == 'number':
        values[f['field_id']] = 3.2 if nm == '天线电流-A机' else 50.0
    elif it == 'date':
        values[f['field_id']] = '2026-09-30'
    elif nm == '维护人签字':
        values[f['field_id']] = 'NB500验收员'
    elif nm == '异常及处理记录':
        values[f['field_id']] = '本次验收未发现异常'
    else:
        values[f['field_id']] = '正常'
resp, data, err = api('PUT', '/equipment-lifecycle/excel-ledgers/%s/' % LID, json={'values': values})
saved_vals = ((data.get('excel') or {}).get('values') or {})
step('9e', '保存填写值（42 字段）', not err and len(saved_vals) >= 40,
     err or '落值=%d' % len(saved_vals))
resp, detail, err = api('GET', '/equipment-lifecycle/excel-ledgers/%s/' % LID)
fv = (detail.get('excel') or {}).get('values') or {}
fid_date = names['维护日期']; fid_sign = names['维护人签字']; fid_c3 = names['天线电流-A机']
ok = fv.get(fid_date) == '2026-09-30' and fv.get(fid_sign) == 'NB500验收员' and fv.get(fid_c3) == 3.2
step('9f', '重新打开台账：填写值完整回放', ok,
     '日期=%r 签字=%r C3=%r' % (fv.get(fid_date), fv.get(fid_sign), fv.get(fid_c3)))
# 负向：未知字段值
resp, data, err = api('PUT', '/equipment-lifecycle/excel-ledgers/%s/' % LID,
                      expect_error=True, json={'values': {'not-a-field-id': 1}})
step('9g', '负向：未绑定字段值拒绝', '未绑定' in err, err)
json.dump(detail, open(os.path.join(OUT, '05_填写后台账详情.json'), 'w', encoding='utf-8'),
          ensure_ascii=False, indent=1, default=str)

# ---------- 提交 ----------
resp, data, err = api('POST', '/equipment-lifecycle/excel-ledgers/%s/submit/' % LID)
step('9h', '提交台账（draft→submitted）', not err and data.get('status') == 'submitted',
     err or 'status=%s' % (data and data.get('status')))

# ---------- 10 Excel 导出 ----------
resp, warn, err = api('POST', '/equipment-lifecycle/excel-ledgers/%s/export/check/' % LID, json={})
warnings = (warn or {}).get('warnings') or []
step('9i', '导出前版式预检 export/check', not err, 'warnings=%s' % warnings)

resp = S.post(BASE + '/equipment-lifecycle/excel-ledgers/%s/export/excel/' % LID, timeout=300)
ok = resp.status_code == 200 and resp.content[:2] == b'PK'
step('10', 'Excel 导出（xlsx 二进制）', ok,
     'HTTP %s bytes=%d' % (resp.status_code, len(resp.content)) if ok else 'HTTP %s %s' % (resp.status_code, resp.text[:200]))
if ok:
    open(os.path.join(OUT, '06_已提交台账导出.xlsx'), 'wb').write(resp.content)

# ---------- 11 PDF 导出 ----------
resp = S.post(BASE + '/equipment-lifecycle/excel-ledgers/%s/export/pdf/' % LID, timeout=300)
ok = resp.status_code == 200 and resp.content[:5] == b'%PDF-'
step('11', 'PDF 导出（LibreOffice 转换）', ok,
     'HTTP %s bytes=%d' % (resp.status_code, len(resp.content)) if ok else 'HTTP %s %s' % (resp.status_code, resp.text[:300]))
if ok:
    open(os.path.join(OUT, '07_已提交台账导出.pdf'), 'wb').write(resp.content)

# ---------- 列表隔离 ----------
resp, data, err = api('GET', '/equipment-lifecycle/excel-ledgers/?ledger_type=week_month')
rows_ls = data.get('data') if isinstance(data, dict) and 'data' in data else data
hit = any(r.get('id') == LID for r in (rows_ls or []))
step('11a', 'Excel 台账列表可见（专用列表）', hit, 'total=%s' % (isinstance(data, dict) and data.get('total')))
resp, data, err = api('GET', '/equipment-lifecycle/ledgers/?ledger_type=week_month')
normal = data.get('data') if isinstance(data, dict) and 'data' in data else data
ids = [r.get('id') for r in (normal or [])]
step('11b', '正式明细台账列表不混入 Excel 台账', LID not in ids, '')

# ---------- 汇总 ----------
print('\n===== 验收结果汇总 =====')
fails = [r for r in RESULTS if r[2] == 'FAIL']
for no, name, st, dt in RESULTS:
    print('%s | %s | %s | %s' % (st, no, name, dt[:100]))
print('TOTAL=%d PASS=%d FAIL=%d' % (len(RESULTS), len(RESULTS) - len(fails), len(fails)))
json.dump([{'step': n, 'name': m, 'status': s, 'detail': d} for n, m, s, d in RESULTS],
          open(os.path.join(OUT, 'results.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('TEMPLATE_ID=%s VERSION_ID=%s LEDGER_ID=%s' % (TID, VID, LID))

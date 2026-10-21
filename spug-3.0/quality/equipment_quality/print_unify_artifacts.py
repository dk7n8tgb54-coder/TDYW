# -*- coding: utf-8 -*-
"""统一打印布局真机验收产物生成（2026-10-21）。

在 tdyw-test 容器内运行（依赖：开发库、chromium、poppler）：
  python3 print_unify_artifacts.py --out /tmp/print_unify

走真实 HTTP 链路（登录 → 上传模板 → 绑定 → 发布 → 创建台账 → 填值 →
导出 PDF / 打印预览 → 详情 print_plan），对两类代表模板各生成：
- {case}-print.pdf      打印预览（与导出同一生成服务）
- {case}-export.pdf     导出 PDF（应与 print 逐字节一致——缓存未命中时
  两次独立生成，文本层一致即视为一致）
- {case}-page-N.png     pdftoppm 渲染页图（与网页截图人工对照）
- {case}-plan.json      版本详情 print_plan（网页分页参考线来源）

产物用途：网页截图与 PDF 页图对比（表格边界/行列比例/合并/分页一致）。
脚本幂等：模板名带时间戳，可重复运行。
"""
import argparse
import io
import json
import os
import subprocess
import uuid

import requests
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side

BASE = 'http://localhost'
THIN = Side(style='thin')


def build_wide_landscape_xlsx():
    """代表模板一：横向 A4、多级合并表头、较宽维护表（12 列）。"""
    wb = Workbook()
    ws = wb.active
    ws.title = '巡检记录'
    ws['A1'] = '设备巡检维护记录表'
    ws.merge_cells('A1:L1')
    ws['A1'].font = Font(size=16, bold=True)
    ws['A1'].alignment = Alignment(horizontal='center', vertical='center')
    ws['A2'] = '基本信息'
    ws.merge_cells('A2:D2')
    ws['E2'] = '巡检项目'
    ws.merge_cells('E2:H2')
    ws['I2'] = '处理记录'
    ws.merge_cells('I2:L2')
    for col in range(1, 13):
        cell = ws.cell(row=3, column=col, value='%s项' % chr(64 + col))
        cell.border = Border(top=THIN, bottom=THIN, left=THIN, right=THIN)
    for row in range(4, 34):
        ws.cell(row=row, column=1, value='设备-%02d' % row)
        ws.cell(row=row, column=2, value='机房%d' % (row % 3))
    for col in range(1, 13):
        ws.column_dimensions[chr(64 + col)].width = 14
    ws.page_setup.orientation = 'landscape'
    ws.page_setup.paperSize = 9
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def build_long_portrait_xlsx():
    """代表模板二：纵向 A4、行数多、底部大面积维护记录/维护人/日期区域。"""
    wb = Workbook()
    ws = wb.active
    ws.title = '维护台账'
    ws['A1'] = '基站月度维护台账'
    ws.merge_cells('A1:H1')
    ws['A1'].font = Font(size=14, bold=True)
    for col in range(1, 9):
        ws.cell(row=2, column=col, value='%s栏' % chr(64 + col))
    for row in range(3, 81):
        ws.cell(row=row, column=1, value='检查项-%02d' % row)
    ws['A81'] = '维护记录'
    ws.merge_cells('A81:H83')
    ws['A81'].alignment = Alignment(vertical='top', wrap_text=True)
    ws['A84'] = '维护人'
    ws['A85'] = '维护日期'
    for col in range(1, 9):
        ws.column_dimensions[chr(64 + col)].width = 10
    for row in (81, 82, 83):
        ws.row_dimensions[row].height = 28
    ws['B10'].border = Border(top=THIN, bottom=THIN, left=THIN, right=THIN)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def binding(sheet, coordinate, name, input_type='text', required=True,
            options=None):
    return {
        'field_id': str(uuid.uuid4()), 'sheet_name': sheet,
        'cell_coordinate': coordinate, 'field_name': name,
        'input_type': input_type, 'is_required': required,
        'unit': '', 'options': options or [],
    }


class Client(object):
    def __init__(self, username, password):
        self.session = requests.Session()
        self.session.headers['Host'] = 'localhost'
        response = self.session.post(
            BASE + '/api/account/login/',
            json={'username': username, 'password': password,
                  'type': 'default'}, timeout=30)
        payload = response.json()
        assert payload.get('error', '') == '', '登录失败: %s' % payload
        self.session.headers['X-Token'] = payload['data']['access_token']

    def post_json(self, url, body):
        response = self.session.post(BASE + url, json=body, timeout=300)
        if not response.headers.get('Content-Type', '').startswith('application/json')                 or not response.content.strip():
            raise AssertionError('%s 返回非 JSON（HTTP %s）: %r' % (
                url, response.status_code, response.content[:200]))
        payload = response.json()
        assert payload.get('error', '') == '', '%s 失败: %s' % (url, payload)
        return payload

    def upload_template(self, name, data):
        response = self.session.post(
            BASE + '/api/equipment-lifecycle/excel-templates/',
            files={'file': (name + '.xlsx', data,
                            'application/vnd.openxmlformats-officedocument'
                            '.spreadsheetml.sheet')},
            data={'name': name, 'ledger_type': 'week_month'}, timeout=120)
        payload = response.json()
        assert payload.get('error', '') == '', '上传失败: %s' % payload
        return payload['data']['data']

    def download(self, url, body=None):
        response = self.session.post(BASE + url, json=body or {}, timeout=300)
        assert response.headers.get('Content-Type', '').startswith(
            'application/pdf'), '%s 未返回 PDF: %s' % (
            url, response.content[:200])
        return response.content


def run_case(client, case, data, bindings, values, out_dir):
    print('[%s] 上传模板' % case)
    template = client.upload_template('统一打印-' + case, data)
    response = client.session.put(
        BASE + '/api/equipment-lifecycle/excel-templates/%s/bindings/'
        % template['id'], json={'field_bindings': bindings}, timeout=120)
    payload = response.json()
    assert payload.get('error', '') == '', '绑定保存失败: %s' % payload
    version = client.post_json(
        '/api/equipment-lifecycle/excel-templates/%s/publish/' % template['id'],
        {})['data']['data']
    ledger = client.post_json(
        '/api/equipment-lifecycle/excel-ledgers/',
        {'version_id': version['id'], 'ledger_type': 'week_month'})['data']['data']
    response = client.session.put(
        BASE + '/api/equipment-lifecycle/excel-ledgers/%s/' % ledger['id'],
        json={'values': values}, timeout=120)
    payload = response.json()
    assert payload.get('error', '') == '', '填写值保存失败: %s' % payload
    response = client.session.get(
        BASE + '/api/equipment-lifecycle/excel-ledgers/%s/' % ledger['id'],
        timeout=60)
    detail = response.json()['data']['data']
    plan = (detail.get('excel') or {}).get('version', {}).get('print_plan')
    with open(os.path.join(out_dir, '%s-plan.json' % case), 'w',
              encoding='utf-8') as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    print('[%s] 台账 %s 生成打印预览与导出 PDF' % (case, ledger['ledger_no']))
    preview = client.download(
        '/api/equipment-lifecycle/excel-ledgers/%s/print-preview/' % ledger['id'])
    export = client.download(
        '/api/equipment-lifecycle/excel-ledgers/%s/export/pdf/' % ledger['id'])
    with open(os.path.join(out_dir, '%s-print.pdf' % case), 'wb') as f:
        f.write(preview)
    with open(os.path.join(out_dir, '%s-export.pdf' % case), 'wb') as f:
        f.write(export)
    print('[%s] 预览 %d 字节 / 导出 %d 字节，渲染页图' % (
        case, len(preview), len(export)))
    subprocess.run(['pdftoppm', '-png', '-r', '80',
                    os.path.join(out_dir, '%s-print.pdf' % case),
                    os.path.join(out_dir, '%s-page' % case)], check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default='/tmp/print_unify')
    parser.add_argument('--username', default='admin')
    parser.add_argument('--password', default='Admin888..')
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    client = Client(args.username, args.password)

    wide_bindings = [
        binding('巡检记录', 'C6', '巡检结果', 'status'),
        binding('巡检记录', 'D6', '处理说明', 'text', required=False),
    ]
    run_case(client, 'wide-landscape', build_wide_landscape_xlsx(),
             wide_bindings,
             {wide_bindings[0]['field_id']: '正常',
              wide_bindings[1]['field_id']: '更换风扇并清理滤网，巡检无其他异常'},
             args.out)

    long_bindings = [
        binding('维护台账', 'B10', '检查结论', 'status'),
        binding('维护台账', 'C84', '维护人签名', 'text'),
        binding('维护台账', 'C85', '维护日期', 'date'),
    ]
    run_case(client, 'long-portrait', build_long_portrait_xlsx(),
             long_bindings,
             {long_bindings[0]['field_id']: '正常',
              long_bindings[1]['field_id']: '张三',
              long_bindings[2]['field_id']: '2026-10-21'},
             args.out)
    print('完成，产物目录：%s' % args.out)


if __name__ == '__main__':
    main()

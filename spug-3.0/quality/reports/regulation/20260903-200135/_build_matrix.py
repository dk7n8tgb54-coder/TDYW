# -*- coding: utf-8 -*-
"""把 Django / Jest 原始测试日志解析为结构化用例矩阵 CSV（纯文本解析，不读源码）。"""
import csv
import io
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))
TMP = os.path.join(BASE, '..', '_tmp')

RISK = [
    ('token', 'P0'), ('traversal', 'P0'), ('tamper', 'P0'), ('expired', 'P0'),
    ('permission', 'P0'), ('tenant', 'P1'), ('cannot', 'P1'), ('denied', 'P1'),
    ('rejected', 'P1'), ('rollback', 'P1'), ('orphan', 'P1'), ('cascade', 'P1'),
    ('audit', 'P1'), ('cleanup', 'P1'), ('oversize', 'P2'), ('pagination', 'P2'),
    ('unicode', 'P2'), ('duplicate', 'P2'), ('order', 'P2'), ('n_plus_one', 'P2'),
]

STATUS_MAP = {'ok': 'PASS', 'skipped': 'NOT_RUN', 'FAIL': 'FAIL',
              'ERROR': 'FAIL', 'fail': 'FAIL', 'error': 'FAIL'}


def guess_risk(blob):
    low = blob.lower()
    for kw, risk in RISK:
        if kw in low:
            return risk
    return 'P3'


def parse_backend():
    with io.open(os.path.join(TMP, 'backend_v2.log'), encoding='utf-8',
                 errors='replace') as fh:
        lines = [ln.strip() for ln in fh]

    order, results = [], {}
    pending = None
    for ln in lines:
        # 独立的结论行（Django -v 2 会把 ok / FAIL 单独换行）
        if pending and re.match(r'^(\.{3} )?(ok|FAIL|ERROR|skipped)( \'|$)', ln):
            results[pending] = STATUS_MAP[re.sub(r'^\.{3} ', '', ln).split()[0]]
            pending = None
            continue
        m = re.match(r'^(FAIL|ERROR): (\S+) \(([\w.]+)\)$', ln)
        if m:
            key = (m.group(3), m.group(2))
            if key not in results:
                order.append(key)
            results[key] = 'FAIL'
            pending = None
            continue
        m = re.match(r'^(test_\w+) \(([\w.]+)\)(.*)$', ln)
        if m:
            key, rest = (m.group(2), m.group(1)), m.group(3).strip()
            if key not in results:
                order.append(key)
            results.setdefault(key, 'PASS')
            token = rest[3:].strip() if rest.startswith('...') else rest
            # 仅当结论令牌完整匹配时才定稿，避免日志噪声（ERROR [xxx] ...）误判
            if token in ('ok', 'FAIL', 'ERROR', 'skipped'):
                results[key] = STATUS_MAP[token]
                pending = None
            else:
                pending = key

    rows = []
    for i, key in enumerate(order, 1):
        cls, name = key
        rows.append({
            'case_id': 'BE-%03d' % i, 'layer': 'backend',
            'module': cls.split('.')[-2] if '.' in cls else cls,
            'suite': cls.rsplit('.', 1)[-1], 'case': name,
            'risk': guess_risk(name + ' ' + cls),
            'result': results.get(key, 'PASS'),
        })
    return rows


def parse_frontend():
    ansi = re.compile(r'\x1b\[[0-9;]*m')
    with io.open(os.path.join(TMP, 'jest_v.log'), encoding='utf-8',
                 errors='replace') as fh:
        lines = [ansi.sub('', ln).strip() for ln in fh]

    rows, current_file, suite = [], '', ''
    for ln in lines:
        m = re.match(r'^(PASS|FAIL) (.+)$', ln)
        if m:
            current_file = os.path.basename(m.group(2).strip())
            continue
        if re.match(r'^[A-Za-z][\w ]{2,60}$', ln) and not ln.endswith('.'):
            suite = ln
            continue
        m = re.match(r'^([√✓✕×])\s+(.+?)(?:\s+\(\d+\s*m?s\))?$', ln)
        if m:
            rows.append({
                'case_id': 'FE-%03d' % (len(rows) + 1), 'layer': 'frontend',
                'module': current_file, 'suite': suite, 'case': m.group(2).strip(),
                'risk': guess_risk(m.group(2) + ' ' + suite),
                'result': 'PASS' if m.group(1) in ('√', '✓') else 'FAIL',
            })
    return rows


def write_csv(path, rows):
    fields = ['case_id', 'layer', 'risk', 'module', 'suite', 'case', 'result']
    with io.open(path, 'w', encoding='utf-8-sig', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    be, fe = parse_backend(), parse_frontend()
    write_csv(os.path.join(BASE, 'test-matrix-backend.csv'), be)
    write_csv(os.path.join(BASE, 'test-matrix-frontend.csv'), fe)
    for label, rows in (('backend', be), ('frontend', fe)):
        s = {}
        for r in rows:
            s[r['result']] = s.get(r['result'], 0) + 1
        print('%-9s total=%d %s' % (label, len(rows), s))


if __name__ == '__main__':
    main()

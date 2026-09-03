# -*- coding: utf-8 -*-
"""从 Jest JSON 结果生成前端用例矩阵 CSV。"""
import csv
import io
import json
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, '..', '_tmp', 'jest.json')
OUT = os.path.join(BASE, 'test-matrix-frontend.csv')

RISK = [
    ('token', 'P0'), ('error', 'P0'), ('permission', 'P0'),
    ('traversal', 'P0'), ('tamper', 'P0'), ('expired', 'P0'),
    ('tenant', 'P1'), ('cannot', 'P1'), ('denied', 'P1'),
    ('rejected', 'P1'), ('rollback', 'P1'), ('audit', 'P1'),
    ('payload', 'P1'), ('resizable', 'P2'), ('duplicate', 'P2'),
]
STATUS = {'passed': 'PASS', 'failed': 'FAIL', 'pending': 'NOT_RUN',
          'skipped': 'NOT_RUN', 'todo': 'NOT_RUN'}


def guess_risk(blob):
    low = blob.lower()
    for kw, risk in RISK:
        if kw in low:
            return risk
    return 'P2'


def main():
    with io.open(SRC, encoding='utf-8') as fh:
        data = json.load(fh)

    rows = []
    idx = 0
    for suite in data.get('testResults', []):
        module = os.path.basename(suite.get('name', ''))
        for case in suite.get('assertionResults', []):
            idx += 1
            title = case.get('fullName') or case.get('title', '')
            suite_name = (case.get('ancestorTitles') or [''])[0]
            rows.append({
                'case_id': 'FE-%03d' % idx,
                'layer': 'frontend',
                'module': re.sub(r'\.test\.js$', '', module),
                'suite': suite_name,
                'case': title,
                'risk': guess_risk(title + ' ' + suite_name),
                'result': STATUS.get(case.get('status'), 'NOT_RUN'),
            })

    fields = ['case_id', 'layer', 'risk', 'module', 'suite', 'case', 'result']
    with io.open(OUT, 'w', encoding='utf-8-sig', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    summary = {}
    for r in rows:
        summary[r['result']] = summary.get(r['result'], 0) + 1
    print('frontend total=%d %s' % (len(rows), summary))


if __name__ == '__main__':
    main()

"""审计 action 影响面扫描：提取全部 audit 调用点的 action 实参与 DB 白名单对比。

只做影响面分析（读源码文本），不作为行为测试依据。
"""
import os
import re

ROOT = '/data/spug/spug_api/apps'

WHITELIST = {
    'create', 'update', 'delete', 'login', 'logout',
    'export', 'import', 'approve', 'other',
}

PATTERNS = [
    re.compile(r"record_audit_event\(\s*(?:request|self\.request)\s*,\s*['\"]([a-z_]+)['\"]"),
    re.compile(r"save_audit_log\([^)]*?action\s*=\s*['\"]([a-z_]+)['\"]"),
    re.compile(r"log_celery_audit\(\s*['\"]([a-z_]+)['\"]"),
]

found = {}
detail = {}

for dirpath, _dirnames, filenames in os.walk(ROOT):
    for fn in filenames:
        if not fn.endswith('.py') or fn.startswith('test_') or 'migrations' in dirpath:
            continue
        path = os.path.join(dirpath, fn)
        try:
            with open(path, encoding='utf-8', errors='replace') as fh:
                text = fh.read()
        except OSError:
            continue
        for pat in PATTERNS:
            for m in pat.finditer(text):
                action = m.group(1)
                found[action] = found.get(action, 0) + 1
                detail.setdefault(action, []).append(
                    path.replace(ROOT, 'apps') + ':' + str(text[:m.start()].count('\n') + 1))

print('=== 实际使用的 audit action ===')
for action, cnt in sorted(found.items(), key=lambda kv: -kv[1]):
    flag = '   OK' if action in WHITELIST else '  ILLEGAL'
    print('%s  %-28s x%d' % (flag, action, cnt))

print()
print('=== 不在 DB 白名单内的 action 及调用点 ===')
illegal = [k for k in found if k not in WHITELIST]
if not illegal:
    print('(none)')
for action in sorted(illegal):
    print('%s (%d 处)' % (action, found[action]))
    for loc in detail[action][:15]:
        print('    ' + loc)

print()
print('legal=%d illegal=%d' % (len(found) - len(illegal), len(illegal)))

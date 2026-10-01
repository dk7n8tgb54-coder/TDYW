# -*- coding: utf-8 -*-
"""ICS 200/60 E2E 专用账号 + 真实角色（真实 HTTP 认证用）。幂等。

在 tdyw-test 容器内执行：
  docker exec tdyw-test python - <<'EOF'  （或 manage.py shell 等价环境）
"""
import json
import time

from apps.account.models import Role, User

USERNAME = 'ics_e2e'
TOKEN = ('ics-e2e-' * 8)[:32]
PERMS = {
    'equipment_lifecycle': {
        'ledger_template': ['view', 'add', 'edit', 'del'],
        'ledger': ['view', 'add', 'edit', 'submit', 'export', 'review', 'del'],
    }
}

role = Role.objects.filter(name='ICS-E2E角色').first()
admin = User.objects.filter(is_supper=True).first() or User.objects.first()
if role is None:
    role = Role.objects.create(
        name='ICS-E2E角色', desc='ICS 200/60 内话系统周月维护记录表端到端验收专用（2026-10-01）',
        page_perms=json.dumps(PERMS, ensure_ascii=False), tenant_id='default',
        created_by=admin)
else:
    role.page_perms = json.dumps(PERMS, ensure_ascii=False)
    role.save()

user = User.objects.filter(username=USERNAME).first()
if user is None:
    user = User.objects.create(
        username=USERNAME, nickname='ICS验收', is_active=True, is_supper=False,
        password_hash=User.make_password('Ics#2026!'),
        access_token=TOKEN, token_expired=int(time.time()) + 3600 * 24 * 7,
        last_login='2026-10-01', last_ip='172.19.0.1',
        type='default', tenant_id='default')
else:
    user.access_token = TOKEN
    user.token_expired = int(time.time()) + 3600 * 24 * 7
    user.last_ip = '172.19.0.1'
    user.is_active = True
    user.save()
user.roles.add(role)

# 清理上一轮本脚本的 ICS E2E 模板（幂等重跑；有台账引用的改名让位）
from apps.equipment_lifecycle.excel_models import OperationLedgerExcelTemplate
stale = OperationLedgerExcelTemplate.objects.filter(name__startswith='ICS200-60内话系统周月维护记录表（E2E验收')
for t in stale:
    print('stale template:', t.id, t.name)
for t in stale:
    if not t.versions.exists():
        t.delete()
    else:
        t.name = '%s-旧%d' % (t.name, t.id)
        t.save()
print('USER_ID=%s ROLE_ID=%s TOKEN=%s' % (user.id, role.id, TOKEN))
print('SETUP OK')

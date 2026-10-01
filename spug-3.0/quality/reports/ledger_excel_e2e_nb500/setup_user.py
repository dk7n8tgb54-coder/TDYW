# -*- coding: utf-8 -*-
"""NB500 E2E 专用账号 + 真实角色（真实 HTTP 认证用）。幂等。"""
import json
import time

from apps.account.models import Role, User

USERNAME = 'nb500_e2e'
TOKEN = ('nb500-e2e-' * 5)[:32]
PERMS = {
    'equipment_lifecycle': {
        'ledger_template': ['view', 'add', 'edit', 'del'],
        'ledger': ['view', 'add', 'edit', 'submit', 'export', 'review', 'del'],
    }
}

role = Role.objects.filter(name='NB500-E2E角色').first()
admin = User.objects.filter(is_supper=True).first() or User.objects.first()
if role is None:
    role = Role.objects.create(
        name='NB500-E2E角色', desc='NB500.xlsx 端到端验收专用（2026-09-30）',
        page_perms=json.dumps(PERMS, ensure_ascii=False), tenant_id='default',
        created_by=admin)
else:
    role.page_perms = json.dumps(PERMS, ensure_ascii=False)
    role.save()

user = User.objects.filter(username=USERNAME).first()
if user is None:
    user = User.objects.create(
        username=USERNAME, nickname='NB500验收', is_active=True, is_supper=False,
        password_hash=User.make_password('Nb500#2026'),
        access_token=TOKEN, token_expired=int(time.time()) + 3600 * 24 * 7,
        last_login='2026-09-30', last_ip='172.19.0.1',
        type='default', tenant_id='default')
else:
    user.access_token = TOKEN
    user.token_expired = int(time.time()) + 3600 * 24 * 7
    user.last_ip = '172.19.0.1'
    user.is_active = True
    user.save()
user.roles.add(role)

# 清理上一轮本脚本的 NB500 模板（幂等重跑）
from apps.equipment_lifecycle.excel_models import OperationLedgerExcelTemplate
stale = OperationLedgerExcelTemplate.objects.filter(name__startswith='NB500无方向信标周月维护记录表（E2E验收')
for t in stale:
    print('stale template:', t.id, t.name, 'ledgers:', t.versions.count())
# 仅删除无台账引用的旧草稿模板；有引用的保留（PROTECT），改名避免撞名
for t in stale:
    if not t.versions.exists():
        t.delete()
    else:
        t.name = t.name + '-旧' + str(t.id)
        t.save()
print('USER_ID=%s ROLE_ID=%s TOKEN=%s' % (user.id, role.id, TOKEN))
print('SETUP OK')

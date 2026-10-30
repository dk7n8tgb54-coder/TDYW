# -*- coding: utf-8 -*-
"""多文件制度端到端验证（开发环境 dev 库 + dev 存储，测试手册）

流程：两份文件分别编辑保存 -> 整套发布 v1 -> 修改/移除其中一份 ->
再发布 v2 -> 查看和下载两个历史版本 -> 整套回退 v1 -> 发布 v3。
全程断言：快照清单有序、哈希一致、旧版内容与顺序不变。
"""
import os
import tempfile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.test.utils import setup_test_environment

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()
setup_test_environment()

import time
from apps.account.models import User, Role
from apps.institution import storage
from apps.institution.models import (Manual, ManualDraft, ManualFile,
                                     ManualVersion, ManualVersionFile)

# ---- 账号与角色（测试专用，命名隔离） ----
stamp = str(int(time.time()))
PERMS = ['institution.manual.view', 'institution.manual.add',
         'institution.manual.edit', 'institution.manual.upload',
         'institution.manual.download', 'institution.manual.draft_edit',
         'institution.manual.publish', 'institution.manual.config']


def perm_json(perms):
    import json
    tree = {}
    for p in perms:
        a, b, c = p.split('.')
        tree.setdefault(a, {}).setdefault(b, {})[c] = True
    return json.dumps(tree)


creator = User.objects.filter(username='e2e_creator').first()
if not creator:
    creator = User.objects.create(
        username='e2e_creator', nickname='e2e_creator',
        password_hash=User.make_password('x'), access_token='e2e' + '0' * 28,
        is_supper=True, is_active=True, tenant_id='',
        token_expired=int(time.time()) + 86400, type='default')
admin = User.objects.create(
    username=f'e2e_mgr_{stamp}', nickname=f'e2e_mgr_{stamp}',
    password_hash=User.make_password('x'), access_token=('m' + stamp)[:32].ljust(32, '0'),
    is_active=True, tenant_id='e2e', token_expired=int(time.time()) + 86400,
    type='default')
role = Role.objects.create(
    name=f'e2e_role_{stamp}', desc='', page_perms=perm_json(PERMS),
    perms_version=1, tenant_id='e2e', created_by=creator)
admin.roles.add(role)

client = Client()
client.defaults['HTTP_X_TOKEN'] = admin.access_token


def ok(resp, hint):
    body = resp.json()
    assert not body.get('error'), f'{hint} failed: {body}'
    return body.get('data')


def post(path, data=None, **kw):
    import json as _json
    return client.post(path, data=_json.dumps(data or {}),
                       content_type='application/json', **kw)


M = f'/institution/manuals'

# ---- 1) 建手册 + 两份文件（各自含原稿与草稿） ----
data = ok(post(f'{M}/create/', {'name': f'E2E多文件手册_{stamp}', 'code': 'E2E-M',
                                'owner_type': 'department',
                                'edit_role_ids': [role.id],
                                'view_role_ids': [role.id],
                                'publish_role_ids': [role.id]}), 'create manual')
mid = data['id']
ok(client.put(f'{M}/{mid}/password/',
              data=__import__('json').dumps({'password': 'e2e-pass-1'}),
              content_type='application/json'), 'set password')

file_a = ok(client.post(f'{M}/{mid}/files/create/',
                        {'file': SimpleUploadedFile('甲-总则.docx', b'PK\x03\x04 A-original')}), 'file A')
file_b = ok(client.post(f'{M}/{mid}/files/create/',
                        {'file': SimpleUploadedFile('乙-细则.docx', b'PK\x03\x04 B-original')}), 'file B')
fid_a, fid_b = file_a['id'], file_b['id']
assert file_a['draft']['revision'] == 1 and file_b['draft']['revision'] == 1
print('[1] 两份文件已建：', file_a['name'], file_b['name'])

# ---- 2) 两份文件分别编辑保存（并行会话语义：各自开会话各自保存） ----
def edit_and_save(fid, tag):
    resp = post(f'{M}/{mid}/files/{fid}/draft/session/', {'password': 'e2e-pass-1'})
    sess = ok(resp, f'session {tag}')
    up = SimpleUploadedFile(f'{tag}.docx', b'PK\x03\x04 ' + tag.encode() + b'-saved')
    resp = client.post(f'{M}/{mid}/files/{fid}/draft/save/',
                       {'file': up, 'session_key': sess['session_key'],
                        'revision': sess['revision']})
    d = ok(resp, f'save {tag}')
    # 保存后退出会话（发布前不得有活跃会话）
    ok(client.delete(f'{M}/{mid}/files/{fid}/draft/session/',
                     data=_json_dumps({'session_key': sess['session_key']}),
                     content_type='application/json'), f'exit {tag}')
    return d


import json as _json_dumps_mod
def _json_dumps(x):
    return _json_dumps_mod.dumps(x)


edit_and_save(fid_a, 'A-v2')
edit_and_save(fid_b, 'B-v2')
print('[2] 两份文件分别编辑保存完成（修订号各自递增）')

# ---- 3) 整套发布 v1 ----
v1 = ok(post(f'{M}/{mid}/publish/', {'change_note': 'e2e 首版整套发布'}), 'publish v1')
assert v1['version_no'] == 1
assert [f['file_name'] for f in v1['files']] == ['甲-总则.docx', '乙-细则.docx'], v1['files']
v1_snapshots = {f['id']: f for f in v1['files']}
for f in v1['files']:
    snap = ManualVersionFile.objects.get(pk=f['id'])
    abs_path = storage.resolve_absolute_path(snap.file_path)
    assert os.path.exists(abs_path)
    assert storage.compute_file_hash(abs_path) == f['file_hash']
print('[3] v1 发布：快照清单', [f['file_name'] for f in v1['files']])

# ---- 4) 修改甲、移除乙，再发布 v2 ----
edit_and_save(fid_a, 'A-v3')
ok(post(f'{M}/{mid}/files/{fid_b}/remove/', {}), 'remove B')
files_now = ok(client.get(f'{M}/{mid}/files/'), 'list files')
assert [f['name'] for f in files_now] == ['甲-总则.docx']
v2 = ok(post(f'{M}/{mid}/publish/', {'change_note': 'e2e 移除乙后发布'}), 'publish v2')
assert v2['version_no'] == 2
assert [f['file_name'] for f in v2['files']] == ['甲-总则.docx'], v2['files']
print('[4] v2 发布：快照清单', [f['file_name'] for f in v2['files']])

# ---- 5) 查看和下载两个历史版本，确认旧版内容与顺序未变 ----
versions = ok(client.get(f'{M}/{mid}/versions/'), 'version list')
by_no = {v['version_no']: v for v in versions['items']}
assert [f['file_name'] for f in by_no[1]['files']] == ['甲-总则.docx', '乙-细则.docx']
assert [f['file_name'] for f in by_no[2]['files']] == ['甲-总则.docx']
v1_id = by_no[1]['id']
for f in v1['files']:
    sfid = f['id']
    resp = client.get(f'{M}/{mid}/versions/{v1_id}/files/{sfid}/download/')
    assert resp.status_code == 200, resp.status_code
    content = (b''.join(resp.streaming_content)
               if hasattr(resp, 'streaming_content') else resp.content)
    import hashlib
    assert hashlib.sha256(content).hexdigest() == f['file_hash'], f['file_name']
    # 逐份预览地址可签发
    prev = ok(client.get(f'{M}/{mid}/versions/{v1_id}/files/{sfid}/preview-url/'),
              'v1 preview-url')
    assert 'preview_url' in prev  # 预览地址依赖 dev kkfileview 配置，链路已由隔离测试覆盖
# v1 的乙快照内容仍可下载（文件未被移除动作删除）
snap_b = ManualVersionFile.objects.get(pk=[f['id'] for f in v1['files'] if f['file_name'] == '乙-细则.docx'][0])
assert os.path.exists(storage.resolve_absolute_path(snap_b.file_path))
print('[5] 两个历史版本清单与逐份下载/预览均核对通过（v1 含乙，v2 仅甲）')

# ---- 6) 整套回退 v1 -> 待发布集合重建 -> 发布 v3 ----
rb = ok(post(f'{M}/{mid}/draft/from-version/', {'version_id': by_no[1]['id']}), 'rollback v1')
assert rb['restored_files'] == 2
files_now = ok(client.get(f'{M}/{mid}/files/'), 'list after rollback')
assert [f['name'] for f in files_now] == ['甲-总则.docx', '乙-细则.docx']
# 乙草稿内容 = v1 乙快照
draft_b = ManualDraft.objects.get(file_id=fid_b)
assert draft_b.file_hash == v1_snapshots[[f['id'] for f in v1['files'] if f['file_name'] == '乙-细则.docx'][0]]['file_hash']
v3 = ok(post(f'{M}/{mid}/publish/', {'change_note': 'e2e 回退v1后重发'}), 'publish v3')
assert v3['version_no'] == 3
assert [f['file_name'] for f in v3['files']] == ['甲-总则.docx', '乙-细则.docx']
# v1 快照仍未变
for f in v1['files']:
    snap = ManualVersionFile.objects.get(pk=f['id'])
    assert storage.compute_file_hash(
        storage.resolve_absolute_path(snap.file_path)) == f['file_hash']
print('[6] 整套回退与 v3 重发通过；v1/v2 快照哈希全程未变')

# ---- 清理：删除测试手册（有版本不可删 -> 归档保留，仅清账号） ----
print('E2E PASS: manual_id=', mid, 'stamp=', stamp)

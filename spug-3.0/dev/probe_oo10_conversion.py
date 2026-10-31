# -*- coding: utf-8 -*-
"""OO 10.0 对照探测：ConversionService 签名转换请求 + Command forcesave。

在 tdyw-test 容器内运行（真实代码路径，不 mock 网络）：
  cd /data/spug/spug_api && DJANGO_SETTINGS_MODULE=spug.settings \
      python /data/spug/dev/probe_oo10_conversion.py

只读探测：不写库、不改配置；转换/命令请求使用真实 JWT 签名与真实 HTTP。
"""
import json
import sys
import uuid

import django

django.setup()

import requests

from django.conf import settings
from apps.account.models import User
from apps.institution import editor_services
from apps.institution.models import Manual, ManualDraft, ManualFile
from apps.institution import storage
from apps.institution.onlyoffice_jwt import sign_payload
from apps.institution.views_draft import build_editor_token

MANUAL_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 8
FILE_ID = int(sys.argv[2]) if len(sys.argv) > 2 else 5

OO10 = 'http://onlyoffice-10'          # dev_default 网络直连 10.0 对照容器
PUBLIC_BASE = 'http://tdyw-test'       # DS 回源 spug API 基址（与 compose 一致）


def hr(title):
    print()
    print('=' * 72)
    print(title)
    print('=' * 72)


def main():
    manual = Manual.objects.filter(pk=MANUAL_ID).first()
    file_entry = ManualFile.objects.filter(pk=FILE_ID, manual=manual).first()
    draft = ManualDraft.objects.filter(file=file_entry).first()
    assert manual and file_entry and draft, 'sample manual/file/draft missing'
    abs_path = storage.resolve_absolute_path(draft.file_path)
    with open(abs_path, 'rb') as f:
        head = f.read(4)
    print('manual=%s file=%s revision=%s' % (manual.id, file_entry.id, draft.revision))
    print('draft file: %s exists=%s zip_magic=%s' % (abs_path, bool(head == b'PK\x03\x04'), head))

    user = (User.objects.filter(is_active=True, username='admin').first()
            or User.objects.filter(is_active=True).first())
    token = build_editor_token(manual, file_entry, draft, user)
    file_url = (
        '%s/api/institution/manuals/%d/files/%d/attachments/oo-editor-file/?token=%s'
        % (PUBLIC_BASE, manual.id, file_entry.id, token)
    )
    print('file_url host reachable check (from tdyw-test itself):')
    resp = requests.get(file_url, timeout=15)
    print('  GET oo-editor-file ->', resp.status_code, resp.headers.get('Content-Type'),
          'bytes=%s' % len(resp.content), 'magic=%r' % resp.content[:2])

    conv_body = {
        'async': False,
        'filetype': 'docx',
        'outputtype': 'pdf',
        'key': 'probe-%s' % uuid.uuid4().hex[:12],
        'title': 'probe-%s.docx' % uuid.uuid4().hex[:6],
        'url': file_url,
    }
    conv_token = sign_payload(conv_body, settings.ONLYOFFICE_JWT_SECRET)

    targets = [
        ('10.0 /converter', OO10 + '/converter'),
        ('10.0 /ConvertService.ashx', OO10 + '/ConvertService.ashx'),
    ]
    for label, url in targets:
        hr('CONVERT -> %s (%s)' % (label, url))
        body = dict(conv_body)
        body['key'] = 'probe-%s' % uuid.uuid4().hex[:12]
        body['title'] = 'probe-%s.docx' % uuid.uuid4().hex[:6]
        body['token'] = sign_payload(body, settings.ONLYOFFICE_JWT_SECRET)
        try:
            r = requests.post(url, json=body, timeout=120)
            print('HTTP', r.status_code, r.headers.get('Content-Type'))
            print(r.text[:800])
        except Exception as e:
            print('REQUEST FAILED:', type(e).__name__, e)

    hr('CONVERT unsigned (JWT enforcement check, 10.0 /converter)')
    try:
        r = requests.post(OO10 + '/converter', json=dict(conv_body), timeout=60)
        print('HTTP', r.status_code)
        print(r.text[:400])
    except Exception as e:
        print('REQUEST FAILED:', type(e).__name__, e)

    hr('COMMAND forcesave via real _post_command (10.0 /command only, '
       'key absent -> expect error 1)')
    data, err = editor_services._post_command(
        OO10, {'c': 'forcesave',
               'key': 'probe-absent-%s' % uuid.uuid4().hex[:8]})
    print('10.0 -> data=%s err=%s' % (data, err))


if __name__ == '__main__':
    main()

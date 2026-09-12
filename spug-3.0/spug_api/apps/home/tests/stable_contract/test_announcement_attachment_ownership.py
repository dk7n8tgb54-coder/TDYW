# -*- coding: utf-8 -*-
"""公告附件跨模块越权回归测试（stable_contract）

背景：
    `apps/home/announcement.py` 的 `AnnouncementAttachmentDeleteView` 此前直接调用
    `AttachmentService.soft_delete(request.user, form.id, delete_file=True)`，
    服务层只按租户过滤，导致持有 `home.announcement.delete` 权限的管理员可枚举
    自增附件 ID，软删除同租户其他模块（执照 / 批复 / 合同 / 干扰 / 升级等）的附件。

修复后契约：
    归属校验下沉到 AttachmentService，公告管理端只放行
    module='announcement' / object_type='announcement' 的附件。
"""
import json
import os
import shutil
import tempfile
import time

from django.test import TestCase, Client
from django.utils import timezone

from apps.account.models import Role, User
from apps.evidence.models import EvidenceAttachment
from apps.home.models import Announcement, SCOPE_ALL, STATUS_UNPUBLISHED
from apps.utils.test_helpers import setup_test_env

ANN_MODULE = 'announcement'
ANN_OBJECT_TYPE = 'announcement'
# 同租户的其他模块附件（模拟被枚举到的越权目标）
OTHER_MODULE = 'radio_license'
OTHER_OBJECT_TYPE = 'license'

ANN_PERMS = [('home', 'announcement', [
    'view', 'add', 'edit', 'delete', 'publish', 'withdraw',
])]


def _make_user(username, tenant_id='default'):
    token = (username * 10)[:32]
    return User.objects.create(
        username=username, nickname=username, password_hash='x',
        is_active=True, is_supper=False, access_token=token,
        token_expired=int(time.time()) + 3600, last_login='2026-01-01',
        last_ip='127.0.0.1', type='default', tenant_id=tenant_id,
    )


def _make_client(user):
    client = Client()
    client.defaults['HTTP_X_TOKEN'] = user.access_token
    client.defaults['HTTP_X_FORWARDED_FOR'] = '10.0.0.1'
    return client


def _grant_perms(user, perms):
    """按模块/页面/权限码授予角色权限（沿用公告特征测试的授权方式）"""
    perm_dict = {}
    for module, page, keys in perms:
        perm_dict.setdefault(module, {}).setdefault(page, []).extend(keys)
    role = Role.objects.create(
        name=f'role_{user.username}',
        page_perms=json.dumps(perm_dict),
        created_by=user,
    )
    user.roles.add(role)
    user.set_perms_cache()
    return role


class AnnouncementAttachmentOwnershipTest(TestCase):
    """公告管理端删除不得删除其他模块附件，同时必须能删除本公告附件"""

    def setUp(self):
        setup_test_env(self)
        self.media = tempfile.mkdtemp(prefix='announcement_attachment_')
        self.addCleanup(shutil.rmtree, self.media, True)

        settings_ctx = self.settings(MEDIA_ROOT=self.media)
        settings_ctx.enable()
        self.addCleanup(settings_ctx.disable)

        self.admin = _make_user('ann_att_admin', tenant_id='tenant_a')
        _grant_perms(self.admin, ANN_PERMS)
        self.client_auth = _make_client(self.admin)

        self.announcement = Announcement.objects.create(
            tenant_id=self.admin.tenant_id,
            title='附件归属测试公告',
            content='公告内容',
            scope_type=SCOPE_ALL,
            effective_start_at=timezone.now(),
            status=STATUS_UNPUBLISHED,
            created_by_id=self.admin.id,
            created_by_name=self.admin.nickname,
            publish_department_id=self.admin.tenant_id,
            publish_department_name=self.admin.tenant_id,
        )

    def _make_attachment(self, module, object_type, object_id, file_name='proof.pdf'):
        rel = os.path.join(module, self.admin.tenant_id, '202601',
                           f'{object_type}_{object_id}', file_name)
        abs_path = os.path.join(self.media, rel)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        with open(abs_path, 'wb') as f:
            f.write(b'pdf-body')
        return EvidenceAttachment.objects.create(
            tenant_id=self.admin.tenant_id,
            module=module,
            object_type=object_type,
            object_id=str(object_id),
            file_name=file_name,
            file_path=rel,
            file_size=8,
            file_ext='.pdf',
            file_hash_sha256='a' * 64,
            uploaded_by_id=self.admin.id,
            uploaded_by_name=self.admin.nickname,
        )

    @staticmethod
    def _is_deleted(attachment_id):
        return EvidenceAttachment.objects.all_with_deleted().get(pk=attachment_id).is_deleted

    def test_other_module_attachment_delete_rejected(self):
        att = self._make_attachment(OTHER_MODULE, OTHER_OBJECT_TYPE, 999)
        resp = self.client_auth.delete(f'/home/announcement/admin/attachments/?id={att.id}')
        data = resp.json()
        self.assertTrue(data.get('error'), '其他模块附件不应可被公告管理端删除')
        self.assertEqual(data.get('error'), '附件不存在或无权限删除')
        self.assertFalse(self._is_deleted(att.id), '被拒绝的删除不应改动附件')
        self.assertIsNone(
            EvidenceAttachment.objects.all_with_deleted().get(pk=att.id).deleted_at,
            '被拒绝的删除不应写入删除痕迹',
        )

    def test_wrong_object_type_delete_rejected(self):
        """同模块但对象类型不符的附件同样拒绝"""
        att = self._make_attachment(ANN_MODULE, 'notice_draft', 999)
        resp = self.client_auth.delete(f'/home/announcement/admin/attachments/?id={att.id}')
        self.assertTrue(resp.json().get('error'), '对象类型不符的附件不应可被删除')
        self.assertFalse(self._is_deleted(att.id), '被拒绝的删除不应改动附件')

    def test_own_announcement_attachment_delete_ok(self):
        """正向对照：公告自身附件仍可正常软删除"""
        att = self._make_attachment(ANN_MODULE, ANN_OBJECT_TYPE, self.announcement.id)
        resp = self.client_auth.delete(f'/home/announcement/admin/attachments/?id={att.id}')
        self.assertFalse(resp.json().get('error'), resp.json())
        self.assertTrue(self._is_deleted(att.id), '公告自身附件应被软删除')

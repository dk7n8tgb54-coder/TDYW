# -*- coding: utf-8 -*-
"""AttachmentService 磁盘文件名唯一化 stable_contract 测试

背景：
    附件落盘历史上直接使用清洗后的原始文件名，重名靠 os.path.exists 加序号，
    存在两个问题：
    1. 存在性检查与写入之间有时间窗，并发上传同名文件会互相覆盖（TOCTOU 竞态）；
    2. 不同业务对象目录下同名文件磁盘名相同，kkFileView 以文件名作为预览缓存键，
       会跨对象命中旧缓存。

修复后契约（与资料库命名规范 apps/document/libs/naming_utils.py 同口径）：
    1. 默认落盘名 = {清洗后原始名}_{13位毫秒时间戳}_{6位hex随机串}{原始扩展名}；
    2. 同名重复上传磁盘名必然不同，物理文件共存；
    3. 用户可见名 file_name 始终保留原始文件名，磁盘重命名对用户零感知；
    4. 落盘名不超过 Linux 255 字节限制且保留扩展名；
    5. 显式传入 disk_name 的调用方（如签名图片 UUID 名）行为不变。
"""
import os
import shutil
import tempfile

from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from apps.evidence.attachment_service import AttachmentService
from apps.utils.test_helpers import make_user, setup_test_env

MODULE = 'diskname_mod'
OBJECT_TYPE = 'obj'
TENANT = 'tenant_a'


class AttachmentDiskNameTestCase(TestCase):
    """默认上传生成唯一磁盘名；显式 disk_name 行为不变"""

    def setUp(self):
        setup_test_env(self)
        self.media = tempfile.mkdtemp(prefix='evidence_diskname_')
        self.addCleanup(shutil.rmtree, self.media, True)

        settings_ctx = self.settings(MEDIA_ROOT=self.media)
        settings_ctx.enable()
        self.addCleanup(settings_ctx.disable)

        self.user = make_user('diskname_user')
        self.user.tenant_id = TENANT
        self.user.save()

    # ---------------- 工具 ----------------

    def _upload(self, filename, disk_name=None):
        att, error = AttachmentService.upload(
            file=SimpleUploadedFile(filename, b'attachment-body'),
            user=self.user,
            module=MODULE,
            object_type=OBJECT_TYPE,
            object_id='1',
            disk_name=disk_name,
        )
        self.assertIsNone(error, error)
        return att

    @staticmethod
    def _disk_basename(att):
        return os.path.basename(att.file_path)

    # ---------------- 1. 默认命名格式 ----------------

    def test_disk_name_keeps_original_prefix_and_ext(self):
        att = self._upload('项目验收报告.pdf')
        basename = self._disk_basename(att)
        self.assertRegex(basename, r'^项目验收报告_\d{13}_[0-9a-f]{6}\.pdf$')
        self.assertTrue(os.path.exists(os.path.join(settings.MEDIA_ROOT, att.file_path)))

    def test_file_name_field_keeps_original_name(self):
        att = self._upload('对外显示名.xlsx')
        self.assertEqual(att.file_name, '对外显示名.xlsx')

    # ---------------- 2. 同名重传唯一性 ----------------

    def test_duplicate_uploads_get_unique_disk_names(self):
        att1 = self._upload('同名文件.docx')
        att2 = self._upload('同名文件.docx')
        self.assertNotEqual(self._disk_basename(att1), self._disk_basename(att2))
        for att in (att1, att2):
            self.assertTrue(os.path.exists(os.path.join(settings.MEDIA_ROOT, att.file_path)))

    # ---------------- 3. 长文件名字节截断 ----------------

    def test_long_filename_truncated_to_255_bytes(self):
        att = self._upload('超' * 300 + '.pdf')
        basename = self._disk_basename(att)
        self.assertLessEqual(len(basename.encode('utf-8')), 255)
        self.assertTrue(basename.endswith('.pdf'), basename)
        self.assertTrue(os.path.exists(os.path.join(settings.MEDIA_ROOT, att.file_path)))

    # ---------------- 4. 显式 disk_name 行为不变 ----------------

    def test_explicit_disk_name_still_respected(self):
        att = self._upload('ignored.png', disk_name='custom-uuid-name.png')
        self.assertEqual(self._disk_basename(att), 'custom-uuid-name.png')

    # ---------------- 5. 路径穿越清洗仍生效 ----------------

    def test_path_traversal_sanitized_in_disk_name(self):
        att = self._upload('../../../../etc/passwd.pdf')
        basename = self._disk_basename(att)
        self.assertNotIn('..', att.file_path)
        self.assertTrue(basename.startswith('passwd'), basename)
        self.assertTrue(basename.endswith('.pdf'), basename)

"""
盘点并修复党建文档复制时物理文件错误落入普通 public 目录的历史数据。

用法：
    # dry-run（默认）：只输出盘点清单，不执行任何修改
    python manage.py audit_pb_file_paths

    # 实际执行修复（移动物理文件 + 更新 DB 记录）
    python manage.py audit_pb_file_paths --apply

逻辑：
1. 获取党建根文件夹 ID
2. 查找所有 folder 在党建目录树下的 DocumentFilePublic 记录
3. 检查每条记录的 file_path 是否位于 party_building_documents/files 下
4. 若不在，则为"污染"记录
5. --apply 时：移动物理文件到正确目录，更新 DB file_path
   - 移动前检查：源文件存在、目标无冲突、哈希一致、无其他 DB 记录共享
   - 物理操作成功后再更新数据库
"""
import os
import hashlib
import shutil

from django.core.management.base import BaseCommand
from django.conf import settings

from apps.document.models import (
    DocumentFilePublic,
    DocumentSystemFolder,
)
from apps.document.libs.document_utils import (
    get_document_absolute_path,
    get_document_relative_path,
    PARTY_BUILDING_DOCUMENTS_SYSTEM_FOLDER,
)
from apps.document.services.system_folder_service import (
    get_system_root_folder_id,
    is_folder_in_scope,
)

PB_CODE = PARTY_BUILDING_DOCUMENTS_SYSTEM_FOLDER


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


class Command(BaseCommand):
    help = '盘点并修复党建文档 file_path 不在 party_building_documents/files 下的记录'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            default=False,
            help='实际执行修复（默认 dry-run 只输出清单）',
        )

    def handle(self, *args, **options):
        apply_mode = options['apply']

        # 1. 获取党建根文件夹 ID
        root_folder_id = get_system_root_folder_id(PB_CODE)
        if root_folder_id is None:
            self.stdout.write(self.style.WARNING(
                f'未找到 code={PB_CODE} 的 DocumentSystemFolder，无污染数据。'
            ))
            return

        # 2. 查找所有党建目录树下的文件
        all_files = DocumentFilePublic.objects.all()
        pb_files = []
        polluted = []

        for f in all_files:
            if f.folder_id is None:
                continue
            if not is_folder_in_scope(f.folder_id, PB_CODE):
                continue
            pb_files.append(f)

            # 3. 检查 file_path 是否在 party_building_documents/files 下
            pb_base = get_document_absolute_path(
                is_public=True, system_folder=PB_CODE
            )
            if not f.file_path.startswith(pb_base + os.sep):
                polluted.append(f)

        self.stdout.write(self.style.NOTICE(
            f'党建目录树下文件总数: {len(pb_files)}'
        ))
        self.stdout.write(self.style.NOTICE(
            f'污染记录数（file_path 不在党建目录）: {len(polluted)}'
        ))

        if not polluted:
            self.stdout.write(self.style.SUCCESS('无污染数据，无需修复。'))
            return

        # 4. 输出污染清单
        self.stdout.write('')
        self.stdout.write(self.style.NOTICE('=== 污染记录清单（dry-run）==='))
        for f in polluted:
            pb_dir = get_document_absolute_path(
                is_public=True,
                folder_id=f.folder_id,
                system_folder=PB_CODE,
            )
            expected_prefix = pb_dir + os.sep
            self.stdout.write(f'  [id={f.id}] name={f.display_name}')
            self.stdout.write(f'    当前 file_path: {f.file_path}')
            self.stdout.write(f'    期望目录前缀:   {expected_prefix}')
            self.stdout.write(f'    物理文件存在:   {os.path.isfile(f.file_path)}')
            self.stdout.write('')

        if not apply_mode:
            self.stdout.write(self.style.WARNING(
                'dry-run 模式：未执行任何修改。如需修复，请添加 --apply 参数。'
            ))
            return

        # 5. --apply：执行修复
        self.stdout.write(self.style.NOTICE('=== 开始修复 ==='))
        fixed = 0
        skipped = 0

        for f in polluted:
            ok, msg = self._fix_record(f)
            if ok:
                fixed += 1
                self.stdout.write(self.style.SUCCESS(
                    f'  [id={f.id}] 修复成功: {msg}'
                ))
            else:
                skipped += 1
                self.stdout.write(self.style.ERROR(
                    f'  [id={f.id}] 跳过: {msg}'
                ))

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'修复完成: {fixed} 条已修复, {skipped} 条跳过'
        ))

    def _fix_record(self, f):
        """
        修复单条记录：移动物理文件到正确目录并更新 DB。

        Returns:
            (True, msg) 或 (False, reason)
        """
        # 计算正确目标目录
        pb_dir = get_document_absolute_path(
            is_public=True,
            folder_id=f.folder_id,
            system_folder=PB_CODE,
        )
        target_path = os.path.join(pb_dir, f.physical_name)

        # 检查 1: 源文件存在
        if not os.path.isfile(f.file_path):
            return False, f'源文件不存在: {f.file_path}'

        # 检查 2: 目标路径无冲突
        if os.path.exists(target_path):
            # 如果是同一个文件（路径相同），跳过
            if os.path.abspath(f.file_path) == os.path.abspath(target_path):
                return False, '源路径和目标路径相同，无需修复'
            return False, f'目标路径已存在: {target_path}'

        # 检查 3: 无其他 DB 记录共享同一 file_path
        shared = DocumentFilePublic.objects.filter(
            file_path=f.file_path
        ).exclude(id=f.id).exists()
        if shared:
            return False, f'file_path 被其他 DB 记录共享，需人工处理'

        # 检查 4: 移动前哈希
        src_hash = _sha256(f.file_path)

        # 执行物理移动
        os.makedirs(pb_dir, exist_ok=True)
        shutil.move(f.file_path, target_path)

        # 验证移动后文件存在且哈希一致
        if not os.path.isfile(target_path):
            return False, f'移动后目标文件不存在: {target_path}'
        dst_hash = _sha256(target_path)
        if src_hash != dst_hash:
            # 回滚
            shutil.move(target_path, f.file_path)
            return False, '移动后哈希不一致，已回滚'

        # 物理操作成功后更新数据库
        f.file_path = target_path
        f.save(update_fields=['file_path'])

        return True, f'{f.file_path} -> {target_path}'

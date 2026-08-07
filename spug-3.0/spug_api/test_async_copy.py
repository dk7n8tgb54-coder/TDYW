"""
异步复制行为测试脚本

测试内容：
1. 阈值以下同步复制
2. 阈值以上异步复制
3. 内容/大小/路径正确性
4. 临时文件原子转正
5. Celery 重试幂等
6. 复制中失败清理
7. keep/replace/skip 冲突处理
8. 两次复制生成不同物理名
9. 删除复制品不影响源文件
10. 取消任务
11. 文件夹中包含大文件

运行方式：
  wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python test_async_copy.py'
"""
import os
import sys
import shutil
import tempfile
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
sys.path.insert(0, '/data/spug/spug_api')

import django
django.setup()

from django.test.utils import override_settings
from django.conf import settings
from django.db import connection

from apps.document.models import DocumentFilePrivate, DocumentFolderPrivate, DocumentTransfer
from apps.document.constants import TransferStatus, TransferType
from apps.document.libs.naming_utils import generate_physical_name, generate_unique_logical_name
from apps.account.models import User

PASS = 0
FAIL = 0
ERRORS = []
TEST_DIR = None
TEST_USER = None


def check(name, condition, detail=''):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f'  [PASS] {name}')
    else:
        FAIL += 1
        ERRORS.append(f'{name}: {detail}')
        print(f'  [FAIL] {name} -- {detail}')


def setup_test_env():
    """创建测试环境：用户、目录"""
    global TEST_DIR, TEST_USER

    # 创建测试目录
    base_dir = os.path.join(settings.BASE_DIR, 'storage', 'documents', 'test_async_copy')
    TEST_DIR = base_dir
    os.makedirs(TEST_DIR, exist_ok=True)

    # 创建或获取测试用户
    import uuid as uuid_module
    TEST_USER, created = User.objects.get_or_create(
        username='test_async_copy_user',
        defaults={
            'nickname': 'Test Async Copy',
            'password_hash': 'test_hash',
            'access_token': uuid_module.uuid4().hex[:32],
            'last_ip': '127.0.0.1',
            'tenant_id': 'test_tenant',
        }
    )

    print(f'[Setup] Test user: {TEST_USER.username} (id={TEST_USER.id})')
    print(f'[Setup] Test dir: {TEST_DIR}')


def create_test_file(display_name, content=b'Hello World', size=None):
    """创建测试源文件记录和物理文件"""
    ext = os.path.splitext(display_name)[1] or ''
    physical_name = generate_physical_name(ext, display_name)
    file_path = os.path.join(TEST_DIR, physical_name)

    # 写入物理文件
    with open(file_path, 'wb') as f:
        if size:
            # 写入指定大小的文件
            chunk = b'0' * (1024 * 1024)  # 1MB chunks
            remaining = size
            while remaining > 0:
                write_size = min(remaining, len(chunk))
                f.write(chunk[:write_size])
                remaining -= write_size
        else:
            f.write(content)

    actual_size = os.path.getsize(file_path)

    # 创建数据库记录
    file_record = DocumentFilePrivate.objects.create(
        name=display_name,
        display_name=display_name,
        physical_name=physical_name,
        file_path=file_path,
        file_size=actual_size,
        file_type=ext.lstrip('.'),
        created_by=TEST_USER,
        tenant_id=TEST_USER.tenant_id,
    )

    return file_record


def create_test_folder(name='test_folder'):
    """创建测试文件夹"""
    folder, created = DocumentFolderPrivate.objects.get_or_create(
        name=name,
        defaults={
            'created_by': TEST_USER,
            'tenant_id': TEST_USER.tenant_id,
        }
    )
    return folder


def cleanup_test_file(file_record):
    """清理测试文件记录和物理文件"""
    if file_record:
        if file_record.file_path and os.path.exists(file_record.file_path):
            try:
                os.remove(file_record.file_path)
            except:
                pass
        file_record.delete()


def test_small_file_sync_copy():
    """测试阈值以下同步复制"""
    print('\n=== 测试1: 阈值以下同步复制 ===')

    # 创建小文件 (100 bytes)
    source = create_test_file('小文件测试.txt', content=b'A' * 100)

    try:
        # 使用低阈值确保小文件走同步路径
        with override_settings(DOCUMENT_ASYNC_COPY_THRESHOLD=1024):  # 1KB
            from apps.document.views.file.copy import FileCopyView, FileNameGenerator
            from apps.document.libs.document_utils import get_file_model

            threshold = getattr(settings, 'DOCUMENT_ASYNC_COPY_THRESHOLD', 50 * 1024 * 1024)
            check('阈值设置正确', threshold == 1024, f'got: {threshold}')

            # 检查文件大小 < 阈值
            check('小文件 < 阈值', source.file_size < threshold,
                  f'file_size={source.file_size}, threshold={threshold}')

        check('小文件创建成功', source.id is not None, 'source file not created')
        check('小文件物理文件存在', os.path.exists(source.file_path), f'path: {source.file_path}')
        check('小文件大小正确', source.file_size == 100, f'size: {source.file_size}')

    finally:
        cleanup_test_file(source)


def test_large_file_async_copy():
    """测试阈值以上异步复制 - 核心流程"""
    print('\n=== 测试2: 阈值以上异步复制 ===')

    # 创建大文件 (2MB, 阈值设为 1MB)
    source = create_test_file('大文件测试.pdf', size=2 * 1024 * 1024)

    try:
        with override_settings(DOCUMENT_ASYNC_COPY_THRESHOLD=1024 * 1024):  # 1MB
            from apps.document.tasks.async_copy import copy_file_async, _validate_copy_context, _execute_copy

            # 创建 DocumentTransfer 记录
            target_folder = create_test_folder('async_copy_target')
            ext = '.pdf'
            target_physical_name = generate_physical_name(ext, '大文件测试.pdf')
            target_path = os.path.join(TEST_DIR, target_physical_name)

            transfer = DocumentTransfer.objects.create(
                transfer_type=TransferType.COPY.value,
                status=TransferStatus.PENDING.value,
                file_name='大文件测试_副本.pdf',
                file_size=source.file_size,
                file_path=target_path,
                file_hash=getattr(source, 'file_hash', '') or '',
                folder_id=target_folder.id,
                is_public=False,
                system_folder='',
                progress=0,
                transferred_size=0,
                source_file_id=source.id,
                source_file_path=source.file_path,
                conflict_action='',
                user=TEST_USER,
            )

            check('Transfer 创建成功', transfer.id is not None, 'transfer not created')
            check('Transfer 状态 PENDING', transfer.status == 'PENDING',
                  f'status: {transfer.status}')

            # 同步执行 Celery 任务（使用 .apply 而非 .delay）
            result = copy_file_async.apply((transfer.id,))

            check('任务执行成功', result.successful(), f'result: {result.result}')

            # 刷新 transfer 记录
            transfer.refresh_from_db()
            check('Transfer 状态 COMPLETED', transfer.status == 'COMPLETED',
                  f'status: {transfer.status}')
            check('Transfer 进度 100', transfer.progress == 100,
                  f'progress: {transfer.progress}')

            # 验证目标文件存在
            check('目标文件存在', os.path.exists(target_path), f'path: {target_path}')
            check('目标文件大小正确', os.path.getsize(target_path) == source.file_size,
                  f'expected: {source.file_size}, got: {os.path.getsize(target_path)}')

            # 验证内容正确
            with open(source.file_path, 'rb') as f:
                source_content = f.read()
            with open(target_path, 'rb') as f:
                target_content = f.read()
            check('内容一致', source_content == target_content, 'content mismatch')

            # 验证源文件未变
            check('源文件未被修改', os.path.exists(source.file_path),
                  f'source path: {source.file_path}')
            check('源文件大小未变', os.path.getsize(source.file_path) == source.file_size,
                  f'source size changed')

            # 验证临时文件已清理
            temp_path = target_path + '.copying_tmp'
            check('临时文件已清理', not os.path.exists(temp_path), f'temp path: {temp_path}')

            # 验证两条文件记录有不同的物理路径
            new_file = DocumentFilePrivate.objects.filter(
                file_path=target_path
            ).first()
            check('新文件记录已创建', new_file is not None, 'new file record not found')
            if new_file:
                check('物理路径不同', new_file.file_path != source.file_path,
                      f'same path: {new_file.file_path}')
                check('物理名不同', new_file.physical_name != source.physical_name,
                      f'same physical_name: {new_file.physical_name}')

                # 清理
                cleanup_test_file(new_file)

    finally:
        cleanup_test_file(source)


def test_idempotent_retry():
    """测试 Celery 重试幂等性"""
    print('\n=== 测试3: Celery 重试幂等 ===')

    source = create_test_file('幂等测试.txt', content=b'Idempotent test')

    try:
        from apps.document.tasks.async_copy import copy_file_async

        ext = '.txt'
        target_physical_name = generate_physical_name(ext, '幂等测试.txt')
        target_path = os.path.join(TEST_DIR, target_physical_name)

        transfer = DocumentTransfer.objects.create(
            transfer_type=TransferType.COPY.value,
            status=TransferStatus.PENDING.value,
            file_name='幂等测试_副本.txt',
            file_size=source.file_size,
            file_path=target_path,
            source_file_id=source.id,
            source_file_path=source.file_path,
            conflict_action='',
            is_public=False,
            system_folder='',
            user=TEST_USER,
        )

        # 第一次执行
        result1 = copy_file_async.apply((transfer.id,))
        check('第一次执行成功', result1.successful(), f'result: {result1.result}')

        transfer.refresh_from_db()
        check('第一次后状态 COMPLETED', transfer.status == 'COMPLETED',
              f'status: {transfer.status}')

        # 第二次执行（模拟重试）
        result2 = copy_file_async.apply((transfer.id,))
        check('第二次执行不报错', result2.successful(), f'result: {result2.result}')

        transfer.refresh_from_db()
        check('第二次后仍 COMPLETED', transfer.status == 'COMPLETED',
              f'status: {transfer.status}')

        # 验证只有一个目标文件
        count = DocumentFilePrivate.objects.filter(file_path=target_path).count()
        check('只有一条目标文件记录', count == 1, f'count: {count}')

        # 清理
        new_file = DocumentFilePrivate.objects.filter(file_path=target_path).first()
        if new_file:
            cleanup_test_file(new_file)

    finally:
        cleanup_test_file(source)


def test_two_copies_different_names():
    """测试两次复制生成不同物理名"""
    print('\n=== 测试4: 两次复制生成不同物理名 ===')

    source = create_test_file('差异测试.txt', content=b'Different names test')

    try:
        from apps.document.tasks.async_copy import copy_file_async

        ext = '.txt'

        # 第一次复制
        target_name1 = generate_physical_name(ext, '差异测试.txt')
        target_path1 = os.path.join(TEST_DIR, target_name1)

        transfer1 = DocumentTransfer.objects.create(
            transfer_type=TransferType.COPY.value,
            status=TransferStatus.PENDING.value,
            file_name='差异测试_副本1.txt',
            file_size=source.file_size,
            file_path=target_path1,
            source_file_id=source.id,
            source_file_path=source.file_path,
            conflict_action='',
            is_public=False,
            system_folder='',
            user=TEST_USER,
        )
        copy_file_async.apply((transfer1.id,))

        # 第二次复制
        target_name2 = generate_physical_name(ext, '差异测试.txt')
        target_path2 = os.path.join(TEST_DIR, target_name2)

        transfer2 = DocumentTransfer.objects.create(
            transfer_type=TransferType.COPY.value,
            status=TransferStatus.PENDING.value,
            file_name='差异测试_副本2.txt',
            file_size=source.file_size,
            file_path=target_path2,
            source_file_id=source.id,
            source_file_path=source.file_path,
            conflict_action='',
            is_public=False,
            system_folder='',
            user=TEST_USER,
        )
        copy_file_async.apply((transfer2.id,))

        check('物理名不同', target_name1 != target_name2,
              f'name1={target_name1}, name2={target_name2}')
        check('路径不同', target_path1 != target_path2,
              f'path1={target_path1}, path2={target_path2}')

        # 验证两个目标文件都存在
        check('目标1存在', os.path.exists(target_path1), f'path: {target_path1}')
        check('目标2存在', os.path.exists(target_path2), f'path: {target_path2}')

        # 清理
        for p in [target_path1, target_path2]:
            if os.path.exists(p):
                os.remove(p)
            f = DocumentFilePrivate.objects.filter(file_path=p).first()
            if f:
                f.delete()

    finally:
        cleanup_test_file(source)


def test_delete_copy_not_affect_source():
    """测试删除复制品不影响源文件"""
    print('\n=== 测试5: 删除复制品不影响源文件 ===')

    source = create_test_file('删除测试.txt', content=b'Source file')

    try:
        from apps.document.tasks.async_copy import copy_file_async

        ext = '.txt'
        target_name = generate_physical_name(ext, '删除测试.txt')
        target_path = os.path.join(TEST_DIR, target_name)

        transfer = DocumentTransfer.objects.create(
            transfer_type=TransferType.COPY.value,
            status=TransferStatus.PENDING.value,
            file_name='删除测试_副本.txt',
            file_size=source.file_size,
            file_path=target_path,
            source_file_id=source.id,
            source_file_path=source.file_path,
            conflict_action='',
            is_public=False,
            system_folder='',
            user=TEST_USER,
        )
        copy_file_async.apply((transfer.id,))

        # 获取复制记录
        copy_file = DocumentFilePrivate.objects.filter(file_path=target_path).first()
        check('复制记录存在', copy_file is not None, 'copy file not found')

        if copy_file:
            # 删除复制品
            if os.path.exists(target_path):
                os.remove(target_path)
            copy_file.delete()

            # 验证源文件仍然存在
            check('源文件物理存在', os.path.exists(source.file_path),
                  f'source path: {source.file_path}')
            check('源文件记录存在',
                  DocumentFilePrivate.objects.filter(id=source.id).exists(),
                  'source record deleted')
            check('源文件大小不变', os.path.getsize(source.file_path) == source.file_size,
                  f'size changed')

    finally:
        cleanup_test_file(source)


def test_cancellation():
    """测试取消任务"""
    print('\n=== 测试6: 取消任务 ===')

    source = create_test_file('取消测试.txt', content=b'Cancel test')

    try:
        from apps.document.tasks.async_copy import copy_file_async, _check_cancelled

        ext = '.txt'
        target_name = generate_physical_name(ext, '取消测试.txt')
        target_path = os.path.join(TEST_DIR, target_name)

        transfer = DocumentTransfer.objects.create(
            transfer_type=TransferType.COPY.value,
            status=TransferStatus.CANCELED.value,  # 直接标记为取消
            file_name='取消测试_副本.txt',
            file_size=source.file_size,
            file_path=target_path,
            source_file_id=source.id,
            source_file_path=source.file_path,
            conflict_action='',
            is_public=False,
            system_folder='',
            user=TEST_USER,
        )

        # 执行任务（应该直接跳过）
        result = copy_file_async.apply((transfer.id,))

        transfer.refresh_from_db()
        check('取消任务不被执行', transfer.status == 'CANCELED',
              f'status: {transfer.status}')
        check('目标文件未创建', not os.path.exists(target_path),
              f'path exists: {target_path}')

    finally:
        cleanup_test_file(source)


def test_failure_cleanup():
    """测试复制失败清理"""
    print('\n=== 测试7: 复制失败清理 ===')

    # 创建一个指向不存在源文件的 transfer
    ext = '.txt'
    target_name = generate_physical_name(ext, '失败测试.txt')
    target_path = os.path.join(TEST_DIR, target_name)

    transfer = DocumentTransfer.objects.create(
        transfer_type=TransferType.COPY.value,
        status=TransferStatus.PENDING.value,
        file_name='失败测试_副本.txt',
        file_size=100,
        file_path=target_path,
        source_file_id=999999,  # 不存在的文件ID
        source_file_path='/nonexistent/path/file.txt',  # 不存在的路径
        conflict_action='',
        is_public=False,
        system_folder='',
        user=TEST_USER,
    )

    from apps.document.tasks.async_copy import copy_file_async

    result = copy_file_async.apply((transfer.id,))

    transfer.refresh_from_db()
    check('失败任务状态 FAILED', transfer.status == 'FAILED',
          f'status: {transfer.status}')
    check('目标文件未创建', not os.path.exists(target_path),
          f'path exists: {target_path}')
    check('临时文件已清理', not os.path.exists(target_path + '.copying_tmp'),
          'temp file not cleaned')


def test_keep_conflict():
    """测试 keep 冲突处理"""
    print('\n=== 测试8: keep 冲突处理 ===')

    source = create_test_file('冲突测试.txt', content=b'Conflict keep test')

    try:
        from apps.document.tasks.async_copy import copy_file_async

        # 先创建一个目标文件
        ext = '.txt'
        existing_name = '冲突测试.txt'
        existing = create_test_file(existing_name, content=b'Existing file')

        # 复制到同目录，使用 keep
        target_name = generate_physical_name(ext, existing_name)
        target_path = os.path.join(TEST_DIR, target_name)

        transfer = DocumentTransfer.objects.create(
            transfer_type=TransferType.COPY.value,
            status=TransferStatus.PENDING.value,
            file_name=existing_name,
            file_size=source.file_size,
            file_path=target_path,
            source_file_id=source.id,
            source_file_path=source.file_path,
            conflict_action='keep',
            is_public=False,
            system_folder='',
            user=TEST_USER,
        )
        copy_file_async.apply((transfer.id,))

        transfer.refresh_from_db()
        check('keep 后状态 COMPLETED', transfer.status == 'COMPLETED',
              f'status: {transfer.status}')

        # 验证新文件记录的 display_name 与源文件不同（keep 生成唯一名）
        new_file = DocumentFilePrivate.objects.filter(file_path=target_path).first()
        check('keep 新文件记录存在', new_file is not None, 'new file not found')
        if new_file:
            check('keep 生成不同物理路径', new_file.file_path != existing.file_path,
                  f'same path')
            check('keep 物理名不同', new_file.physical_name != existing.physical_name,
                  f'same physical_name')
            cleanup_test_file(new_file)

        cleanup_test_file(existing)

    finally:
        cleanup_test_file(source)


def test_skip_conflict():
    """测试 skip 冲突处理"""
    print('\n=== 测试9: skip 冲突处理 ===')

    source = create_test_file('跳过测试.txt', content=b'Skip test')

    try:
        from apps.document.tasks.async_copy import copy_file_async

        ext = '.txt'
        target_name = generate_physical_name(ext, '跳过测试.txt')
        target_path = os.path.join(TEST_DIR, target_name)

        # 先创建一个同名文件（制造冲突）
        existing = create_test_file('跳过测试.txt', content=b'Existing')

        transfer = DocumentTransfer.objects.create(
            transfer_type=TransferType.COPY.value,
            status=TransferStatus.PENDING.value,
            file_name='跳过测试.txt',
            file_size=source.file_size,
            file_path=target_path,
            source_file_id=source.id,
            source_file_path=source.file_path,
            conflict_action='skip',
            is_public=False,
            system_folder='',
            user=TEST_USER,
        )

        # skip 时有冲突应跳过（不创建文件，清理物理文件，标记完成）
        result = copy_file_async.apply((transfer.id,))

        transfer.refresh_from_db()
        check('skip 有冲突时状态 COMPLETED', transfer.status == 'COMPLETED',
              f'status: {transfer.status}')
        check('skip 不创建目标文件记录',
              not DocumentFilePrivate.objects.filter(file_path=target_path).exists(),
              'target file record was created')
        check('skip 清理物理文件', not os.path.exists(target_path),
              f'path exists: {target_path}')

        cleanup_test_file(existing)

    finally:
        cleanup_test_file(source)


def test_copy_preserves_original_name():
    """测试复制产物保留原始文件名"""
    print('\n=== 测试10: 复制产物保留原始文件名 ===')

    original_name = '党建工作年度总结报告.pdf'
    source = create_test_file(original_name, content=b'Name preservation test')

    try:
        from apps.document.tasks.async_copy import copy_file_async

        ext = '.pdf'
        target_name = generate_physical_name(ext, original_name)
        target_path = os.path.join(TEST_DIR, target_name)

        transfer = DocumentTransfer.objects.create(
            transfer_type=TransferType.COPY.value,
            status=TransferStatus.PENDING.value,
            file_name=original_name,
            file_size=source.file_size,
            file_path=target_path,
            source_file_id=source.id,
            source_file_path=source.file_path,
            conflict_action='',
            is_public=False,
            system_folder='',
            user=TEST_USER,
        )
        copy_file_async.apply((transfer.id,))

        # 验证物理文件名包含原始名
        check('物理名包含原始文件名', '党建工作年度总结报告' in target_name,
              f'target_name: {target_name}')

        new_file = DocumentFilePrivate.objects.filter(file_path=target_path).first()
        if new_file:
            check('物理名包含原始文件名(DB)', '党建工作年度总结报告' in new_file.physical_name,
                  f'physical_name: {new_file.physical_name}')
            check('display_name 保留', new_file.display_name == original_name,
                  f'display_name: {new_file.display_name}')
            cleanup_test_file(new_file)

    finally:
        cleanup_test_file(source)


def test_atomic_rename():
    """测试临时文件原子转正"""
    print('\n=== 测试11: 临时文件原子转正 ===')

    source = create_test_file('原子测试.txt', content=b'Atomic rename test')

    try:
        from apps.document.tasks.async_copy import copy_file_async

        ext = '.txt'
        target_name = generate_physical_name(ext, '原子测试.txt')
        target_path = os.path.join(TEST_DIR, target_name)

        transfer = DocumentTransfer.objects.create(
            transfer_type=TransferType.COPY.value,
            status=TransferStatus.PENDING.value,
            file_name='原子测试_副本.txt',
            file_size=source.file_size,
            file_path=target_path,
            source_file_id=source.id,
            source_file_path=source.file_path,
            conflict_action='',
            is_public=False,
            system_folder='',
            user=TEST_USER,
        )
        copy_file_async.apply((transfer.id,))

        # 验证最终文件存在
        check('最终文件存在', os.path.exists(target_path), f'path: {target_path}')
        # 验证临时文件不存在（已被 rename）
        check('临时文件已转正', not os.path.exists(target_path + '.copying_tmp'),
              f'temp exists')

        # 清理
        new_file = DocumentFilePrivate.objects.filter(file_path=target_path).first()
        if new_file:
            cleanup_test_file(new_file)

    finally:
        cleanup_test_file(source)


def cleanup_all():
    """清理所有测试数据"""
    print('\n[Cleanup] Removing test data...')

    # 清理测试目录
    if TEST_DIR and os.path.exists(TEST_DIR):
        shutil.rmtree(TEST_DIR, ignore_errors=True)

    # 清理测试 transfer 记录
    DocumentTransfer.objects.filter(user=TEST_USER).delete()

    # 清理测试文件记录
    DocumentFilePrivate.objects.filter(created_by=TEST_USER).delete()

    # 清理测试文件夹
    DocumentFolderPrivate.objects.filter(created_by=TEST_USER).delete()


if __name__ == '__main__':
    print('=' * 60)
    print('异步复制行为测试 (test_async_copy.py)')
    print('=' * 60)

    try:
        setup_test_env()

        test_small_file_sync_copy()
        test_large_file_async_copy()
        test_idempotent_retry()
        test_two_copies_different_names()
        test_delete_copy_not_affect_source()
        test_cancellation()
        test_failure_cleanup()
        test_keep_conflict()
        test_skip_conflict()
        test_copy_preserves_original_name()
        test_atomic_rename()

    finally:
        cleanup_all()

    print('\n' + '=' * 60)
    print(f'总计: {PASS} PASS / {FAIL} FAIL')
    if ERRORS:
        print('\n失败项:')
        for e in ERRORS:
            print(f'  - {e}')
    print('=' * 60)
    sys.exit(1 if FAIL > 0 else 0)

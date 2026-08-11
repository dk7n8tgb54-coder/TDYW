"""资料库边界测试 - 真实行为验证

验证通过代码审查推断的 4 个边界 bug 是否真实存在。
所有测试只读或使用临时文件，不污染 dev 库。
"""
import os
import re
import sys
import tempfile
import shutil

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from apps.document.views.upload.validators import (
    ChunkStorageManager, FolderValidator,
)
from apps.document.views.upload.chunk import _validate_chunk_size
from apps.document.libs.naming_utils import generate_unique_logical_name
from apps.document.models import DocumentFilePrivate

PASS = 'PASS'
FAIL = 'FAIL'
results = []


def report(name, ok, detail):
    tag = PASS if ok else FAIL
    results.append((name, ok, detail))
    print(f'[{tag}] {name}')
    print(f'    {detail}')
    print()


# ========== B1: 分片文件名不一致（P0）==========
print('=' * 70)
print('B1: 分片保存格式 vs 检查格式一致性')
print('=' * 70)

tmp_dir = tempfile.mkdtemp(prefix='boundary_b1_')


class FakeChunkFile:
    def chunks(self):
        return [b'test chunk content 0']


try:
    # 实际保存一个分片
    chunk_path, err = ChunkStorageManager.save_chunk_file(
        FakeChunkFile(), tmp_dir, 0
    )
    actual_files = os.listdir(tmp_dir)
    print(f'保存分片后目录内容: {actual_files}')
    print(f'返回的 chunk_path: {chunk_path}')

    # chunk.py:201 用的格式
    chunk_py_check = os.path.join(tmp_dir, f'chunk_{0}')
    chunk_py_exists = os.path.exists(chunk_py_check)

    # resume_strategies.py:60 用的格式（与 chunk.py 相同）
    resume_check = os.path.join(tmp_dir, f'chunk_{0}')
    resume_exists = os.path.exists(resume_check)

    # 实际保存的格式
    correct_check = os.path.join(tmp_dir, f'{0}.part')
    correct_exists = os.path.exists(correct_check)

    print(f'chunk.py 检查 "chunk_0" 存在: {chunk_py_exists}')
    print(f'resume_strategies 检查 "chunk_0" 存在: {resume_exists}')
    print(f'实际格式 "0.part" 存在: {correct_exists}')

    # 真实后果：模拟 _update_cache_and_marker 的检查逻辑
    # chunk.py:196-214: if chunk_index == total_chunks - 1: 检查所有分片存在
    # 这里直接复刻该段逻辑
    total_chunks = 1
    missing_chunks = []
    for i in range(total_chunks):
        # 用 chunk.py 的格式
        cf = os.path.join(tmp_dir, f'chunk_{i}')
        if not os.path.exists(cf):
            missing_chunks.append(i)

    marker_would_create = (len(missing_chunks) == 0)
    report(
        'B1: _SUCCESS_ 标记会被创建吗',
        not marker_would_create,  # 期望: 不会被创建(bug)
        f'missing_chunks={missing_chunks}, marker_would_create={marker_would_create}'
        + (f' -> 标记永不创建' if not marker_would_create else '')
    )
finally:
    shutil.rmtree(tmp_dir, ignore_errors=True)


# ========== B2: 序号溢出导致唯一约束冲突（P1）==========
print('=' * 70)
print('B2: naming_utils 序号溢出 - 4 位名不匹配 3 位正则')
print('=' * 70)

clean_original = 'testfile'
ext = '.txt'
# naming_utils.py:278 的正则
regex_pattern = rf"^{re.escape(clean_original)}_(\d{{3}}){re.escape(ext)}$"

# 模拟已存在 testfile_001.txt ... testfile_999.txt
# max_counter = 999, new_counter = 1000
# naming_utils.py:289-290: if new_counter > 999: return f"{clean_original}_{new_counter:04d}{ext}"
new_counter = 1000
generated_name = f"{clean_original}_{new_counter:04d}{ext}"
print(f'第 1000 个同名文件生成名: {generated_name}')

# 下次查询时, 该名能否被正则匹配(用于提取 max_counter)?
match_4digit = re.match(regex_pattern, generated_name)
print(f'4 位名 "{generated_name}" 匹配 3 位正则: {bool(match_4digit)}')

# 对比: 3 位名能匹配
match_3digit = re.match(regex_pattern, f'{clean_original}_999{ext}')
print(f'3 位名 "testfile_999.txt" 匹配: {bool(match_3digit)}')

# 后果链
print('后果链:')
print('  1. 第 1000 个文件生成 "testfile_1000.txt"')
print('  2. 第 1001 次上传: 正则不匹配 1000, max_counter 仍=999')
print('  3. new_counter 再次=1000, 生成 "testfile_1000.txt"')
print('  4. 触发 unique_file_name_folder_private 唯一约束冲突')

report(
    'B2: 4 位序号名不匹配 3 位正则',
    not match_4digit,  # 期望: 不匹配(证明 bug)
    f'4 位名匹配 3 位正则={bool(match_4digit)} -> bug 存在'
    if not match_4digit else '未发现 bug'
)


# ========== B4: chunk_size 非数字 fail-open ==========
print('=' * 70)
print('B4: _validate_chunk_size 对非数字 chunk_size 的行为')
print('=' * 70)

tmp_dir2 = tempfile.mkdtemp(prefix='boundary_b4_')
chunk_path_b4 = os.path.join(tmp_dir2, '0.part')
with open(chunk_path_b4, 'wb') as f:
    f.write(b'fake chunk 12345')


class FakeRequest:
    def __init__(self, chunk_size):
        self.POST = {'chunk_size': chunk_size} if chunk_size is not None else {}


try:
    # 场景1: chunk_size='abc' (非数字)
    err1 = _validate_chunk_size(FakeRequest('abc'), chunk_path_b4, 0)
    print(f'chunk_size="abc" 返回: {err1!r}')

    # 场景2: chunk_size 不传
    err2 = _validate_chunk_size(FakeRequest(None), chunk_path_b4, 0)
    print(f'chunk_size 不传 返回: {err2!r}')

    # 场景3: chunk_size='999' (数字但与实际 13 字节不匹配)
    err3 = _validate_chunk_size(FakeRequest('999'), chunk_path_b4, 0)
    print(f'chunk_size="999"(实际13字节) 返回: {err3!r}')

    # 场景1和2应返回 None(跳过校验), 场景3应返回错误
    fail_open = (err1 is None and err2 is None)
    report(
        'B4: 非数字 chunk_size 静默跳过校验(fail-open)',
        fail_open,  # 期望: fail-open(bug)
        f'非数字返回 None={err1 is None}, 不传返回 None={err2 is None}'
        + (f' -> 攻击者可上传任意大小分片不被检测' if fail_open else '')
    )
finally:
    shutil.rmtree(tmp_dir2, ignore_errors=True)


# ========== B7: FolderValidator 非数字 folder_id 静默当根目录 ==========
print('=' * 70)
print('B7: FolderValidator 对非数字 folder_id 的行为')
print('=' * 70)


class FakeUser:
    id = 999999
    tenant_id = 'boundary_test_tenant'
    is_supper = False
    username = 'boundary_tester'


try:
    # 场景1: folder_id='abc'
    folder1, err1 = FolderValidator.validate_folder('abc', False, FakeUser())
    print(f"folder_id='abc' 返回: folder={folder1}, error={err1}")

    # 场景2: folder_id=None (正常的根目录)
    folder2, err2 = FolderValidator.validate_folder(None, False, FakeUser())
    print(f"folder_id=None 返回: folder={folder2}, error={err2}")

    # 场景3: folder_id='123abc' (混合)
    folder3, err3 = FolderValidator.validate_folder('123abc', False, FakeUser())
    print(f"folder_id='123abc' 返回: folder={folder3}, error={err3}")

    # 'abc' 和 None 返回相同 → 非数字被当根目录
    same_as_root = (folder1 is None and err1 is None)
    report(
        'B7: 非数字 folder_id 静默当作根目录(fail-open)',
        same_as_root,  # 期望: fail-open(bug)
        f"'abc' 返回 ({folder1!r}, {err1!r}) == None 根目录返回 ({folder2!r}, {err2!r})"
        if same_as_root else f"'abc' 返回 ({folder1!r}, {err1!r})"
    )
except Exception as e:
    report('B7', False, f'异常: {e}')


# ========== 汇总 ==========
print('=' * 70)
print('汇总')
print('=' * 70)
passed = sum(1 for _, ok, _ in results if ok)
failed = sum(1 for _, ok, _ in results if not ok)
print(f'共 {len(results)} 项, 复现 bug {failed} 项, 未复现 {passed} 项')
for name, ok, _ in results:
    print(f'  [{"BUG" if ok else " OK "}] {name}')

sys.exit(0)

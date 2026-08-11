"""资料库边界测试 第二波 - 纯函数边界

覆盖: 文件大小/文件名/党建参数/状态转换矩阵的边界
不碰数据库, 全部纯函数调用。
"""
import os
import sys

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from apps.document.constants import (
    DEFAULT_MAX_FILE_SIZE, DEFAULT_MAX_FOLDER_DEPTH,
    TransferStatus, is_valid_status_transition, ALLOWED_STATUS_TRANSITIONS,
)
from apps.document.views.upload.validators import ChunkUploadValidator
from apps.document.views.base import validate_file_name
from apps.document.libs.naming_utils import clean_illegal_chars, get_file_ext
from apps.document.services.system_folder_service import validate_system_folder_context

results = []


def report(name, ok, detail):
    results.append((name, ok, detail))
    print(f'[{"BUG" if ok else " OK "}] {name}')
    print(f'    {detail}')
    print()


# ========== C1: 文件大小边界 ==========
print('=' * 70)
print('C1: 文件大小边界 (ChunkUploadValidator.validate_file)')
print('=' * 70)
max_size = DEFAULT_MAX_FILE_SIZE  # 10GB
print(f'DEFAULT_MAX_FILE_SIZE = {max_size} (10GB)')

cases = [
    (-1, '负数'),
    (0, '0 字节'),
    (1, '1 字节'),
    (5 * 1024 * 1024 - 1, '5MB-1 (分片阈值前)'),
    (5 * 1024 * 1024, '5MB (分片阈值)'),
    (5 * 1024 * 1024 + 1, '5MB+1 (分片阈值后)'),
    (max_size, 'max (10GB)'),
    (max_size + 1, 'max+1 (超限)'),
]
for size, label in cases:
    ok, err = ChunkUploadValidator.validate_file('test.txt', size, max_size)
    print(f'  size={size:>15} ({label}): valid={ok}, err={err!r}')
    if size == 0 and not ok:
        report('C1-a: 0 字节文件被拒绝(上传层)', True, f'0字节返回 {err!r}')
    if size == max_size + 1 and not ok:
        report('C1-b: 超过 max 被拒绝', True, f'max+1 返回 {err!r}')
    if size == 1 and not ok:
        report('C1-c: 1 字节被错误拒绝', False, f'1字节返回 {err!r}')


# ========== C2: 文件名边界 ==========
print('=' * 70)
print('C2: 文件名边界 (validate_file_name + clean_illegal_chars)')
print('=' * 70)

name_cases = [
    ('', '空文件名'),
    (None, 'None'),
    ('a', '单字符'),
    ('a' * 300, '超长名(300字符)'),
    ('中文文件名.txt', '中文'),
    ('file with space.txt', '含空格'),
    ('file.name.with.dots.txt', '多点号'),
    ('file..double.txt', '连续点号'),
    ('archive.tar.gz', '重复后缀.tar.gz'),
    ('file<bad>.txt', '含非法字符<>'),
    ('file/path.txt', '路径穿越尝试'),
    ('../../../etc/passwd', '路径穿越'),
    ('file\x00null.txt', '含NUL'),
    ('file\nnewline.txt', '含换行'),
    ('.hidden', '纯隐藏文件'),
    ('..', '上级目录'),
    ('.', '当前目录'),
    ('CON', 'Windows保留名'),
    ('a' * 255 + '.txt', '255字符名'),
]
for name, label in name_cases:
    try:
        valid = validate_file_name(name)
        cleaned = clean_illegal_chars(name) if name else 'unnamed'
        print(f'  {label:25} valid={valid!r:6} cleaned={cleaned!r}')
    except Exception as e:
        print(f'  {label:25} 异常: {type(e).__name__}: {e}')
        report(f'C2: {label} 抛异常', True, f'{type(e).__name__}: {e}')

# 关键检查
if not validate_file_name(''):
    report('C2-a: 空文件名被拒绝', True, '')
# 路径穿越是否被拦截
path_traversal_valid = validate_file_name('../../../etc/passwd')
report('C2-b: 路径穿越 ../../../etc/passwd', path_traversal_valid,
       f'validate_file_name 返回 {path_traversal_valid!r}'
       + (' -> 未拦截!' if path_traversal_valid else ' -> 已拦截'))


# ========== C3: get_file_ext 多后缀 ==========
print('=' * 70)
print('C3: get_file_ext 扩展名提取')
print('=' * 70)
ext_cases = [
    'archive.tar.gz',
    'archive.tar.bz2',
    'file.md5',
    'file.sha256',
    'noext',
    '.dotfile',
    'a.b.c.d.e',
    '',
    'file.TXT',  # 大写
]
for name in ext_cases:
    base, ext = get_file_ext(name)
    print(f'  {name:25} -> base={base!r:20} ext={ext!r}')
# 验证 .tar.gz 被正确识别
base, ext = get_file_ext('archive.tar.gz')
report('C3: .tar.gz 多后缀识别', ext == '.tar.gz',
       f'ext={ext!r}' + (' -> 正确' if ext == '.tar.gz' else ' -> 错误'))


# ========== C4: 党建参数边界 ==========
print('=' * 70)
print('C4: validate_system_folder_context 党建参数边界')
print('=' * 70)
sf_cases = [
    (None, False, 'None + 私有'),
    ('', False, '空串 + 私有'),
    ('', True, '空串 + 公共(正常)'),
    ('party_building_documents', True, '党建 + 公共(正确)'),
    ('party_building_documents', False, '党建 + 私有(非法)'),
    ('party_building_documents', None, '党建 + None is_public'),
    ('unknown_code', True, '未知编码 + 公共'),
    ('unknown_code', False, '未知编码 + 私有'),
    ('PARTY_BUILDING_DOCUMENTS', True, '大写编码(大小写)'),
    ('  party_building_documents  ', True, '含空格'),
]
for sf, is_pub, label in sf_cases:
    try:
        ok, err = validate_system_folder_context(sf, is_pub)
        print(f'  {label:35} ok={ok!r:6} err={err!r}')
    except Exception as e:
        print(f'  {label:35} 异常: {type(e).__name__}: {e}')
        report(f'C4: {label} 抛异常', True, f'{type(e).__name__}: {e}')

# 关键: 党建+私有应被拒绝
ok, err = validate_system_folder_context('party_building_documents', False)
report('C4-a: 党建+私有被拒绝', not ok, f'ok={ok}, err={err!r}')
# 未知编码
ok, err = validate_system_folder_context('unknown_code', True)
report('C4-b: 未知编码被拒绝', not ok, f'ok={ok}, err={err!r}')


# ========== C5: 状态转换矩阵边界 ==========
print('=' * 70)
print('C5: 状态转换矩阵边界 (is_valid_status_transition)')
print('=' * 70)

# 终态不应允许转出
terminal_cases = [
    (TransferStatus.COMPLETED, TransferStatus.UPLOADING, 'COMPLETED->UPLOADING'),
    (TransferStatus.COMPLETED, TransferStatus.FAILED, 'COMPLETED->FAILED'),
    (TransferStatus.COMPLETED, TransferStatus.CANCELED, 'COMPLETED->CANCELED'),
    (TransferStatus.CANCELED, TransferStatus.UPLOADING, 'CANCELED->UPLOADING'),
    (TransferStatus.CANCELED, TransferStatus.COMPLETED, 'CANCELED->COMPLETED'),
]
for src, dst, label in terminal_cases:
    valid = is_valid_status_transition(src, dst)
    print(f'  {label:30} valid={valid}')
    if valid:
        report(f'C5: {label} 终态可转出(违反终态语义)', True, '')

# 关键转换
key_cases = [
    (TransferStatus.UPLOADING, TransferStatus.COMPLETED, 'UPLOADING->COMPLETED', True),
    (TransferStatus.UPLOADING, TransferStatus.MERGING, 'UPLOADING->MERGING', True),
    (TransferStatus.PAUSED, TransferStatus.UPLOADING, 'PAUSED->UPLOADING(恢复)', True),
    (TransferStatus.MERGING, TransferStatus.CANCELED, 'MERGING->CANCELED(合并中取消)', True),
    (TransferStatus.FAILED, TransferStatus.UPLOADING, 'FAILED->UPLOADING(重试)', True),
    (TransferStatus.PAUSED, TransferStatus.MERGING, 'PAUSED->MERGING(直接合并?)', False),
]
for src, dst, label, expected in key_cases:
    valid = is_valid_status_transition(src, dst)
    print(f'  {label:35} valid={valid} (期望{expected})')
    if valid != expected:
        report(f'C5: {label} 行为与期望不符', True, f'实际={valid}, 期望={expected}')

# 暂停后立即恢复 / 恢复后立即取消 的转换链
chain1 = (is_valid_status_transition(TransferStatus.UPLOADING, TransferStatus.PAUSED)
          and is_valid_status_transition(TransferStatus.PAUSED, TransferStatus.UPLOADING))
print(f'  暂停后立即恢复链: {chain1}')
chain2 = (is_valid_status_transition(TransferStatus.PAUSED, TransferStatus.UPLOADING)
          and is_valid_status_transition(TransferStatus.UPLOADING, TransferStatus.CANCELED))
print(f'  恢复后立即取消链: {chain2}')


# ========== C6: 目录深度限制不一致 ==========
print('=' * 70)
print('C6: 目录深度限制不一致')
print('=' * 70)
print(f'  constants.DEFAULT_MAX_FOLDER_DEPTH = {DEFAULT_MAX_FOLDER_DEPTH}')
print(f'  folder/views.py:448 硬编码 MAX_FOLDER_DEPTH = 50')
print(f'  models.py FolderPathMixin 用 DEFAULT_MAX_FOLDER_DEPTH(100)')
report('C6: 深度限制三值不一致(50 vs 100)',
       DEFAULT_MAX_FOLDER_DEPTH != 50,
       f'constants={DEFAULT_MAX_FOLDER_DEPTH}, views硬编码=50 -> get_full_path允许100层但删除只到50层')


# ========== 汇总 ==========
print('=' * 70)
print('汇总')
print('=' * 70)
bug_count = sum(1 for _, ok, _ in results if ok)
ok_count = sum(1 for _, ok, _ in results if not ok)
print(f'共 {len(results)} 项边界检查, 发现问题 {bug_count} 项, 正常 {ok_count} 项')
for name, ok, _ in results:
    print(f'  [{"BUG" if ok else " OK "}] {name}')
sys.exit(0)

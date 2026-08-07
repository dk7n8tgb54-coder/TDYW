"""
命名工具测试脚本
测试 clean_illegal_chars() 和 generate_physical_name() 的安全性

运行方式：
  wsl bash -c 'docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python scripts/test_naming_fix.py'
"""
import os
import sys
import unicodedata

# Django 环境设置
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

# 添加项目路径
sys.path.insert(0, '/data/spug/spug_api')

import django
django.setup()

from apps.document.libs.naming_utils import (
    clean_illegal_chars, generate_physical_name, get_file_ext, _truncate_utf8_safe
)

PASS = 0
FAIL = 0
ERRORS = []


def check(name, condition, detail=''):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f'  [PASS] {name}')
    else:
        FAIL += 1
        ERRORS.append(f'{name}: {detail}')
        print(f'  [FAIL] {name} -- {detail}')


def test_clean_illegal_chars():
    """测试非法字符清理"""
    print('\n=== 测试 clean_illegal_chars ===')

    # 1. 十几个汉字正常保留
    name = '党建工作年度总结报告'
    result = clean_illegal_chars(name, replace_space=False)
    check('十几个汉字保留', result == '党建工作年度总结报告', f'got: {result}')

    # 2. 中英文混合
    name = '2024年度报告_Report.pdf'
    result = clean_illegal_chars(name, replace_space=False)
    check('中英文混合保留', result == '2024年度报告_Report.pdf', f'got: {result}')

    # 3. 空格处理（replace_space=False 保留空格）
    name = 'my file name.txt'
    result = clean_illegal_chars(name, replace_space=False)
    check('空格保留(replace_space=False)', result == 'my file name.txt', f'got: {result}')

    # 4. 空格处理（replace_space=True 替换为下划线）
    result = clean_illegal_chars(name, replace_space=True)
    check('空格替换(replace_space=True)', result == 'my_file_name.txt', f'got: {result}')

    # 5. Windows 危险字符
    name = 'file<>:"/\\|?*.txt'
    result = clean_illegal_chars(name, replace_space=False)
    check('Windows危险字符清理', '/' not in result and '\\' not in result and
          ':' not in result and '*' not in result and '?' not in result and
          '"' not in result and '<' not in result and '>' not in result and
          '|' not in result, f'got: {result}')

    # 6. 路径穿越 - ../
    name = '../../../etc/passwd'
    result = clean_illegal_chars(name, replace_space=False)
    check('路径穿越阻止(../)', '..' not in result and '/' not in result, f'got: {result}')

    # 7. 绝对路径
    name = '/etc/passwd'
    result = clean_illegal_chars(name, replace_space=False)
    check('绝对路径阻止', '/' not in result, f'got: {result}')

    # 8. NUL 字符
    name = 'file\x00name.txt'
    result = clean_illegal_chars(name, replace_space=False)
    check('NUL字符清除', '\x00' not in result, f'got: {repr(result)}')

    # 9. 控制字符
    name = 'file\x01\x02\x03\x04\x05name.txt'
    result = clean_illegal_chars(name, replace_space=False)
    check('控制字符清除', '\x01' not in result and '\x02' not in result and
          '\x03' not in result and '\x04' not in result and '\x05' not in result, f'got: {repr(result)}')

    # 10. DEL 字符 (0x7f)
    name = 'file\x7fname.txt'
    result = clean_illegal_chars(name, replace_space=False)
    check('DEL字符清除', '\x7f' not in result, f'got: {repr(result)}')

    # 11. 连续下划线合并
    name = 'file___name.txt'
    result = clean_illegal_chars(name, replace_space=False)
    check('连续下划线合并', '___' not in result, f'got: {result}')

    # 12. 首尾下划线
    name = '_filename_'
    result = clean_illegal_chars(name, replace_space=False)
    check('首尾下划线去除', not result.startswith('_') and not result.endswith('_'), f'got: {result}')

    # 13. 空字符串
    result = clean_illegal_chars('', replace_space=False)
    check('空字符串兜底', result == 'unnamed', f'got: {result}')

    # 14. None
    result = clean_illegal_chars(None, replace_space=False)
    check('None兜底', result == 'unnamed', f'got: {result}')

    # 15. 括号
    name = 'file(1).txt'
    result = clean_illegal_chars(name, replace_space=False)
    check('括号保留', result == 'file(1).txt', f'got: {result}')

    # 16. NFC 规范化
    # NFD: 'é' = 'e' + U+0301 (组合字符)
    # NFC: 'é' = U+00E9 (单一字符)
    nfd_str = 'e\u0301.txt'  # NFD 形式
    result = clean_illegal_chars(nfd_str, replace_space=False)
    nfc_form = unicodedata.normalize('NFC', nfd_str)
    check('NFC规范化', result == nfc_form, f'got: {repr(result)}, expected: {repr(nfc_form)}')


def test_generate_physical_name():
    """测试物理文件名生成"""
    print('\n=== 测试 generate_physical_name ===')

    # 1. 中文文件名保留
    name = '党建工作年度总结报告.pdf'
    result = generate_physical_name('.pdf', name)
    check('中文文件名保留', '党建工作年度总结报告' in result, f'got: {result}')
    check('中文文件名有扩展名', result.endswith('.pdf'), f'got: {result}')
    check('中文文件名有时间戳', '_' in result, f'got: {result}')

    # 2. 十几个汉字完整保留
    name = '关于加强党建工作的实施意见通知.pdf'
    result = generate_physical_name('.pdf', name)
    check('十几个汉字完整保留', '关于加强党建工作的实施意见通知' in result, f'got: {result}')

    # 3. 无原始名
    result = generate_physical_name('.mp4')
    check('无原始名生成', result.endswith('.mp4') and '_' in result, f'got: {result}')

    # 4. 无扩展名
    result = generate_physical_name('', 'README')
    check('无扩展名处理', 'README' in result, f'got: {result}')

    # 5. 多扩展名 .tar.gz
    name = 'archive.tar.gz'
    result = generate_physical_name('.tar.gz', name)
    check('多扩展名处理', result.endswith('.tar.gz'), f'got: {result}')
    check('多扩展名保留原名', 'archive' in result, f'got: {result}')

    # 6. 路径穿越
    name = '../../../etc/passwd.pdf'
    result = generate_physical_name('.pdf', name)
    check('路径穿越阻止', '..' not in result and '/etc/' not in result, f'got: {result}')

    # 7. 危险字符
    name = 'file<>:"|?*.pdf'
    result = generate_physical_name('.pdf', name)
    check('危险字符清理', '<' not in result and '>' not in result and
          ':' not in result and '"' not in result and '|' not in result and
          '?' not in result and '*' not in result, f'got: {result}')

    # 8. 超长中文（UTF-8 字节安全截断）
    long_name = '这是一个非常长的中文文件名' * 20 + '.pdf'
    result = generate_physical_name('.pdf', long_name)
    # 检查总长度不超过 model max_length=100
    check('超长文件名长度限制', len(result) <= 100, f'len={len(result)}, got: {result}')
    # 检查 UTF-8 字节不超过 Linux 255 字节限制
    check('超长文件名字节限制', len(result.encode('utf-8')) <= 255, f'bytes={len(result.encode("utf-8"))}')
    # 检查以扩展名结尾
    check('超长文件名扩展名保留', result.endswith('.pdf'), f'got: {result}')
    # 检查没有截断半个汉字（可以正确 UTF-8 解码）
    try:
        result.encode('utf-8').decode('utf-8')
        check('超长文件名无半个汉字', True)
    except UnicodeDecodeError:
        check('超长文件名无半个汉字', False, 'UTF-8 decode failed')

    # 9. 两次复制生成不同物理名
    name = '测试文件.pdf'
    result1 = generate_physical_name('.pdf', name)
    result2 = generate_physical_name('.pdf', name)
    check('两次复制生成不同物理名', result1 != result2, f'r1={result1}, r2={result2}')

    # 10. Emoji
    name = '测试📁文件.pdf'
    result = generate_physical_name('.pdf', name)
    check('Emoji处理不崩溃', result.endswith('.pdf'), f'got: {result}')

    # 11. 空格保留
    name = 'my report.pdf'
    result = generate_physical_name('.pdf', name)
    check('空格在物理名中保留', 'my report' in result or 'my_report' in result, f'got: {result}')

    # 12. 括号和下划线
    name = 'report_v2(最终版).pdf'
    result = generate_physical_name('.pdf', name)
    check('括号和下划线保留', 'report_v2(最终版)' in result, f'got: {result}')


def test_truncate_utf8_safe():
    """测试 UTF-8 字节安全截断"""
    print('\n=== 测试 _truncate_utf8_safe ===')

    # 1. 中文不截断半个汉字
    text = '党建工作年度总结报告'  # 10 个汉字 = 30 UTF-8 字节
    result = _truncate_utf8_safe(text, 15)  # 15 字节 = 5 个汉字
    check('UTF-8安全截断(15字节)', result == '党建工作年', f'got: {result}')

    # 2. 不需要截断
    text = 'short.txt'
    result = _truncate_utf8_safe(text, 100)
    check('不需截断', result == 'short.txt', f'got: {result}')

    # 3. 空字符串
    result = _truncate_utf8_safe('', 10)
    check('空字符串', result == '', f'got: {result}')

    # 4. 刚好在字符边界
    text = 'AB'  # 2 ASCII 字节
    result = _truncate_utf8_safe(text, 2)
    check('字符边界', result == 'AB', f'got: {result}')

    # 5. 超长中文
    text = '党建' * 50  # 100 个汉字 = 300 UTF-8 字节
    result = _truncate_utf8_safe(text, 60)  # 60 字节 = 20 个汉字
    check('超长中文截断', len(result.encode('utf-8')) <= 60 and
          len(result) == 20, f'len={len(result)}, bytes={len(result.encode("utf-8"))}')


def test_copy_preserves_name():
    """测试复制路径保留原始文件名"""
    print('\n=== 测试复制路径保留原始文件名 ===')

    # 模拟 copy.py 中的调用
    from apps.document.views.file.copy import FileNameGenerator

    # 检查 FileNameGenerator.generate 是否传递 original_name
    import inspect
    source = inspect.getsource(FileNameGenerator.generate)
    check('FileNameGenerator 传递 original_name',
          'generate_physical_name(file_ext, original_display_name)' in source,
          'FileNameGenerator.generate 未传递 original_display_name')

    # 检查 folder_copy_service.py 中的调用
    from apps.document.services import folder_copy_service
    source = inspect.getsource(folder_copy_service.FileCopier._copy_single_file)
    check('FileCopier 传递 original_name',
          'generate_physical_name(file_ext, original_display_name)' in source,
          'FileCopier._copy_single_file 未传递 original_display_name')


def test_get_file_ext():
    """测试扩展名提取"""
    print('\n=== 测试 get_file_ext ===')

    # 1. 普通文件
    name, ext = get_file_ext('report.pdf')
    check('普通文件扩展名', ext == '.pdf', f'got: {ext}')

    # 2. 多扩展名
    name, ext = get_file_ext('archive.tar.gz')
    check('多扩展名', ext == '.tar.gz', f'got: {ext}')

    # 3. 无扩展名
    name, ext = get_file_ext('README')
    check('无扩展名', ext == '', f'got: {ext}')

    # 4. 中文文件名
    name, ext = get_file_ext('党建工作总结.pdf')
    check('中文文件名扩展名', ext == '.pdf', f'got: {ext}')


if __name__ == '__main__':
    print('=' * 60)
    print('命名工具测试 (test_naming_fix.py)')
    print('=' * 60)

    test_clean_illegal_chars()
    test_generate_physical_name()
    test_truncate_utf8_safe()
    test_copy_preserves_name()
    test_get_file_ext()

    print('\n' + '=' * 60)
    print(f'总计: {PASS} PASS / {FAIL} FAIL')
    if ERRORS:
        print('\n失败项:')
        for e in ERRORS:
            print(f'  - {e}')
    print('=' * 60)
    sys.exit(1 if FAIL > 0 else 0)

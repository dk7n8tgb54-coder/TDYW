import sys
import os
sys.path.insert(0, '.')
os.chdir('..')

from apps.document.constants import TransferStatus, DEFAULT_MAX_FOLDER_DEPTH, DEFAULT_MAX_FILE_SIZE, DEFAULT_CHUNK_CLEANUP_AGE, DEFAULT_MERGE_LOCK_TIMEOUT, DEFAULT_MERGE_STATUS_TIMEOUT

print('=== 常量导入测试 ===')
print('OK - 所有常量导入成功')

print('\n=== TransferStatus枚举值测试 ===')
for status in TransferStatus:
    print(f'{status.name}: value="{status.value}", lower="{status.value.lower()}"')

print('\n=== 配置常量值测试 ===')
print(f'DEFAULT_MAX_FOLDER_DEPTH = {DEFAULT_MAX_FOLDER_DEPTH}')
print(f'DEFAULT_MAX_FILE_SIZE = {DEFAULT_MAX_FILE_SIZE}')
print(f'DEFAULT_CHUNK_CLEANUP_AGE = {DEFAULT_CHUNK_CLEANUP_AGE}')
print(f'DEFAULT_MERGE_LOCK_TIMEOUT = {DEFAULT_MERGE_LOCK_TIMEOUT}')
print(f'DEFAULT_MERGE_STATUS_TIMEOUT = {DEFAULT_MERGE_STATUS_TIMEOUT}')

print('\n=== 验证值 ===')
assert DEFAULT_MAX_FOLDER_DEPTH == 100
assert DEFAULT_MAX_FILE_SIZE == 10 * 1024 * 1024 * 1024
assert DEFAULT_CHUNK_CLEANUP_AGE == 24 * 3600
assert DEFAULT_MERGE_LOCK_TIMEOUT == 600
assert DEFAULT_MERGE_STATUS_TIMEOUT == 300

print('OK - 所有常量值正确')

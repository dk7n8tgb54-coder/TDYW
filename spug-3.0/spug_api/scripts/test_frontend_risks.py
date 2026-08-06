# -*- coding: utf-8 -*-
"""前端静态分析 - 验证 3 个前端风险点"""
import os

base = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                    'spug_web', 'src', 'pages', 'document', 'stores', 'upload')

# ---- P1: 合并重试永久停在 merging ----
print('=' * 60)
print('[P1] 合并重试永久停在 merging')
print('=' * 60)

# 1. chunkUpload.js 是否有 startMergePolling
with open(os.path.join(base, 'core', 'chunkUpload.js'), 'r', encoding='utf-8') as f:
    chunk_src = f.read()

has_start_merge_polling = 'startMergePolling' in chunk_src
has_async_def = 'async startMergePolling' in chunk_src
has_poll = 'pollMergeStatus' in chunk_src

print(f'  startMergePolling 出现在代码中: {has_start_merge_polling}')
print(f'  作为方法定义 (async startMergePolling): {has_async_def}')
print(f'  pollMergeStatus 方法存在: {has_poll}')

if has_start_merge_polling and not has_async_def:
    print('  -> startMergePolling 被调用但未作为方法定义')
    if has_poll:
        print('  -> 实际方法是 pollMergeStatus，方法名不匹配')
    print('  [P1] 风险确认！合并重试调用不存在的方法，无轮询，永久停在 merging')
else:
    print('  [P1] 风险未复现')

# 2. ItemOperationController 调用 startMergePolling
with open(os.path.join(base, 'core', 'controls', 'ItemOperationController.js'), 'r', encoding='utf-8') as f:
    ioc_src = f.read()

call_count = ioc_src.count('startMergePolling')
print(f'\n  ItemOperationController.js 中 startMergePolling 出现 {call_count} 次')

if call_count > 0:
    # 找到调用行
    for i, line in enumerate(ioc_src.split('\n'), 1):
        if 'startMergePolling' in line:
            print(f'    line {i}: {line.strip()}')

# 3. StateChangeHandler 对 RETRY_MERGE 的处理
with open(os.path.join(base, 'core', 'lifecycle', 'StateChangeHandler.js'), 'r', encoding='utf-8') as f:
    sch_src = f.read()

has_retry_merge = 'RETRY_MERGE' in sch_src
print(f'\n  StateChangeHandler.js 中有 RETRY_MERGE: {has_retry_merge}')

if has_retry_merge:
    idx = sch_src.find('RETRY_MERGE')
    after = sch_src[idx:idx+500]
    lines_after = after.split('\n')[:10]
    print('  RETRY_MERGE 后续代码:')
    for line in lines_after:
        print(f'    {line}')

    has_early_return = 'return' in after[:150]
    has_merge_call = 'mergeChunks' in after[:500]
    print(f'\n  RETRY_MERGE 后直接 return: {has_early_return}')
    print(f'  RETRY_MERGE 后调 mergeChunks: {has_merge_call}')
    if has_early_return and not has_merge_call:
        print('  [P1] 风险确认！RETRY_MERGE 跳过合并和轮询，永久停在 merging')

# ---- P2: 轮询把确定失败当网络抖动 ----
print('\n' + '=' * 60)
print('[P2] 轮询把确定失败当网络抖动')
print('=' * 60)

# 检查 pollMergeStatus 中 failed/timeout/not_found 抛 Error
failed_check = "status.status === 'failed'" in chunk_src
timeout_check = "status.status === 'timeout'" in chunk_src or "'timeout'" in chunk_src
not_found_check = "status.status === 'not_found'" in chunk_src or "'not_found'" in chunk_src

print(f'  检查 failed 状态: {failed_check}')
print(f'  检查 timeout 状态: {timeout_check}')
print(f'  检查 not_found 状态: {not_found_check}')

# 检查这些检查后是否抛 Error
if failed_check:
    idx = chunk_src.find("status.status === 'failed'")
    after = chunk_src[idx:idx+300]
    has_throw = 'throw' in after[:200]
    print(f'  failed 状态后抛 Error: {has_throw}')

# 检查 catch 块是否用 consecutiveErrors 重试
has_catch_retry = 'consecutiveErrors' in chunk_src and 'MAX_CONSECUTIVE_ERRORS' in chunk_src
print(f'  catch 块用 consecutiveErrors 重试: {has_catch_retry}')

if has_throw and has_catch_retry:
    print('  [P2] 风险确认！failed/timeout/not_found 抛 Error 后被 catch 捕获')
    print('  [P2] catch 用 consecutiveErrors 重试，真实合并错误被掩盖')
    print('  [P2] 用户需等待约 31 秒，最终只得到"连续查询失败"')

print('\n' + '=' * 60)
print('前端静态分析完成')
print('=' * 60)

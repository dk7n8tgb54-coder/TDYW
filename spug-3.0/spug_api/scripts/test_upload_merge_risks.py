# -*- coding: utf-8 -*-
"""
上传合并风险验证测试 - 验证 9 个风险点真伪

运行方式：
  docker exec -e PYTHONIOENCODING=utf-8 -e PYTHONPATH=/data/spug/spug_api \
    -w /data/spug/spug_api tdyw-test python scripts/test_upload_merge_risks.py
"""
import os, sys, json, shutil, tempfile, threading, inspect, uuid

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django; django.setup()

from django.test import TestCase, RequestFactory
from apps.account.models import User
from apps.document.models import DocumentTransfer, DocumentFilePrivate, DocumentFolderPrivate
from apps.document.constants import TransferStatus
from apps.document.views.upload.merge import check_idempotency
from apps.document.tasks.merge import TransferStatusUpdater, MergePipeline, FileRecordCreator
from apps.document.libs.naming_utils import generate_unique_logical_name
from apps.document.services.task_resolver import TaskIdResolver
from apps.document.views.upload.chunk import FileChunkUploadView
from apps.document.views.upload.resume_strategies import SuccessMarkerStrategy
from libs import json_response

def _make_user(username='testuser', tenant_id='test_tenant'):
    return User.objects.create(
        username=username, nickname=username,
        password_hash=User.make_password('test123!'),
        access_token=uuid.uuid4().hex,
        tenant_id=tenant_id, type='default',
        last_ip='127.0.0.1',
    )

def _make_transfer(user, **kw):
    d = dict(tenant_id='test_tenant', user=user, transfer_type='UPLOAD',
             status=TransferStatus.PENDING.value, file_name='test.pdf', file_size=1024,
             file_path='/data/documents/test.pdf', file_hash='', folder_id=None,
             is_public=False, system_folder='')
    d.update(kw); return DocumentTransfer.objects.create(**d)

def _read_js(rel_path):
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                        'spug_web', 'src', 'pages', 'document', 'stores', 'upload')
    p = os.path.join(base, *rel_path.split('/'))
    if not os.path.exists(p): return None
    with open(p, 'r', encoding='utf-8') as f: return f.read()

def _src_after(text, marker, length=200):
    """获取 text 中 marker 之后的 length 字符"""
    idx = text.find(marker)
    return text[idx+len(marker):idx+len(marker)+length] if idx >= 0 else ''


# ============================================================
# [P0] 跨 transfer 哈希复用已移除（原 _lookup_by_file_hash 已删除）
# ============================================================
class TestP0_HashIdempotency(TestCase):
    """_lookup_by_file_hash 已于 2026-08-07 移除，跨 transfer 哈希复用不再存在。

    原风险：_lookup_by_file_hash 不按 folder_id/system_folder 过滤，可跨目录/跨空间误命中。
    当前：merge.py check_idempotency 仅基于同一 transfer_id 查询，不支持跨 transfer 秒传。
    """

    @unittest.skip('_lookup_by_file_hash 已删除，跨 transfer 哈希复用不再存在')
    def test_01_cross_folder_hit(self):
        pass

    @unittest.skip('_lookup_by_file_hash 已删除')
    def test_02_cross_system_folder_hit(self):
        pass

    @unittest.skip('_lookup_by_file_hash 已删除')
    def test_03_public_cross_user_hit(self):
        pass

    def test_04_check_idempotency_no_cross_transfer(self):
        """check_idempotency 不再支持 file_hash 参数，仅基于 transfer_id"""
        # check_idempotency 现在只接受 transfer_id 和 user
        r, err = check_idempotency(transfer_id=999999)
        no_hit = r is None
        print(f'  [P0] 不存在的 transfer_id 不命中: {no_hit}')
        if no_hit: print('  [P0] 确认！check_idempotency 仅基于 transfer_id，无跨 transfer 哈希复用')

    @unittest.skip('_lookup_by_file_hash 已删除，无需源码检查')
    def test_05_source_no_folder_filter(self):
        pass


# ============================================================
# [P1] CANCELED 不是实际终态，合并任务可覆盖
# ============================================================
class TestP1_CancelNotTerminal(TestCase):

    def setUp(self):
        self.user = _make_user('p1_cancel', 't_cancel')
        self.transfer = _make_transfer(self.user, status=TransferStatus.CANCELED.value,
                                       file_hash='cancel_h', folder_id=400, error_message='用户取消')

    def test_01_canceled_to_completed(self):
        """CANCELED -> COMPLETED 覆盖"""
        class Mock:
            transfer_id = None
        mock = Mock(); mock.transfer_id = self.transfer.id
        TransferStatusUpdater(mock).update_status(TransferStatus.COMPLETED)
        self.transfer.refresh_from_db()
        risk = self.transfer.status == TransferStatus.COMPLETED.value
        print(f'  [P1] CANCELED->COMPLETED: {risk}')
        if risk: print('  [P1] 风险确认！已取消记录被覆盖为 COMPLETED')

    def test_02_canceled_to_merging(self):
        """CANCELED -> MERGING 覆盖"""
        class Mock:
            transfer_id = None
        mock = Mock(); mock.transfer_id = self.transfer.id
        TransferStatusUpdater(mock).update_status(TransferStatus.MERGING)
        self.transfer.refresh_from_db()
        risk = self.transfer.status == TransferStatus.MERGING.value
        print(f'  [P1] CANCELED->MERGING: {risk}')
        if risk: print('  [P1] 风险确认！已取消记录被覆盖为 MERGING')

    def test_03_source_no_status_guard(self):
        """源码无旧状态守卫"""
        src = inspect.getsource(TransferStatusUpdater.update_status)
        has_old = 'old_status' in src
        has_guard = 'if old_status' in src and (
            'return' in _src_after(src, 'if old_status', 80) or
            'raise' in _src_after(src, 'if old_status', 80)
        )
        risk = has_old and not has_guard
        print(f'  [P1] 无旧状态守卫: {risk}')
        if risk: print('  [P1] 风险确认！old_status 仅用于审计日志，无"if old_status==CANCELED: return"')


# ============================================================
# [P1] 状态更新失败仍报告成功并清理分片
# ============================================================
class TestP1_StatusUpdateSwallowed(TestCase):

    def setUp(self):
        self.user = _make_user('p1_sw', 't_sw')
        self.transfer = _make_transfer(self.user, status=TransferStatus.MERGING.value, file_hash='sw_h')

    def test_01_source_swallows_exception(self):
        """源码吞掉异常不 re-raise"""
        src = inspect.getsource(TransferStatusUpdater.update_status)
        has_try = 'try:' in src
        has_except = 'except Exception' in src
        except_block = _src_after(src, 'except Exception', 200)
        has_reraise = 'raise' in except_block
        risk = has_try and has_except and not has_reraise
        print(f'  [P1] 吞掉异常不 re-raise: {risk}')
        if risk: print('  [P1] 风险确认！except Exception 仅 logger.error')

    def test_02_silent_fail_when_record_deleted(self):
        """记录删除后 update_status 静默失败"""
        tid = self.transfer.id; self.transfer.delete()
        class Mock:
            transfer_id = None
        mock = Mock(); mock.transfer_id = tid
        try:
            TransferStatusUpdater(mock).update_status(TransferStatus.COMPLETED)
            risk = True
        except Exception:
            risk = False
        print(f'  [P1] 静默失败不抛异常: {risk}')
        if risk: print('  [P1] 风险确认！状态更新失败不抛异常，execute 继续到 _finalize_success')

    def test_03_execute_no_error_check_after_update(self):
        """execute 步骤4后不检查错误继续步骤5"""
        src = inspect.getsource(MergePipeline.execute)
        has_step4 = 'update_status' in src
        has_step5 = '_finalize_success' in src
        between = _src_after(src, 'update_status', 500).split('_finalize_success')[0] if has_step4 and has_step5 else ''
        has_check = 'if not' in between or 'if result' in between or 'if success' in between
        risk = has_step4 and has_step5 and not has_check
        print(f'  [P1] execute 不检查 update_status 结果: {risk}')
        if risk: print('  [P1] 风险确认！步骤4失败后步骤5 _finalize_success 照常执行')


# ============================================================
# [P1] 同目录同名并发上传竞态
# ============================================================
class TestP1_ConcurrentNamingRace(TestCase):

    def setUp(self):
        self.user = _make_user('p1_race', 't_race')
        self.folder = DocumentFolderPrivate.objects.create(name='race', tenant_id='t_race', created_by=self.user)

    def test_01_source_no_select_for_update(self):
        """源码无 select_for_update"""
        src = inspect.getsource(generate_unique_logical_name)
        has_tx = 'transaction.atomic' in src
        has_lock = 'select_for_update' in src
        risk = has_tx and not has_lock
        print(f'  [P1] 无 select_for_update: {risk}')
        if risk: print('  [P1] 风险确认！transaction.atomic 内无行锁，并发可生成相同名称')

    def test_02_concurrent_duplicate(self):
        """并发调用生成重复名称"""
        results = []; barrier = threading.Barrier(2)
        def gen():
            barrier.wait()
            try:
                results.append(generate_unique_logical_name(
                    FileModel=DocumentFilePrivate, original_name='report.pdf',
                    folder=self.folder, user=self.user))
            except Exception as e:
                results.append(f'ERR:{e}')
        t1 = threading.Thread(target=gen); t2 = threading.Thread(target=gen)
        t1.start(); t2.start(); t1.join(10); t2.join(10)
        print(f'  [P1] 并发结果: {results}')
        if len(results) == 2 and results[0] == results[1] and not str(results[0]).startswith('ERR'):
            print(f'  [P1] 风险确认！并发生成相同名称: {results[0]}')
        else:
            print('  [P1] 风险未复现（可能 DB 隔离级别阻止）')

    def test_03_create_file_instance_no_transfer_id(self):
        """幂等检查不含 transfer_id/file_hash"""
        src = inspect.getsource(FileRecordCreator._create_file_instance)
        if 'existing' in src.lower():
            sec = _src_after(src, 'existing', 300).lower()
            has_tid = 'transfer_id' in sec; has_hash = 'file_hash' in sec
        else:
            has_tid = has_hash = False
        risk = not has_tid and not has_hash
        print(f'  [P1] 幂等检查不含 transfer_id/file_hash: {risk}')
        if risk: print('  [P1] 风险确认！只按 name+folder 判断重试，可能关联到另一份文件')


# ============================================================
# [P2] _SUCCESS_ 标记不能证明所有分片存在
# ============================================================
class TestP2_SuccessMarkerIncomplete(TestCase):

    def test_01_marker_on_last_index_only(self):
        """源码：标记创建条件是 chunk_index == total-1"""
        src = inspect.getsource(FileChunkUploadView._update_cache_and_marker)
        has_idx = 'chunk_index' in src and 'total_chunks' in src and '- 1' in src
        no_count = 'count(' not in src and 'len(' not in src
        risk = has_idx and no_count
        print(f'  [P2] 标记仅看 chunk_index==total-1: {risk}')
        if risk: print('  [P2] 风险确认！不验证分片 0~total-2 是否已上传')

    def test_02_resume_returns_full_range(self):
        """源码：看到标记返回 range(total)"""
        src = inspect.getsource(SuccessMarkerStrategy.get_chunks)
        risk = 'list(range(total_chunks))' in src and 'os.listdir' not in src
        print(f'  [P2] resume 看到标记返回全量: {risk}')
        if risk: print('  [P2] 风险确认！不检查磁盘分片是否存在')

    def test_03_out_of_order_false_marker(self):
        """乱序上传：只传 0,1,4 但标记声称 0-4 全部就绪"""
        d = tempfile.mkdtemp(prefix='test_')
        try:
            for i in [0, 1, 4]:
                with open(os.path.join(d, f'chunk_{i}'), 'wb') as f: f.write(b'x')
            with open(os.path.join(d, '_SUCCESS_'), 'w') as f:
                json.dump({'total_chunks': 5, 'file_hash': 'test'}, f)
            class MM:
                def __init__(s, dd): s._d = dd
                def read(s):
                    p = os.path.join(s._d, '_SUCCESS_')
                    if os.path.exists(p):
                        with open(p) as f: return json.load(f)
                    return None
            strat = SuccessMarkerStrategy(lambda dd: MM(dd))
            chunks, complete = strat.get_chunks(
                chunk_dir=d, file_hash='test', user_id=1, is_public=False,
                total_chunks=5, transfer_id=999)
            risk = complete and chunks == [0, 1, 2, 3, 4]
            print(f'  [P2] 乱序标记返回完整列表: {risk}')
            if risk: print(f'  [P2] 风险确认！实际只有 0,1,4（3个）但声称 0-4 全部就绪')
        finally:
            shutil.rmtree(d, ignore_errors=True)


# ============================================================
# [P2] 合并状态查询缺少任务归属校验
# ============================================================
class TestP2_NoOwnershipCheck(TestCase):

    def setUp(self):
        self.user_a = _make_user('p2_a', 't_a')
        self.user_b = _make_user('p2_b', 't_b')

    def test_01_status_view_no_ownership(self):
        """源码：FileMergeStatusView 无归属校验"""
        from apps.document.views.upload.status import FileMergeStatusView
        src = inspect.getsource(FileMergeStatusView.get)
        has_filter = 'request.user' in src and ('filter' in src or 'exclude' in src)
        risk = not has_filter
        print(f'  [P2] status.py 无归属校验: {risk}')
        if risk: print('  [P2] 风险确认！接受任意 task_id，不验证所属用户')

    def test_02_resolver_accepts_any_task_id(self):
        """TaskIdResolver 接受任意 task_id"""
        f = RequestFactory()
        req = f.get('/', {'task_id': 'other_user_task'}); req.user = self.user_b
        tid, mtid, data = TaskIdResolver().resolve(req)
        risk = tid == 'other_user_task'
        print(f'  [P2] 接受任意 task_id: {risk}')
        if risk: print('  [P2] 风险确认！不校验 task_id 归属')

    def test_03_resolver_accepts_any_merge_task_id(self):
        """TaskIdResolver 接受任意 merge_task_id"""
        f = RequestFactory()
        req = f.get('/', {'merge_task_id': 'other_merge'}); req.user = self.user_b
        tid, mtid, data = TaskIdResolver().resolve(req)
        risk = mtid == 'other_merge'
        print(f'  [P2] 接受任意 merge_task_id: {risk}')
        if risk: print('  [P2] 风险确认！不校验 merge_task_id 归属')

    def test_04_resolver_source_no_ownership(self):
        """源码：resolve 无归属校验"""
        src = inspect.getsource(TaskIdResolver.resolve)
        has_user = 'request.user' in src and ('filter' in src or 'exclude' in src)
        has_tenant = 'tenant' in src and 'filter' in src
        risk = not has_user and not has_tenant
        print(f'  [P2] resolve 无归属校验: {risk}')
        if risk: print('  [P2] 风险确认！只从 GET 读取参数，不校验归属')


# ============================================================
# [P1] 分片 XHR 把后端业务错误当作上传成功
# ============================================================
class TestP1_ChunkXHRIgnoresError(TestCase):

    def test_01_json_response_200_for_error(self):
        """json_response(error=...) 返回 HTTP 200"""
        r = json_response(error='文件大小超出限制')
        risk = r.status_code == 200
        print(f'  [P1] json_response(error) 返回 HTTP 200: {risk}')
        if risk:
            print(f'  [P1] body={json.loads(r.content)}')
            print('  [P1] 风险确认！前端 xhr.status===200 会 resolve，不 reject')

    def test_02_chunk_view_uses_json_response_for_errors(self):
        """分片上传视图对错误用 json_response(error=...)"""
        src = inspect.getsource(FileChunkUploadView.post)
        count = src.count('json_response(error=')
        risk = count > 0
        print(f'  [P1] 分片视图有 {count} 处 json_response(error=...): {risk}')
        if risk: print('  [P1] 风险确认！这些错误返回 HTTP 200，前端误判为成功')


# ============================================================
# [P1] 合并重试永久停在 merging（前端静态分析）
# ============================================================
class TestP1_MergeRetryStuck(TestCase):

    def test_01_no_start_merge_polling(self):
        """ChunkUploadStore 无 startMergePolling 方法"""
        src = _read_js('core/chunkUpload.js')
        if src is None:
            print('  [P1] 前端文件不存在，跳过'); return
        has_def = 'async startMergePolling' in src or 'startMergePolling =' in src
        has_poll = 'pollMergeStatus' in src
        risk = not has_def
        print(f'  [P1] 无 startMergePolling 方法定义: {risk}')
        if risk:
            print('  [P1] 风险确认！ItemOperationController 调用 startMergePolling 但该方法不存在')
            if has_poll: print('  [P1] 实际方法名是 pollMergeStatus，不匹配')

    def test_02_state_handler_skips_retry_merge(self):
        """StateChangeHandler 对 RETRY_MERGE 跳过"""
        src = _read_js('core/lifecycle/StateChangeHandler.js')
        if src is None:
            print('  [P1] 前端文件不存在，跳过'); return
        has_retry = 'RETRY_MERGE' in src
        print(f'  [P1] StateChangeHandler 处理 RETRY_MERGE: {has_retry}')
        if has_retry:
            after = _src_after(src, 'RETRY_MERGE', 300)
            has_return = 'return' in after[:100]
            has_merge = 'mergeChunks' in after[:300]
            risk = has_return and not has_merge
            print(f'  [P1] RETRY_MERGE 直接 return 不调 mergeChunks: {risk}')
            if risk: print('  [P1] 风险确认！RETRY_MERGE 跳过合并和轮询，永久停在 merging')


# ============================================================
# [P2] 轮询把确定失败当网络抖动（前端静态分析）
# ============================================================
class TestP2_PollSwallowsFailure(TestCase):

    def test_01_catch_swallows_definite_errors(self):
        """catch 块用重试逻辑吞掉确定错误"""
        src = _read_js('core/chunkUpload.js')
        if src is None:
            print('  [P2] 前端文件不存在，跳过'); return
        throws = "status.status === 'failed'" in src and 'throw' in _src_after(src, "status.status === 'failed'", 200)
        has_catch = 'catch' in src and 'consecutiveErrors' in src
        risk = throws and has_catch
        print(f'  [P2] 确定错误被 catch 当可重试: {risk}')
        if risk:
            print('  [P2] 风险确认！failed/timeout/not_found 抛 Error 后被 catch 捕获')
            print('  [P2] catch 用 consecutiveErrors 重试，真实合并错误被掩盖')


# ============================================================
# 运行入口
# ============================================================
if __name__ == '__main__':
    import unittest
    suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print('\n' + '=' * 70)
    print('风险验证汇总')
    print('=' * 70)
    print(f'测试数: {result.testsRun}, 失败: {len(result.failures)}, 错误: {len(result.errors)}')
    for t, err in result.failures + result.errors:
        print(f'  FAIL: {t}')

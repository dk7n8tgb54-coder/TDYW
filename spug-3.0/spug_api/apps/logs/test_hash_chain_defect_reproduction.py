# -*- coding: utf-8 -*-
"""审计日志哈希链断链根因验证与修复效果测试

生产 2026-09-18 告警共 1448 条链校验错误，诊断结论为两个根因叠加：
1429 条并发分叉 + 19 条迁移遗留字段不一致。本文件先以真实行为测试复现
根因，并验证 2026-09-18 落地的修复（AuditLogSequence 租户级稳定锁行）：

根因一（并发分叉）——已复现，已修复，本文件现为修复效果验证
    旧 save_audit_log（apps/logs/audit.py）在事务内以
    ``select_for_update().order_by('-id').first()`` 锁定"当前最后一条日志"。
    该行是随每次写入变动的行，不是稳定的租户锁：后到事务在旧尾节点的行锁上
    阻塞期间，先到事务提交了新尾节点；InnoDB 阻塞解除后从原扫描位置返回
    旧尾节点（不重新定位到新插入的更大 id 行），两个事务因此基于同一个
    prev_hash 落库，形成兄弟分叉。生产 1448 条错误中 1429 条即此模式
    （断点两侧记录自身哈希均正确、prev_hash 指向真实存在的旧记录）。

    修复（2026-09-18）：新增每租户一行的稳定锁行 AuditLogSequence，
    save_audit_log 在事务内先对该固定行 select_for_update 串行化同租户
    写入，再在临界区内以锁定读读取尾节点；并发方阻塞在固定行上，先到方
    提交后必然能看到新尾节点。迁移 0011 同时为存量租户回填尾节点缓存。

    验证方式：在主事务"已锁定尾节点、尚未计算哈希落库"的真实检查点
    （compute_log_hash_from_values 调用处）注入第二条并发写入。并发侧与
    生产请求相同——独立数据库连接、完整执行真实 save_audit_log——修复前
    其尾节点锁定读必然阻塞在主事务持有的行锁上并返回旧尾节点（分叉），
    修复后阻塞点移到稳定锁行上，解除后必然读到先到方提交的新尾节点。
    100% 确定性复现/验证，无随机竞争。写法参照
    apps/coop_task/tests/test_coop_task_concurrency.py 的检查点注入先例。

根因二（迁移改写哈希输入字段但不重算哈希）——已复现，未做历史重写
    0009_auditlog_audit_action_valid.py:18-20 把 upload_attachment /
    delete_attachment / download_attachment 三类 action 原地 update 为
    'other'，而 log_hash 的输入覆盖 action 字段
    （hash_chain.build_log_hash_payload_from_values），迁移未重算哈希，
    库内留存"action=other + 按迁移前 action 计算的 log_hash"状态，
    校验必然报"log_hash 与字段不一致，疑似被篡改"——即生产 19 条错误的
    来源（2026-07-27 规章附件日志：14 upload / 4 delete / 1 download）。
    测试同时证明：用迁移前 action 重算与库存 log_hash 精确一致，
    内容未被篡改。按"历史数据不静默重写"约定，本批历史行留待受控
    迁移决策（建立新链纪元或重建链），本文件持续固定其证据。

约定：
- 并发用例使用 TransactionTestCase + 独立数据库连接（每线程 close_all），
  允许线程内真实提交并跨线程可见；顺序用例作为对照证明修复前断裂仅由
  并发引起，而非校验/管道问题。
- 0009 迁移后 audit_action_valid CHECK 约束禁止直接插入迁移前 action 值，
  根因二用例按"迁移执行后的库存遗留状态"构造行，与生产数据形态一致。
- test_concurrent_saves_keep_chain_linked 断言修复后的期望行为（链不分叉），
  修复落地后由 expectedFailure 转为常规契约测试（stable_contract 级），
  防止并发分叉回归；管道自检用例与该用例共用注入管道，用于保证管道本身
  可靠、不掩盖基建错误。
"""
import json
import tempfile
import threading
import time
from unittest import mock

from django.db import IntegrityError, OperationalError, connections, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.logs import hash_chain as hash_chain_mod
from apps.logs.audit import save_audit_log
from apps.logs.hash_chain import (
    build_log_hash_payload, compute_log_hash, compute_log_hash_from_values,
    compute_request_hash, verify_hash_chain, verify_log_hash,
)
from apps.logs.models import AuditLog, AuditLogSequence
from apps.logs.tasks import verify_audit_hash_chain

# 并发分叉探针租户（与链首/主写/并发写一一对应，独立成链便于断言）
FORK_TENANT = 'chainfork-probe'
SEQ_TENANT = 'chainfork-seq'
# 迁移遗留状态用例租户
REMAP_TENANT = 'remap-probe'
# 主事务在检查点停留秒数：给并发侧留出到达锁等待点的时间。
# 生产中 ATOMIC_REQUESTS 使行锁持有整个请求周期（秒级），此处 0.6s 已足够
# 并发侧完成建连并阻塞到行锁上。
_INJECT_DELAY = 0.6

# 0009 迁移改写为 'other' 的三类附件 action（0009_auditlog_audit_action_valid.py:18-20）
REMAP_OLD_ACTIONS = ['upload_attachment', 'delete_attachment', 'download_attachment']


def _probe_payload(tenant_id, request_id, marker):
    """构造并发探针的 save_audit_log 入参（真实代码路径使用）"""
    return dict(
        user_id=9, username='chain-probe', action='create',
        target_type='audit_probe', target_id=marker,
        target_name='分叉探针%s' % marker,
        detail={'marker': marker}, ip='127.0.0.1', is_success=True,
        tenant_id=tenant_id, request_id=request_id,
    )


class HashChainConcurrencyForkTests(TransactionTestCase):
    """根因一：并发写入在当前实现下产生兄弟分叉（真实线程 + 独立连接）"""

    def _fork_scene(self):
        """构造"链首 + 主写 + 注入并发写"场景，返回按 request_id 定位的记录。

        确定性时序（无随机竞争）：
        1. 链首 parent 正常落库（未打补丁的真实写入）；
        2. 主写事务执行 select_for_update 锁定 parent（此时锁持有至提交）；
        3. 主写到达 compute_log_hash_from_values 检查点时启动并发线程，
           并发侧完整执行真实 save_audit_log，其尾节点锁定读阻塞在
           parent 的行锁上（必然发生：parent 是该租户当时唯一/最大的行）；
        4. 主写完成哈希计算、落库、提交；
        5. 并发侧解除阻塞，继续完成写入。
        """
        save_audit_log(**_probe_payload(FORK_TENANT, 'req-parent', 'P'))

        injected = {'fired': False}
        rival_result = {'error': None, 'thread': None}
        real_compute = hash_chain_mod.compute_log_hash_from_values

        def compute_with_injection(*args, **kwargs):
            if not injected['fired']:
                injected['fired'] = True

                def rival_writer():
                    try:
                        save_audit_log(
                            **_probe_payload(FORK_TENANT, 'req-rival', 'R'))
                    except Exception as exc:  # pragma: no cover - 管道自检覆盖
                        rival_result['error'] = exc
                    finally:
                        # 并发线程持有独立数据库连接，结束时必须归还
                        connections.close_all()

                rival_thread = threading.Thread(
                    target=rival_writer, name='audit-chain-rival')
                rival_result['thread'] = rival_thread
                rival_thread.start()
                # 主事务在检查点停留：并发侧此时已阻塞在行锁上且未提交，
                # 与生产"后到请求阻塞在旧尾节点行锁"的时序一致
                time.sleep(_INJECT_DELAY)
            return real_compute(*args, **kwargs)

        with mock.patch.object(hash_chain_mod, 'compute_log_hash_from_values',
                               compute_with_injection):
            save_audit_log(**_probe_payload(FORK_TENANT, 'req-main', 'M'))

        rival_thread = rival_result['thread']
        rival_thread.join(timeout=30)
        self.assertFalse(rival_thread.is_alive(), '并发写入线程超时未结束')
        self.assertIsNone(rival_result['error'],
                          '并发侧 save_audit_log 不应抛出异常: %r'
                          % (rival_result['error'],))

        logs = list(
            AuditLog.objects.filter(tenant_id=FORK_TENANT).order_by('id'))
        self.assertEqual(len(logs), 3,
                         '应有链首 + 主写 + 并发写共 3 条记录: %r'
                         % [l.request_id for l in logs])
        by_request = {log.request_id: log for log in logs}
        self.assertEqual(sorted(by_request),
                         ['req-main', 'req-parent', 'req-rival'])
        return (by_request['req-parent'], by_request['req-main'],
                by_request['req-rival'])

    # ---- 对照组（当前应通过）：顺序写入链完整 ----

    def test_sequential_saves_keep_chain_fully_valid(self):
        """顺序写入时链完整：证明并发用例的断裂只由并发引起，而非校验/管道问题"""
        for marker in ('S1', 'S2', 'S3'):
            save_audit_log(**_probe_payload(SEQ_TENANT, 'req-' + marker, marker))
        logs = list(AuditLog.objects.filter(tenant_id=SEQ_TENANT).order_by('id'))
        self.assertEqual(len(logs), 3)
        for i in range(1, len(logs)):
            self.assertEqual(logs[i].prev_hash, logs[i - 1].log_hash,
                             '顺序写入第 %d 条应链到前一条' % i)
        result = verify_hash_chain(logs)
        self.assertTrue(result['valid'], result['errors'])

    # ---- 管道自检（当前应通过，且无 expectedFailure）：注入管道可靠 ----

    def test_injected_concurrent_saves_both_land_with_valid_individual_hashes(self):
        """两条并发记录都真实落库且单条哈希有效——生产特征"断点两侧记录自身哈希正确"。

        本用例不含 expectedFailure：若注入管道不可靠（线程未落库、连接异常），
        在此显式失败，避免 expectedFailure 用例把基建问题误报为缺陷复现。
        """
        parent, main_log, rival_log = self._fork_scene()
        for log in (parent, main_log, rival_log):
            self.assertTrue(log.log_hash, 'id=%s log_hash 应非空' % log.id)
            self.assertTrue(
                verify_log_hash(log),
                'id=%s 单条哈希应与自身字段一致（生产特征：断点两侧记录自身哈希正确）'
                % log.id)
        # 先提交者链到注入时的真实尾节点（该行为不受缺陷影响）
        self.assertEqual(main_log.prev_hash, parent.log_hash,
                         '主写应链到链首 parent')
        # 生产特征：分叉记录的 prev_hash 指向真实存在的旧记录
        self.assertIn(rival_log.prev_hash,
                      [parent.log_hash, main_log.log_hash],
                      '并发记录的 prev_hash 应指向链上真实存在的记录')

    # ---- 修复效果验证（stable_contract 级，防并发分叉回归） ----

    def test_concurrent_saves_keep_chain_linked(self):
        """并发写入后后提交者必须链到先提交者，而不是共享旧尾节点。

        修复前（取证记录）：rival（后提交）的 prev_hash == parent.log_hash，
        与 main（先提交）同基旧尾节点，形成兄弟分叉——生产 1429 条并发分叉
        的产生机制。修复后（AuditLogSequence 稳定锁行）：rival 阻塞在固定
        锁行上，main 提交后 rival 必然读到 main 的尾哈希。
        """
        parent, main_log, rival_log = self._fork_scene()
        self.assertEqual(
            rival_log.prev_hash, main_log.log_hash,
            '并发分叉回归：rival(id=%s) 的 prev_hash=%s... 与 main(id=%s) '
            '同基旧尾节点 parent(id=%s) 的 log_hash=%s...，应为 main 的 '
            'log_hash=%s...'
            % (rival_log.id, rival_log.prev_hash[:12], main_log.id,
               parent.id, parent.log_hash[:12], main_log.log_hash[:12]))
        result = verify_hash_chain(
            AuditLog.objects.filter(tenant_id=FORK_TENANT).order_by('id'))
        self.assertTrue(result['valid'], result['errors'])


class AuditLogSequenceBehaviorTests(TestCase):
    """AuditLogSequence 稳定锁行行为测试（修复配套）"""

    def test_sequence_row_tracks_tenant_tail(self):
        """每次写入后序列行尾节点缓存与最新日志一致"""
        for marker in ('T1', 'T2'):
            save_audit_log(**_probe_payload(FORK_TENANT, 'req-' + marker, marker))
        tail = AuditLog.objects.filter(tenant_id=FORK_TENANT).order_by('-id').first()
        seq = AuditLogSequence.objects.get(tenant_id=FORK_TENANT)
        self.assertEqual(seq.last_log_id, tail.id)
        self.assertEqual(seq.last_log_hash, tail.log_hash)

    def test_sequence_lazy_init_continues_existing_chain(self):
        """序列行缺失（等价迁移前存量租户）时惰性建行，且新日志续接既有链尾"""
        save_audit_log(**_probe_payload(SEQ_TENANT, 'req-L1', 'L1'))
        save_audit_log(**_probe_payload(SEQ_TENANT, 'req-L2', 'L2'))
        # 模拟 0011 迁移前的存量租户：有日志、无序列行
        AuditLogSequence.objects.filter(tenant_id=SEQ_TENANT).delete()
        self.assertFalse(AuditLogSequence.objects.filter(tenant_id=SEQ_TENANT).exists())

        save_audit_log(**_probe_payload(SEQ_TENANT, 'req-L3', 'L3'))

        logs = list(AuditLog.objects.filter(tenant_id=SEQ_TENANT).order_by('id'))
        self.assertEqual(len(logs), 3)
        result = verify_hash_chain(logs)
        self.assertTrue(result['valid'], result['errors'])
        self.assertEqual(logs[2].prev_hash, logs[1].log_hash,
                         '惰性建行后的新日志必须续接既有链尾')
        seq = AuditLogSequence.objects.get(tenant_id=SEQ_TENANT)
        self.assertEqual(seq.last_log_id, logs[2].id)
        self.assertEqual(seq.last_log_hash, logs[2].log_hash)

    def test_sequence_tail_cache_survives_seq_row_absence_for_new_tenant(self):
        """全新租户首写：惰性建行且链首 prev_hash 为空串"""
        save_audit_log(**_probe_payload('chainfork-new', 'req-N1', 'N1'))
        seq = AuditLogSequence.objects.get(tenant_id='chainfork-new')
        log = AuditLog.objects.get(tenant_id='chainfork-new')
        self.assertEqual(seq.last_log_id, log.id)
        self.assertEqual(seq.last_log_hash, log.log_hash)
        self.assertEqual(log.prev_hash, '', '全新租户首写应为链首')


class ActionRemapWithoutHashRecomputeTests(TestCase):
    """根因二：0009 迁移改写 action 未重算 log_hash → "字段不一致"误报

    构造的行与 0009 执行后的生产库存形态一致：
    action='other'（迁移后值）+ log_hash 按迁移前 action 计算（未重算）。
    """

    def _make_remap_row(self, old_action):
        """按迁移后遗留状态写入一条审计日志，从库回读（与校验任务同口径）"""
        created_at = timezone.now().replace(microsecond=0)
        detail_str = json.dumps(
            {'summary': '上传规章附件', 'file_name': '证据材料.pdf'},
            ensure_ascii=False)
        request_hash = compute_request_hash(detail_str)
        # 用迁移前 action 计算哈希：复现"迁移改写 action 但未重算"留下的库存哈希
        stored_hash = compute_log_hash_from_values(
            tenant_id=REMAP_TENANT, user_id=5, username='reg-user',
            action=old_action, target_type='regulation', target_id='12',
            target_name='规章附件', detail=detail_str, ip='10.8.0.6',
            is_success=True, created_at=created_at,
            request_hash=request_hash, response_hash='',
            request_id='req-remap-0009', user_agent='ua', prev_hash='')
        row = AuditLog.objects.create(
            user_id=5, username='reg-user',
            action='other',  # 0009:18-20 改写后的库存值
            target_type='regulation', target_id='12', target_name='规章附件',
            detail=detail_str, ip='10.8.0.6', is_success=True,
            tenant_id=REMAP_TENANT, created_at=created_at,
            request_hash=request_hash, response_hash='',
            prev_hash='', log_hash=stored_hash,
            request_id='req-remap-0009', user_agent='ua')
        return AuditLog.objects.get(pk=row.pk)

    def test_remap_state_reports_field_mismatch(self):
        """迁移遗留状态必然触发链校验"log_hash 与字段不一致"错误（19 条告警的来源）"""
        for old_action in REMAP_OLD_ACTIONS:
            with self.subTest(old_action=old_action):
                row = self._make_remap_row(old_action)
                self.assertTrue(row.log_hash, '库存 log_hash 非空（不是旧数据缺哈希）')
                self.assertFalse(
                    verify_log_hash(row),
                    'action 被 0009 改写后未重算哈希，单条校验应判不一致')
                result = verify_hash_chain([row])
                self.assertFalse(result['valid'])
                self.assertIn('字段不一致', result['errors'][0])
                self.assertIn('疑似被篡改', result['errors'][0])

    def test_pre_migration_action_recompute_matches_stored_hash(self):
        """篡改排除：用迁移前 action 重算与库存 log_hash 精确一致，内容原样

        对应生产诊断方法："使用迁移前的 action 重算，19 条全部精确匹配原
        log_hash"。反向对照：按当前字段（action='other'）重算不匹配，
        证明差异恰好且仅来自 0009 对 action 字段的改写。
        """
        for old_action in REMAP_OLD_ACTIONS:
            with self.subTest(old_action=old_action):
                row = self._make_remap_row(old_action)
                payload = build_log_hash_payload(row)
                self.assertNotEqual(
                    compute_log_hash(payload), row.log_hash,
                    '按当前库存字段重算应不一致（告警来源）')
                payload['action'] = old_action  # 还原 0009 改写前的 action
                self.assertEqual(
                    compute_log_hash(payload), row.log_hash,
                    '用迁移前 action 重算应与库存 log_hash 精确一致（内容未被篡改）')

    def test_daily_verify_task_alarms_on_remap_state(self):
        """真实定时任务代码路径：迁移遗留状态触发每日告警（level=error）"""
        self._make_remap_row('upload_attachment')
        with mock.patch('libs.alert.send_alert') as alert_spy:
            result = verify_audit_hash_chain.apply(args=()).get()
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['total_errors'], 1)
        self.assertEqual(len(result['details']), 1)
        self.assertEqual(result['details'][0]['tenant_id'], REMAP_TENANT)
        self.assertTrue(alert_spy.called, '存在校验错误时应发送告警')
        self.assertEqual(alert_spy.call_args.kwargs.get('level'), 'error')
        self.assertIn('1 处哈希链断裂', alert_spy.call_args.kwargs.get('message', ''))

    def test_check_constraint_rejects_pre_migration_action(self):
        """0009 加装的 audit_action_valid CHECK 约束已禁止迁移前 action 入库

        说明根因二用例为何必须按迁移后遗留状态构造数据，同时防止该约束被
        无意移除。
        """
        with self.assertRaises((IntegrityError, OperationalError)):
            with transaction.atomic():
                AuditLog.objects.create(
                    user_id=1, username='reg-user', action='upload_attachment',
                    target_type='regulation', ip='', tenant_id=REMAP_TENANT)

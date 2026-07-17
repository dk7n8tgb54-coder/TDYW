# -*- coding: utf-8 -*-
"""
传输状态机 Django TestCase

对应报告：资料库代码质量报告.md（P0-1）、资料库代码质量修复建议.md（第1项+第2项）。
本测试作为 CI 守门的一部分，验证传输状态机的核心不变量：

  1. TransferStatus 枚举与 DocumentTransfer.TRANSFER_STATUS_CHOICES 完全一致
  2. ALLOWED_STATUS_TRANSITIONS 引用的状态都是合法枚举值，且覆盖全部枚举
  3. 所有声明的合法转换都能通过 is_valid_status_transition（反之亦然）
  4. 终态（COMPLETED / CANCELED）无出边，且不可再被转换出去
  5. 关键业务链路转换合法：上传/分片合并/下载/暂停恢复/失败重试/取消
  6. 每个非终态至少有 1 个出边，每个非初始态至少有 1 个入边
  7. TransferStatus(value) 构造：合法值成功、非法值抛 ValueError
  8. 拼写一致性：后端统一使用美式 CANCELED

运行方式（纳入 manage.py test 收集，可独立运行）：
  docker exec tdyw python /data/spug/spug_api/manage.py test tests.test_transfer_state_machine
"""
from django.test import TestCase

from apps.document.constants import (
    TransferStatus,
    ALLOWED_STATUS_TRANSITIONS,
    is_valid_status_transition,
)
from apps.document.models import DocumentTransfer


class TransferStateMachineTestCase(TestCase):
    """传输状态机核心不变量测试。"""

    def test_enum_matches_choices(self):
        """TransferStatus 枚举与 TRANSFER_STATUS_CHOICES 完全一致（数量与成员）。"""
        enum_values = {s.value for s in TransferStatus}
        choices_values = {val for val, _label in DocumentTransfer.TRANSFER_STATUS_CHOICES}

        for status in TransferStatus:
            self.assertIn(
                status.value, choices_values,
                f"枚举 {status.name}({status.value}) 应存在于 TRANSFER_STATUS_CHOICES",
            )

        for val, label in DocumentTransfer.TRANSFER_STATUS_CHOICES:
            self.assertIn(
                val, enum_values,
                f"Choices {val}('{label}') 应存在于 TransferStatus 枚举",
            )

        self.assertEqual(
            len(enum_values), len(choices_values),
            f"枚举数量({len(enum_values)}) 应等于 Choices 数量({len(choices_values)})",
        )

    def test_transition_table_references_valid_enums(self):
        """ALLOWED_STATUS_TRANSITIONS 的源与目标都是合法 TransferStatus。"""
        for source_status in ALLOWED_STATUS_TRANSITIONS:
            self.assertIsInstance(
                source_status, TransferStatus,
                f"转换源 {source_status} 应是 TransferStatus 实例",
            )
        for source_status, targets in ALLOWED_STATUS_TRANSITIONS.items():
            for target in targets:
                self.assertIsInstance(
                    target, TransferStatus,
                    f"转换目标 {target}（来自 {source_status.name}）应是 TransferStatus 实例",
                )

    def test_transition_table_covers_all_enum_states(self):
        """每个枚举状态都出现在转换表中（源或目标）。"""
        sources = set(ALLOWED_STATUS_TRANSITIONS.keys())
        all_targets = set()
        for targets in ALLOWED_STATUS_TRANSITIONS.values():
            all_targets.update(targets)

        for status in TransferStatus:
            self.assertTrue(
                status in sources or status in all_targets,
                f"{status.name} 应出现在转换表中（源={status in sources}, 目标={status in all_targets}）",
            )

    def test_allowed_transitions_are_valid(self):
        """所有声明为合法的转换都应通过 is_valid_status_transition。"""
        for source, targets in ALLOWED_STATUS_TRANSITIONS.items():
            for target in targets:
                self.assertTrue(
                    is_valid_status_transition(source, target),
                    f"is_valid_status_transition({source.name}, {target.name}) 应为 True",
                )

    def test_disallowed_transitions_are_invalid(self):
        """所有未在 ALLOWED 中声明的转换都应被拒绝。"""
        for source in TransferStatus:
            allowed = set(ALLOWED_STATUS_TRANSITIONS.get(source, []))
            for target in TransferStatus:
                if target not in allowed:
                    self.assertFalse(
                        is_valid_status_transition(source, target),
                        f"is_valid_status_transition({source.name}, {target.name}) 应为 False",
                    )

    def test_terminal_states_have_no_out_edges(self):
        """终态 COMPLETED / CANCELED 无出边，且不可再转换出去。"""
        terminal_states = [TransferStatus.COMPLETED, TransferStatus.CANCELED]

        for ts in terminal_states:
            out_transitions = ALLOWED_STATUS_TRANSITIONS.get(ts, [])
            self.assertEqual(
                len(out_transitions), 0,
                f"{ts.name} 应为终态，无出边，当前出边数={len(out_transitions)}",
            )

        for ts in terminal_states:
            for other in TransferStatus:
                if other != ts:
                    self.assertFalse(
                        is_valid_status_transition(ts, other),
                        f"终态 {ts.name} 不可转换到 {other.name}",
                    )

    def test_key_business_paths(self):
        """关键业务链路转换合法。"""
        # 小文件上传：PENDING -> UPLOADING -> COMPLETED
        self.assertTrue(is_valid_status_transition(TransferStatus.PENDING, TransferStatus.UPLOADING))
        self.assertTrue(is_valid_status_transition(TransferStatus.PENDING, TransferStatus.COMPLETED))
        self.assertTrue(is_valid_status_transition(TransferStatus.PENDING, TransferStatus.FAILED))

        # 分片上传：PENDING -> UPLOADING -> MERGING -> COMPLETED
        self.assertTrue(is_valid_status_transition(TransferStatus.UPLOADING, TransferStatus.MERGING))
        self.assertTrue(is_valid_status_transition(TransferStatus.MERGING, TransferStatus.COMPLETED))

        # 上传暂停 / 恢复
        self.assertTrue(is_valid_status_transition(TransferStatus.UPLOADING, TransferStatus.PAUSED))
        self.assertTrue(is_valid_status_transition(TransferStatus.PAUSED, TransferStatus.UPLOADING))

        # 下载链路：PENDING -> DOWNLOADING -> COMPLETED
        self.assertTrue(is_valid_status_transition(TransferStatus.PENDING, TransferStatus.DOWNLOADING))
        self.assertTrue(is_valid_status_transition(TransferStatus.DOWNLOADING, TransferStatus.COMPLETED))

        # 下载暂停 / 恢复
        self.assertTrue(is_valid_status_transition(TransferStatus.DOWNLOADING, TransferStatus.PAUSED))
        self.assertTrue(is_valid_status_transition(TransferStatus.PAUSED, TransferStatus.DOWNLOADING))

        # 失败重试
        self.assertTrue(is_valid_status_transition(TransferStatus.FAILED, TransferStatus.UPLOADING))
        self.assertTrue(is_valid_status_transition(TransferStatus.FAILED, TransferStatus.DOWNLOADING))

        # 合并失败
        self.assertTrue(is_valid_status_transition(TransferStatus.MERGING, TransferStatus.FAILED))

    def test_cancelable_from_non_terminal_states(self):
        """各非终态均可取消到 CANCELED。"""
        cancelable_from = [
            TransferStatus.PENDING,
            TransferStatus.UPLOADING,
            TransferStatus.DOWNLOADING,
            TransferStatus.MERGING,
            TransferStatus.FAILED,
        ]
        for src in cancelable_from:
            self.assertTrue(
                is_valid_status_transition(src, TransferStatus.CANCELED),
                f"{src.name} -> CANCELED 应合法",
            )

    def test_completeness_out_and_in_edges(self):
        """每个非终态至少有 1 个出边；每个非初始态至少有 1 个入边。"""
        terminal_states = [TransferStatus.COMPLETED, TransferStatus.CANCELED]

        for status in TransferStatus:
            out_edges = ALLOWED_STATUS_TRANSITIONS.get(status, [])
            if status in terminal_states:
                self.assertEqual(len(out_edges), 0, f"终态 {status.name} 出边数应为 0")
            else:
                self.assertGreater(
                    len(out_edges), 0,
                    f"非终态 {status.name} 应至少有 1 个出边（当前={len(out_edges)}）",
                )

        initial_states = {TransferStatus.PENDING}
        non_initial = set(TransferStatus) - initial_states
        for status in non_initial:
            in_count = sum(
                1 for src, targets in ALLOWED_STATUS_TRANSITIONS.items()
                if status in targets
            )
            self.assertGreater(
                in_count, 0,
                f"非初始态 {status.name} 应至少有 1 个入边（当前={in_count}）",
            )

    def test_enum_construction(self):
        """TransferStatus(value) 构造：合法值成功，非法值抛 ValueError。"""
        for val, _label in DocumentTransfer.TRANSFER_STATUS_CHOICES:
            try:
                status = TransferStatus(val)
                self.assertEqual(status.value, val)
            except ValueError:
                self.fail(f"TransferStatus('{val}') 构造应成功")

        with self.assertRaises(ValueError):
            TransferStatus('NONEXISTENT')

    def test_spelling_consistency(self):
        """拼写一致性：后端统一使用美式 CANCELED。"""
        self.assertEqual(TransferStatus.CANCELED.value, 'CANCELED')
        canceled_in_choices = any(
            v == 'CANCELED' for v, _ in DocumentTransfer.TRANSFER_STATUS_CHOICES
        )
        self.assertTrue(canceled_in_choices, "TRANSFER_STATUS_CHOICES 应使用 CANCELED")

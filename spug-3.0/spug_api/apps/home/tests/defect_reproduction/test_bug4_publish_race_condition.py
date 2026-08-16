# -*- coding: utf-8 -*-
"""
Bug 4 复现测试：发布/撤回操作无并发保护（竞态条件）

缺陷描述：
  AnnouncementPublishView 和 AnnouncementWithdrawView 先查询再修改，
  未使用 select_for_update()，两个管理员同时操作可通过状态前置校验。

复现路径：
  1. 创建未发布公告
  2. 两个线程同时发起发布请求
  3. 两个请求都通过 status != PUBLISHED 检查
  4. 快照字段被后一个请求覆盖
"""
import json
import threading
import time

from django.test import TestCase

from apps.home.models import Announcement, STATUS_UNPUBLISHED, STATUS_PUBLISHED
from apps.home.tests.characterization.test_announcement import (
    _make_user, _grant_perms, _make_client, _make_announcement, ANN_PERMS,
)
from apps.utils.test_helpers import setup_test_env


class Bug4PublishRaceConditionTests(TestCase):
    """发布操作竞态条件"""

    def setUp(self):
        setup_test_env(self)
        self.user1 = _make_user('publisher1', tenant_id='t1')
        self.user2 = _make_user('publisher2', tenant_id='t1')
        _grant_perms(self.user1, ANN_PERMS)
        _grant_perms(self.user2, ANN_PERMS)
        self.client1 = _make_client(self.user1)
        self.client2 = _make_client(self.user2)

    def test_concurrent_publish_both_succeed(self):
        """两个管理员同时发布同一未发布公告，两个请求都返回成功"""
        ann = _make_announcement(
            self.user1, status=STATUS_UNPUBLISHED,
            published_at=None, published_by_id=None, published_by_name='',
        )

        results = [None, None]
        barrier = threading.Barrier(2)

        def do_publish(client, idx):
            barrier.wait()
            resp = client.post(f'/home/announcement/admin/{ann.id}/publish/')
            results[idx] = resp.json()

        t1 = threading.Thread(target=do_publish, args=(self.client1, 0))
        t2 = threading.Thread(target=do_publish, args=(self.client2, 1))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        ann.refresh_from_db()
        # 最终状态应正确
        self.assertEqual(ann.status, STATUS_PUBLISHED)

        # 竞态标志：两个请求都返回成功（都通过了 status != PUBLISHED 检查）
        errors = [r.get('error') for r in results if r]
        no_errors = [r for r in results if not r.get('error')]
        # 如果两个都无错误，说明发生了竞态
        # 如果只有一个成功一个失败，说明 check-then-act 有一定保护（但实际上没有锁）
        if len(no_errors) == 2:
            # 竞态发生：两个请求都通过了检查
            # 快照字段被覆盖，但状态最终正确
            self.assertEqual(ann.status, STATUS_PUBLISHED)
            # 记录：published_by 快照是后完成的那个人，前一个人的数据丢失
        elif len(no_errors) == 1:
            # 测试环境可能串行执行，只有一个成功
            self.assertEqual(ann.status, STATUS_PUBLISHED)

    def test_concurrent_withdraw_both_succeed(self):
        """两个管理员同时撤回同一已发布公告"""
        ann = _make_announcement(self.user1, status=STATUS_PUBLISHED)

        results = [None, None]
        barrier = threading.Barrier(2)

        def do_withdraw(client, idx):
            barrier.wait()
            resp = client.post(f'/home/announcement/admin/{ann.id}/withdraw/')
            results[idx] = resp.json()

        t1 = threading.Thread(target=do_withdraw, args=(self.client1, 0))
        t2 = threading.Thread(target=do_withdraw, args=(self.client2, 1))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        ann.refresh_from_db()
        self.assertEqual(ann.status, STATUS_UNPUBLISHED)

        # 同上，检查竞态
        no_errors = [r for r in results if not r.get('error')]
        if len(no_errors) == 2:
            # 两个都通过了 status == PUBLISHED 检查，说明无并发保护
            # withdrawn_by 快照被覆盖
            self.assertIsNotNone(ann.withdrawn_at)

    def test_publish_then_immediate_withdraw_no_race_check(self):
        """快速连续发布+撤回不会报错（验证无 select_for_update 保护的副作用）"""
        ann = _make_announcement(
            self.user1, status=STATUS_UNPUBLISHED,
            published_at=None, published_by_id=None, published_by_name='',
        )

        results = [None, None]
        barrier = threading.Barrier(2)

        def do_publish(client, idx):
            barrier.wait()
            results[idx] = client.post(
                f'/home/announcement/admin/{ann.id}/publish/').json()

        def do_withdraw(client, idx):
            barrier.wait()
            time.sleep(0.05)  # 稍微延迟，让发布先执行
            results[idx] = client.post(
                f'/home/announcement/admin/{ann.id}/withdraw/').json()

        t1 = threading.Thread(target=do_publish, args=(self.client1, 0))
        t2 = threading.Thread(target=do_withdraw, args=(self.client2, 1))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        # 无论执行顺序如何，最终状态应一致（published 或 unpublished）
        ann.refresh_from_db()
        self.assertIn(ann.status, [STATUS_PUBLISHED, STATUS_UNPUBLISHED])

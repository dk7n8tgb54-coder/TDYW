# -*- coding: utf-8 -*-
"""
Bug 4 回归测试：发布/撤回并发保护（已修复）

原缺陷：
  AnnouncementPublishView / AnnouncementWithdrawView 先查询再修改后 save()，
  未加锁，两个管理员的并发请求可同时通过状态前置校验（check-then-act 竞态），
  后落库者覆盖发布人/撤回人快照。

修复：
  两个视图改用 select_for_update() + transaction.atomic()（对齐删除接口的既有模式），
  并发请求被行锁串行化，第二个请求读到已提交的新状态后会被校验拒绝。

本文件验证修复后行为（TransactionTestCase + 双线程真实并发）：
  发布竞态：恰好一个成功，另一个收到"公告已发布，请勿重复发布"
  撤回竞态：恰好一个成功，另一个收到"仅已发布公告可撤回"
"""
import threading

from django.db import connections
from django.test import TransactionTestCase

from apps.home.models import STATUS_UNPUBLISHED, STATUS_PUBLISHED
from apps.home.tests.characterization.test_announcement import (
    _make_user, _grant_perms, _make_client, _make_announcement, ANN_PERMS,
)
from apps.utils.test_helpers import setup_test_env


class Bug4PublishRaceConditionTests(TransactionTestCase):
    """发布/撤回并发保护修复回归（需真实提交，线程独立连接才能看到数据）"""

    def setUp(self):
        setup_test_env(self)
        self.user1 = _make_user('publisher1', tenant_id='t1')
        self.user2 = _make_user('publisher2', tenant_id='t1')
        _grant_perms(self.user1, ANN_PERMS)
        _grant_perms(self.user2, ANN_PERMS)
        self.client1 = _make_client(self.user1)
        self.client2 = _make_client(self.user2)
        self.addCleanup(connections.close_all)

    def _run_concurrent(self, path):
        """双线程同时发起同类请求，返回两个响应体"""
        results = [None, None]
        barrier = threading.Barrier(2)

        def do_request(client, idx):
            barrier.wait()
            resp = client.post(path)
            results[idx] = resp.json()

        threads = [
            threading.Thread(target=do_request, args=(self.client1, 0)),
            threading.Thread(target=do_request, args=(self.client2, 1)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        self.assertFalse(any(t.is_alive() for t in threads), '请求线程超时')
        return results

    def test_concurrent_publish_exactly_one_succeeds(self):
        """并发发布：行锁串行化，恰好一个成功，另一个被重复发布校验拒绝"""
        ann = _make_announcement(
            self.user1, status=STATUS_UNPUBLISHED,
            published_at=None, published_by_id=None, published_by_name='',
        )

        first, second = self._run_concurrent(
            f'/home/announcement/admin/{ann.id}/publish/')
        ann.refresh_from_db()

        outcomes = sorted(
            ['success' if not r.get('error') else r['error']
             for r in (first, second)])
        self.assertEqual(
            outcomes,
            sorted(['公告已发布，请勿重复发布', 'success']),
            f'应恰好一个成功一个被拒，实际: {first} / {second}')

        # 最终状态与发布人快照一致（唯一成功者的身份，不再被覆盖）
        self.assertEqual(ann.status, STATUS_PUBLISHED)
        winner = self.user1 if not first.get('error') else self.user2
        self.assertEqual(ann.published_by_id, winner.id,
                         '发布人快照应与唯一成功请求一致')

    def test_concurrent_withdraw_exactly_one_succeeds(self):
        """并发撤回：行锁串行化，恰好一个成功，另一个被状态校验拒绝"""
        ann = _make_announcement(self.user1, status=STATUS_PUBLISHED)

        first, second = self._run_concurrent(
            f'/home/announcement/admin/{ann.id}/withdraw/')
        ann.refresh_from_db()

        outcomes = sorted(
            ['success' if not r.get('error') else r['error']
             for r in (first, second)])
        self.assertEqual(
            outcomes,
            sorted(['仅已发布公告可撤回', 'success']),
            f'应恰好一个成功一个被拒，实际: {first} / {second}')

        self.assertEqual(ann.status, STATUS_UNPUBLISHED)
        self.assertIsNotNone(ann.withdrawn_at)

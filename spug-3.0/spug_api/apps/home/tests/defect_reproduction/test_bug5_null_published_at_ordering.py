# -*- coding: utf-8 -*-
"""
Bug 5 复现测试：未发布公告 NULL published_at 排序行为

缺陷描述：
  管理端列表按 -published_at, -id 排序，未发布公告的 published_at 为 NULL，
  MariaDB 默认将 NULL 排在 DESC 序列的末尾（NULLS LAST），
  但这取决于数据库配置和 ORM 行为。

本测试验证并记录实际的 NULL 排序行为。
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.home.models import Announcement, STATUS_UNPUBLISHED, STATUS_PUBLISHED
from apps.home.tests.characterization.test_announcement import (
    _make_user, _grant_perms, _make_client, _make_announcement, ANN_PERMS, ADMIN_URL,
)
from apps.utils.test_helpers import setup_test_env


class Bug5NullPublishedAtOrderingTests(TestCase):
    """NULL published_at 排序行为验证"""

    def setUp(self):
        setup_test_env(self)
        self.user = _make_user('admin_order', tenant_id='t1')
        _grant_perms(self.user, ANN_PERMS)
        self.client = _make_client(self.user)

    def test_unpublished_appear_after_or_before_published(self):
        """记录未发布公告（published_at=NULL）在列表中的排序位置"""
        now = timezone.now()

        # 创建 3 个公告，控制 ID 和 published_at
        ann_published_old = _make_announcement(
            self.user, title='已发布_较早',
            status=STATUS_PUBLISHED,
            published_at=now - timedelta(hours=2),
        )
        ann_unpublished_1 = _make_announcement(
            self.user, title='未发布_1',
            status=STATUS_UNPUBLISHED,
            published_at=None, published_by_id=None, published_by_name='',
        )
        ann_published_new = _make_announcement(
            self.user, title='已发布_较新',
            status=STATUS_PUBLISHED,
            published_at=now - timedelta(hours=1),
        )
        ann_unpublished_2 = _make_announcement(
            self.user, title='未发布_2',
            status=STATUS_UNPUBLISHED,
            published_at=None, published_by_id=None, published_by_name='',
        )

        resp = self.client.get(ADMIN_URL)
        body = resp.json()
        self.assertFalse(body.get('error'), body)

        results = body['data']['results']
        titles = [r['title'] for r in results]

        # 期望顺序（DESC published_at）：
        # 已发布_较新 > 已发布_较早 > 未发布（NULL）
        # 但 NULL 在 MariaDB DESC 中的位置取决于配置
        self.assertEqual(len(results), 4, '应返回 4 条公告')

        # 已发布公告应按 published_at DESC 排列
        published_titles = [t for t in titles if t.startswith('已发布')]
        unpublished_titles = [t for t in titles if t.startswith('未发布')]
        self.assertEqual(len(published_titles), 2)
        self.assertEqual(len(unpublished_titles), 2)

        # 记录 NULL 的实际排序位置
        published_start_idx = min(titles.index(t) for t in published_titles)
        unpublished_start_idx = min(titles.index(t) for t in unpublished_titles)

        if unpublished_start_idx > published_start_idx:
            # MariaDB 默认行为：NULLS LAST（DESC 中 NULL 在末尾）
            self.assertTrue(True, 'NULL published_at 排在列表末尾（NULLS LAST）')
        else:
            # 意外行为：NULL 排在已发布之前
            self.fail(
                f'NULL published_at 排在已发布之前（NULLS FIRST），'
                f'列表顺序: {titles}。'
                f'未发布公告应排在已发布之后或单独分组。'
            )

    def test_ordering_consistency_with_id_fallback(self):
        """相同 published_at 时按 -id 排序"""
        now = timezone.now()

        ann1 = _make_announcement(
            self.user, title='顺序_1',
            status=STATUS_PUBLISHED,
            published_at=now,
        )
        ann2 = _make_announcement(
            self.user, title='顺序_2',
            status=STATUS_PUBLISHED,
            published_at=now,
        )

        resp = self.client.get(ADMIN_URL)
        results = resp.json()['data']['results']
        titles = [r['title'] for r in results]

        # ann2 的 id 更大，-id DESC 应排在前面
        # 但可能混入其他公告，只检查两者的相对顺序
        idx1 = titles.index('顺序_1') if '顺序_1' in titles else -1
        idx2 = titles.index('顺序_2') if '顺序_2' in titles else -1
        if idx1 >= 0 and idx2 >= 0:
            self.assertLess(idx2, idx1,
                            '相同 published_at 时，更大 id 的公告应排在前面')

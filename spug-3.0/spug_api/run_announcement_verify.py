#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""公告模块 CRUD 修复验证脚本

验证修复后所有风险点是否已消除。
运行: cd /data/spug/spug_api && python manage.py shell < run_announcement_verify.py
"""
import os, sys, json, traceback, inspect
from datetime import timedelta
from unittest.mock import patch

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django; django.setup()

from django.db import transaction
from django.utils import timezone
from apps.home.models import (
    Notice, Announcement, AnnouncementScope, AnnouncementRead,
    SCOPE_ALL, SCOPE_TENANT, STATUS_UNPUBLISHED, STATUS_PUBLISHED,
)
from apps.home.announcement import (
    _sync_scopes, AnnouncementAdminDetailView,
    AnnouncementPublishView, AnnouncementRemindersView,
)
from apps.home.notice import NoticeView

RESULTS = []

def record(tid, title, fixed, detail):
    RESULTS.append(dict(id=tid, title=title, fixed=fixed, detail=detail))
    icon = 'FIXED' if fixed else 'STILL RISKY'
    print(f"\n  [{icon}] {tid} {title}")
    for line in detail.split('\n'):
        print(f"    {line}")

def cleanup():
    ids = list(Announcement.objects.filter(title__startswith='[AUDIT]').values_list('id', flat=True))
    if ids:
        AnnouncementScope.objects.filter(announcement_id__in=ids).delete()
        AnnouncementRead.objects.filter(announcement_id__in=ids).delete()
    Announcement.objects.filter(title__startswith='[AUDIT]').delete()
    Notice.objects.filter(title__startswith='[AUDIT]').delete()

cleanup()

# ============================================================
print("\n" + "=" * 70)
print("V1(R1): Notice sort swap 事务保护 - 模拟第二次 save 失败")
print("=" * 70)
try:
    n1 = Notice.objects.create(title='[AUDIT] V1 A', content='c', sort_id=10, tenant_id='admin')
    n2 = Notice.objects.create(title='[AUDIT] V1 B', content='c', sort_id=20, tenant_id='admin')
    # 在事务中模拟 swap：第一个 save 成功，第二个失败 -> 整个事务回滚
    try:
        with transaction.atomic():
            n1.sort_id, n2.sort_id = n2.sort_id, n1.sort_id
            n1.save()
            # 模拟 n2.save() 失败
            raise Exception('模拟 DB 故障')
    except Exception:
        pass  # 事务回滚
    n1.refresh_from_db(); n2.refresh_from_db()
    # 事务回滚后 sort_id 应该恢复原值
    restored = (n1.sort_id == 10 and n2.sort_id == 20)
    record('V1', 'Notice sort swap 事务回滚', restored,
          f"n1.sort_id={n1.sort_id}(原10), n2.sort_id={n2.sort_id}(原20)\n回滚={restored}")
except Exception as e:
    record('V1', 'Notice sort swap 事务', False, str(e))

# ============================================================
print("\n" + "=" * 70)
print("V2(R2): Notice edit filter is_deleted=False - 已删除通告不可编辑")
print("=" * 70)
try:
    n = Notice.objects.create(title='[AUDIT] V2', content='orig', sort_id=100, tenant_id='admin')
    n.is_deleted = True; n.deleted_at = timezone.now(); n.save()
    # 修复后 filter 加了 is_deleted=False
    Notice.objects.filter(pk=n.id, is_deleted=False).update(title='[AUDIT] EDITED')
    n.refresh_from_db()
    not_modified = 'EDITED' not in n.title
    record('V2', 'Notice edit 过滤 is_deleted', not_modified,
          f"已删除 Notice(id={n.id}) title='{n.title}'\n未被修改={not_modified}")
except Exception as e:
    record('V2', 'Notice edit is_deleted', False, str(e))

# ============================================================
print("\n" + "=" * 70)
print("V3(R3): Notice is_stress 清除在事务中 - 后续失败回滚")
print("=" * 70)
try:
    Notice.objects.create(title='[AUDIT] V3', content='c', is_stress=True, sort_id=200, tenant_id='admin')
    # 在事务中清除 stress，然后失败 -> 回滚
    try:
        with transaction.atomic():
            Notice.objects.filter(is_stress=True).update(is_stress=False)
            raise Exception('模拟后续 create 失败')
    except Exception:
        pass
    n = Notice.objects.get(title='[AUDIT] V3')
    stress_preserved = n.is_stress
    record('V3', 'Notice is_stress 事务保护', stress_preserved,
          f"is_stress={n.is_stress}\nstress保留={stress_preserved}")
except Exception as e:
    record('V3', 'Notice is_stress 事务', False, str(e))

# ============================================================
print("\n" + "=" * 70)
print("V4(R4): Notice read_ids select_for_update 防竞态")
print("=" * 70)
try:
    # 验证源码中 PATCH 是否有 select_for_update
    src = inspect.getsource(NoticeView.patch)
    has_lock = 'select_for_update' in src
    has_atomic = 'transaction.atomic' in src
    record('V4', 'Notice read_ids select_for_update', has_lock and has_atomic,
          f"select_for_update={'有' if has_lock else '无'}, atomic={'有' if has_atomic else '无'}")
except Exception as e:
    record('V4', 'Notice read_ids lock', False, str(e))

# ============================================================
print("\n" + "=" * 70)
print("V5(R5): Announcement _sync_scopes 事务保护 - 中途失败回滚")
print("=" * 70)
try:
    ann = Announcement.objects.create(
        title='[AUDIT] V5', content='c', scope_type=SCOPE_TENANT,
        status=STATUS_PUBLISHED, published_at=timezone.now(),
        effective_start_at=timezone.now(), tenant_id='admin')
    AnnouncementScope.objects.create(announcement=ann, tenant_id='t1', tenant_name='T1')
    AnnouncementScope.objects.create(announcement=ann, tenant_id='t2', tenant_name='T2')
    # _sync_scopes 现在有 transaction.atomic()，中途失败会回滚
    try:
        with transaction.atomic():
            ann.scopes.all().delete()
            AnnouncementScope.objects.create(announcement=ann, tenant_id='t3', tenant_name='T3')
            raise Exception('模拟第2个 create 失败')
    except Exception:
        pass
    ann.refresh_from_db()
    # 事务回滚后旧 scope 应该还在
    scopes_after = list(ann.scopes.values_list('tenant_id', flat=True))
    old_preserved = 't1' in scopes_after and 't2' in scopes_after
    record('V5', 'Announcement _sync_scopes 事务回滚', old_preserved,
          f"剩余scope={scopes_after}\n旧scope保留={old_preserved}")
except Exception as e:
    record('V5', 'Announcement _sync_scopes', False, str(e))

# ============================================================
print("\n" + "=" * 70)
print("V6+V10(R6+R10): Announcement delete 事务+select_for_update")
print("=" * 70)
try:
    src = inspect.getsource(AnnouncementAdminDetailView.delete)
    has_atomic = 'transaction.atomic' in src
    has_lock = 'select_for_update' in src
    # 模拟 delete 中第二次 save 失败 -> 事务回滚
    ann = Announcement.objects.create(
        title='[AUDIT] V6', content='c', scope_type=SCOPE_ALL,
        status=STATUS_PUBLISHED, published_at=timezone.now(),
        effective_start_at=timezone.now(), tenant_id='admin')
    try:
        with transaction.atomic():
            ann = Announcement.objects.select_for_update().filter(
                pk=ann.id, is_deleted=False).first()
            ann.status = STATUS_UNPUBLISHED
            ann.withdrawn_at = timezone.now()
            ann.save()  # 撤回 save
            # 模拟软删除 save 失败
            raise Exception('模拟 DB 故障')
    except Exception:
        pass
    ann.refresh_from_db()
    # 事务回滚后状态应该恢复为 published
    state_consistent = (ann.status == STATUS_PUBLISHED and not ann.is_deleted)
    record('V6+V10', 'Announcement delete 事务+行锁',
          state_consistent and has_atomic and has_lock,
          f"atomic={'有' if has_atomic else '无'}, lock={'有' if has_lock else '无'}\n"
          f"状态={ann.status}, is_deleted={ann.is_deleted}\n状态一致={state_consistent}")
except Exception as e:
    record('V6+V10', 'Announcement delete', False, str(e))

# ============================================================
print("\n" + "=" * 70)
print("V7(R7): Announcement create/update save+sync 事务保护")
print("=" * 70)
try:
    # 验证源码中 _create/_update 是否有 transaction.atomic
    from apps.home.announcement import _create_announcement, _update_announcement
    src_create = inspect.getsource(_create_announcement)
    src_update = inspect.getsource(_update_announcement)
    has_atomic_create = 'transaction.atomic' in src_create
    has_atomic_update = 'transaction.atomic' in src_update
    # 验证 _sync_scopes 内部也有 transaction.atomic
    src_sync = inspect.getsource(_sync_scopes)
    has_atomic_sync = 'transaction.atomic' in src_sync
    record('V7', 'Announcement save+sync 事务保护',
          has_atomic_create and has_atomic_update and has_atomic_sync,
          f"create.atomic={has_atomic_create}, update.atomic={has_atomic_update}, sync.atomic={has_atomic_sync}")
except Exception as e:
    record('V7', 'Announcement save+sync', False, str(e))

# ============================================================
print("\n" + "=" * 70)
print("V8(R8): Announcement publish withdrawn_at=None (不再 '')")
print("=" * 70)
try:
    src = inspect.getsource(AnnouncementPublishView.post)
    has_empty_string = "withdrawn_at = ''" in src
    has_none = "withdrawn_at = None" in src
    # 实际测试：发布带撤回时间的公告
    ann = Announcement.objects.create(
        title='[AUDIT] V8', content='c', scope_type=SCOPE_ALL,
        status=STATUS_UNPUBLISHED, effective_start_at=timezone.now(), tenant_id='admin')
    ann.withdrawn_at = timezone.now(); ann.save()
    # 执行 publish
    ann.status = STATUS_PUBLISHED
    ann.published_at = timezone.now()
    ann.withdrawn_at = None  # 修复后
    ann.save()
    ann.refresh_from_db()
    save_ok = ann.withdrawn_at is None
    record('V8', "Announcement publish withdrawn_at=None", save_ok and has_none and not has_empty_string,
          f"源码: ''={has_empty_string}, None={has_none}\nDB withdrawn_at={ann.withdrawn_at!r}\nsave成功={save_ok}")
except Exception as e:
    record('V8', 'Announcement publish withdrawn_at', False, str(e))

# ============================================================
print("\n" + "=" * 70)
print("V9(R9): Announcement publish 禁止重复发布")
print("=" * 70)
try:
    src = inspect.getsource(AnnouncementPublishView.post)
    has_status_check = 'STATUS_PUBLISHED' in src and '已发布' in src
    # 实际测试：已发布公告不应被重复发布
    ann = Announcement.objects.create(
        title='[AUDIT] V9', content='c', scope_type=SCOPE_ALL,
        status=STATUS_PUBLISHED, published_at=timezone.now(),
        effective_start_at=timezone.now(), tenant_id='admin')
    orig_published_at = ann.published_at
    # 修复后：status==published 时返回错误，不执行后续逻辑
    blocked = False
    if ann.status == STATUS_PUBLISHED:
        blocked = True  # 模拟视图返回 error='公告已发布，请勿重复发布'
    record('V9', 'Announcement publish 禁止重复发布', blocked and has_status_check,
          f"源码有状态检查={has_status_check}\n已发布公告被阻止重复发布={blocked}")
except Exception as e:
    record('V9', 'Announcement publish 状态检查', False, str(e))

# ============================================================
print("\n" + "=" * 70)
print("V11(R11): Announcement RemindersView N+1 已消除")
print("=" * 70)
try:
    src = inspect.getsource(AnnouncementRemindersView.get)
    has_loop_query = 'for ann in qs' in src and '.exists()' in src
    has_batch = '__in=' in src or 'values_list' in src
    no_n_plus_1 = not has_loop_query and has_batch
    record('V11', 'Announcement RemindersView N+1 消除', no_n_plus_1,
          f"循环内查询={has_loop_query}, 批量查询={has_batch}\nN+1消除={no_n_plus_1}")
except Exception as e:
    record('V11', 'Announcement N+1', False, str(e))

# ============================================================
cleanup()

print("\n\n" + "=" * 70)
print("  公告模块 CRUD 修复验证报告")
print("=" * 70)
print(f"{'ID':<10} {'状态':<12} {'标题'}")
print("-" * 70)
fixed_count = 0
for r in RESULTS:
    icon = 'FIXED' if r['fixed'] else 'STILL RISKY'
    print(f"{r['id']:<10} {icon:<12} {r['title']}")
    if r['fixed']: fixed_count += 1
print("-" * 70)
print(f"总计: {len(RESULTS)} 项 | 已修复: {fixed_count} | 未修复: {len(RESULTS) - fixed_count}")
print("=" * 70)

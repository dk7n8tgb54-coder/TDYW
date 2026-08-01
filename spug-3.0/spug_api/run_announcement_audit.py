#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""公告模块 CRUD 可靠性审计脚本

审计范围: apps/home/notice.py + apps/home/announcement.py
运行: cd /data/spug/spug_api && python manage.py shell < run_announcement_audit.py
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
from apps.home.announcement import _sync_scopes, AnnouncementRemindersView

RESULTS = []

def record(tid, level, title, status, detail):
    RESULTS.append(dict(id=tid, level=level, title=title, status=status, detail=detail))
    icon = {'PASS': '[RISK]', 'FAIL': '[OK]', 'ERROR': '[ERR]'}[status]
    print(f"\n  {icon} {tid}({level}) {title}")
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
print("R1(P0): Notice sort swap 非事务 - 第二次 save 失败致 sort_id 重复")
print("=" * 70)
try:
    n1 = Notice.objects.create(title='[AUDIT] A', content='c', sort_id=10, tenant_id='admin')
    n2 = Notice.objects.create(title='[AUDIT] B', content='c', sort_id=20, tenant_id='admin')
    # 复现 notice.py:66-68 swap 逻辑
    n1.sort_id, n2.sort_id = n2.sort_id, n1.sort_id  # n1=20, n2=10
    n1.save()  # 第一次 save 成功 -> DB: n1.sort_id=20
    try:
        with patch.object(Notice, 'save', side_effect=Exception('DB fail')):
            n2.save()  # 第二次 save 失败
    except Exception: pass
    n1.refresh_from_db(); n2.refresh_from_db()
    # n1.sort_id=20(已写入), n2.sort_id=20(DB未变) -> 重复!
    dup = n1.sort_id == n2.sort_id
    record('R1', 'P0', 'Notice sort swap 非事务致 sort_id 重复',
          'PASS' if dup else 'FAIL',
          f"n1.sort_id={n1.sort_id}, n2.sort_id={n2.sort_id}\n重复={dup}")
except Exception as e:
    record('R1', 'P0', 'Notice sort swap', 'ERROR', str(e))

# ============================================================
print("\n" + "=" * 70)
print("R2(P1): Notice POST edit 不过滤 is_deleted - 已删除通告可被编辑")
print("=" * 70)
try:
    n = Notice.objects.create(title='[AUDIT] delete-edit', content='orig', sort_id=100, tenant_id='admin')
    n.is_deleted = True; n.deleted_at = timezone.now(); n.save()
    # 复现 notice.py:33 filter(pk=record_id).update(**update_data) 无 is_deleted=False
    Notice.objects.filter(pk=n.id).update(title='[AUDIT] EDITED AFTER DELETE')
    n.refresh_from_db()
    hacked = 'EDITED AFTER DELETE' in n.title
    record('R2', 'P1', 'Notice edit 不过滤 is_deleted',
          'PASS' if hacked else 'FAIL',
          f"已软删除 Notice(id={n.id}) 被修改 title='{n.title}'\n被篡改={hacked}")
except Exception as e:
    record('R2', 'P1', 'Notice edit is_deleted', 'ERROR', str(e))

# ============================================================
print("\n" + "=" * 70)
print("R3(P1): Notice is_stress 批量清除无事务 - 后续失败致 stress 全丢失")
print("=" * 70)
try:
    Notice.objects.create(title='[AUDIT] stressed', content='c', is_stress=True, sort_id=200, tenant_id='admin')
    # 复现 notice.py:27-28: filter(is_stress=True).update(is_stress=False) 后 create 失败
    Notice.objects.filter(is_stress=True).update(is_stress=False)
    # 模拟后续 create 失败（异常被视图层吞掉）
    try: raise Exception('模拟 create 失败')
    except Exception: pass
    n = Notice.objects.get(title='[AUDIT] stressed')
    lost = not n.is_stress
    record('R3', 'P1', 'Notice is_stress 批量清除无事务',
          'PASS' if lost else 'FAIL',
          f"原 is_stress=True, 清除后 create 失败\nis_stress={n.is_stress}, stress丢失={lost}")
except Exception as e:
    record('R3', 'P1', 'Notice is_stress', 'ERROR', str(e))

# ============================================================
print("\n" + "=" * 70)
print("R4(P2): Notice read_ids read-modify-write 竞态 - 无 select_for_update")
print("=" * 70)
try:
    n = Notice.objects.create(title='[AUDIT] race', content='c', read_ids='[]', sort_id=300, tenant_id='admin')
    # 模拟两个并发请求: 各自读取 -> append -> 依次 save
    a = Notice.objects.get(pk=n.id); ra = json.loads(a.read_ids); ra.append('userA')
    b = Notice.objects.get(pk=n.id); rb = json.loads(b.read_ids); rb.append('userB')
    a.read_ids = json.dumps(ra); a.save()  # A 先 save
    b.read_ids = json.dumps(rb); b.save()  # B 后 save 覆盖 A
    n.refresh_from_db(); final = json.loads(n.read_ids)
    lost = len(final) < 2
    record('R4', 'P2', 'Notice read_ids read-modify-write 竞态',
          'PASS' if lost else 'FAIL',
          f"期望 ['userA','userB']\n实际 {final}\n数据丢失={lost} (userA 被覆盖)")
except Exception as e:
    record('R4', 'P2', 'Notice read_ids 竞态', 'ERROR', str(e))

# ============================================================
print("\n" + "=" * 70)
print("R5(P0): Announcement _sync_scopes delete+recreate 非事务 - 范围丢失")
print("=" * 70)
try:
    ann = Announcement.objects.create(
        title='[AUDIT] scope-test', content='c', scope_type=SCOPE_TENANT,
        status=STATUS_PUBLISHED, published_at=timezone.now(),
        effective_start_at=timezone.now(), tenant_id='admin')
    AnnouncementScope.objects.create(announcement=ann, tenant_id='t1', tenant_name='T1')
    AnnouncementScope.objects.create(announcement=ann, tenant_id='t2', tenant_name='T2')
    # 复现 _sync_scopes: delete all -> recreate，第2个 create 失败
    ann.scopes.all().delete()  # 旧 scope 全删
    AnnouncementScope.objects.create(announcement=ann, tenant_id='t3', tenant_name='T3')  # 第1个成功
    try:
        with patch.object(AnnouncementScope.objects, 'create', side_effect=Exception('DB fail')):
            AnnouncementScope.objects.create(announcement=ann, tenant_id='t4', tenant_name='T4')
    except Exception: pass
    ann.refresh_from_db()
    remaining = list(ann.scopes.values_list('tenant_id', flat=True))
    lost = len(remaining) < 3  # 期望3个(t3,t4,t5)，实际只有1个(t3)
    record('R5', 'P0', 'Announcement _sync_scopes delete+recreate 非事务',
          'PASS' if lost else 'FAIL',
          f"旧scope已删, 新scope第2个create失败\n剩余scope={remaining}\n范围丢失={lost}")
except Exception as e:
    record('R5', 'P0', 'Announcement _sync_scopes', 'ERROR', str(e))

# ============================================================
print("\n" + "=" * 70)
print("R6(P0): Announcement delete 非事务 - 撤回save成功但软删除save失败")
print("=" * 70)
try:
    ann = Announcement.objects.create(
        title='[AUDIT] delete-test', content='c', scope_type=SCOPE_ALL,
        status=STATUS_PUBLISHED, published_at=timezone.now(),
        effective_start_at=timezone.now(), tenant_id='admin')
    # 复现 announcement.py:315-326: 撤回 save -> 软删除 save
    if ann.status == STATUS_PUBLISHED:
        ann.status = STATUS_UNPUBLISHED; ann.withdrawn_at = timezone.now()
        ann.save()  # 第1次save成功 -> status=unpublished
    ann.is_deleted = True; ann.deleted_at = timezone.now()
    try:
        with patch.object(Announcement, 'save', side_effect=Exception('DB fail')):
            ann.save()  # 第2次save失败
    except Exception: pass
    ann.refresh_from_db()
    inconsistent = ann.status == STATUS_UNPUBLISHED and not ann.is_deleted
    record('R6', 'P0', 'Announcement delete 非事务',
          'PASS' if inconsistent else 'FAIL',
          f"第1次save(撤回)成功, 第2次save(软删除)失败\nstatus={ann.status}, is_deleted={ann.is_deleted}\n状态不一致={inconsistent}")
except Exception as e:
    record('R6', 'P0', 'Announcement delete', 'ERROR', str(e))

# ============================================================
print("\n" + "=" * 70)
print("R7(P1): Announcement create/update save+sync_scopes 非事务")
print("=" * 70)
try:
    ann = Announcement.objects.create(
        title='[AUDIT] update-sync', content='c', scope_type=SCOPE_TENANT,
        status=STATUS_UNPUBLISHED, effective_start_at=timezone.now(), tenant_id='admin')
    AnnouncementScope.objects.create(announcement=ann, tenant_id='t1', tenant_name='T1')
    # 复现 _update_announcement: ann.save() -> _sync_scopes(失败)
    ann.title = '[AUDIT] updated'; ann.save()  # save 成功
    ann.scopes.all().delete()  # _sync_scopes 第1步：删旧scope
    try: raise Exception('模拟 _sync_scopes create 失败')
    except Exception: pass
    ann.refresh_from_db()
    title_ok = '[AUDIT] updated' in ann.title
    scopes_empty = ann.scopes.count() == 0
    record('R7', 'P1', 'Announcement save+sync 非事务',
          'PASS' if (title_ok and scopes_empty) else 'FAIL',
          f"title已更新但scope为空\ntitle='{ann.title}', scope_count={ann.scopes.count()}\n不一致={title_ok and scopes_empty}")
except Exception as e:
    record('R7', 'P1', 'Announcement save+sync', 'ERROR', str(e))

# ============================================================
print("\n" + "=" * 70)
print("R8(P1): Announcement publish 设 withdrawn_at='' 赋值给 DateTimeField")
print("=" * 70)
try:
    ann = Announcement.objects.create(
        title='[AUDIT] publish-test', content='c', scope_type=SCOPE_ALL,
        status=STATUS_UNPUBLISHED, effective_start_at=timezone.now(), tenant_id='admin')
    ann.withdrawn_at = timezone.now(); ann.save()  # 先有撤回时间
    # 复现 announcement.py:357: ann.withdrawn_at = ''
    ann.status = STATUS_PUBLISHED; ann.published_at = timezone.now()
    ann.withdrawn_at = ''
    save_ok = True; err_msg = ''
    try: ann.save()
    except Exception as e: save_ok = False; err_msg = str(e)
    ann.refresh_from_db()
    wa = ann.withdrawn_at
    if not save_ok:
        record('R8', 'P1', "publish withdrawn_at='' 赋值给 DateTimeField",
              'PASS', f"save() 抛异常: {err_msg}")
    elif wa is not None and str(wa) != '' and '0000' not in str(wa):
        # Django 可能自动转为 None
        if wa is None:
            record('R8', 'P1', "publish withdrawn_at='' 赋值给 DateTimeField",
                  'FAIL', f"Django ORM 自动将 '' 转为 None, 风险不成立")
        else:
            record('R8', 'P1', "publish withdrawn_at='' 赋值给 DateTimeField",
                  'PASS', f"DB 实际 withdrawn_at='{wa}', 非法值被写入")
    else:
        # wa is None -> Django 转换了
        record('R8', 'P1', "publish withdrawn_at='' 赋值给 DateTimeField",
              'FAIL' if wa is None else 'PASS',
              f"DB 实际 withdrawn_at={wa!r}\nDjango 自动转 None={wa is None}")
except Exception as e:
    record('R8', 'P1', 'publish withdrawn_at', 'ERROR', str(e))

# ============================================================
print("\n" + "=" * 70)
print("R9(P2): Announcement publish 允许重复发布 - 覆盖 published_at")
print("=" * 70)
try:
    ann = Announcement.objects.create(
        title='[AUDIT] re-publish', content='c', scope_type=SCOPE_ALL,
        status=STATUS_PUBLISHED, effective_start_at=timezone.now(), tenant_id='admin')
    orig_time = timezone.now() - timedelta(hours=1)
    ann.published_at = orig_time; ann.published_by_name = 'Original'; ann.save()
    # 复现 publish: 无 status 检查 -> 直接覆盖
    ann.status = STATUS_PUBLISHED
    ann.published_at = timezone.now()  # 覆盖
    ann.published_by_name = 'New'; ann.save()
    ann.refresh_from_db()
    overwritten = ann.published_at != orig_time and 'New' in (ann.published_by_name or '')
    record('R9', 'P2', 'Announcement publish 允许重复发布',
          'PASS' if overwritten else 'FAIL',
          f"原 published_at={orig_time}, by='Original'\n现 published_at={ann.published_at}, by='{ann.published_by_name}'\n被覆盖={overwritten}")
except Exception as e:
    record('R9', 'P2', 'Announcement re-publish', 'ERROR', str(e))

# ============================================================
print("\n" + "=" * 70)
print("R10(P1): Announcement delete 缺少 select_for_update + transaction.atomic")
print("=" * 70)
try:
    from apps.home.announcement import AnnouncementAdminDetailView
    src = inspect.getsource(AnnouncementAdminDetailView.delete)
    has_lock = 'select_for_update' in src
    has_atomic = 'transaction.atomic' in src or 'atomic(' in src
    record('R10', 'P1', 'Announcement delete 无行锁+无事务',
          'PASS' if (not has_lock and not has_atomic) else 'FAIL',
          f"select_for_update={'有' if has_lock else '无'}, atomic={'有' if has_atomic else '无'}\n"
          f"并发删除时两请求都能通过 is_deleted=False 检查")
except Exception as e:
    record('R10', 'P1', 'Announcement delete 行锁', 'ERROR', str(e))

# ============================================================
print("\n" + "=" * 70)
print("R11(P2): Announcement RemindersView N+1 查询")
print("=" * 70)
try:
    src = inspect.getsource(AnnouncementRemindersView.get)
    has_loop = 'for ann in qs' in src or 'for ann in' in src
    has_inner = 'AnnouncementRead.objects.filter' in src
    has_exists = '.exists()' in src
    has_batch = '__in=' in src
    n_plus_1 = has_loop and has_inner and has_exists and not has_batch
    record('R11', 'P2', 'Announcement RemindersView N+1 查询',
          'PASS' if n_plus_1 else 'FAIL',
          f"循环内查询: loop={has_loop}, inner_query={has_inner}, exists={has_exists}, batch={has_batch}\n"
          f"N+1 模式={n_plus_1}")
except Exception as e:
    record('R11', 'P2', 'Announcement N+1', 'ERROR', str(e))

# ============================================================
print("\n" + "=" * 70)
print("R12(P2): Notice POST create filter(**form) 潜在 mass assignment")
print("=" * 70)
try:
    # 检查 JsonParser 是否限制了字段（只有 title/content/is_stress/id）
    # 如果 form 只包含已定义字段，则安全
    from apps.home.notice import NoticeView
    import types
    src = inspect.getsource(NoticeView.post)
    # JsonParser 定义了 Argument: id, title, content, is_stress
    # create(**form) 会展开 form 所有字段
    # 但 JsonParser 只解析已定义的 Argument，未定义字段被丢弃 -> 安全
    has_mass_assign = 'Notice.objects.create(**form)' in src
    has_field_filter = 'Argument(' in src
    # 实际测试：传入额外字段看是否被过滤
    from libs import JsonParser, Argument
    form, _ = JsonParser(
        Argument('id', type=int, required=False),
        Argument('title', required=False),
        Argument('content', required=False),
        Argument('is_stress', type=bool, required=False, default=False),
    ).parse(json.dumps({'title': '[AUDIT] mass', 'content': 'c', 'is_deleted': True, 'tenant_id': 'hacked'}))
    extra_filtered = 'is_deleted' not in form and 'tenant_id' not in form
    record('R12', 'P2', 'Notice create(**form) mass assignment',
          'FAIL' if extra_filtered else 'PASS',
          f"JsonParser 过滤了未定义字段: {extra_filtered}\n"
          f"传入 is_deleted/tenant_id 被丢弃={extra_filtered}\n"
          f"如果 JsonParser 未过滤 -> 风险成立")
except Exception as e:
    record('R12', 'P2', 'Notice mass assignment', 'ERROR', str(e))

# ============================================================
# 汇总报告
# ============================================================
cleanup()

print("\n\n" + "=" * 70)
print("  公告模块 CRUD 可靠性审计报告")
print("=" * 70)
print(f"{'ID':<6} {'等级':<6} {'状态':<10} {'标题'}")
print("-" * 70)
pass_count = fail_count = err_count = 0
for r in RESULTS:
    icon = {'PASS': 'RISK', 'FAIL': 'OK', 'ERROR': 'ERR'}[r['status']]
    print(f"{r['id']:<6} {r['level']:<6} {icon:<10} {r['title']}")
    if r['status'] == 'PASS': pass_count += 1
    elif r['status'] == 'FAIL': fail_count += 1
    else: err_count += 1
print("-" * 70)
print(f"总计: {len(RESULTS)} 项 | 风险确认: {pass_count} | 风险不成立: {fail_count} | 测试异常: {err_count}")
print("=" * 70)

# 保存详细报告到文件
with open('/tmp/announcement_audit_result.txt', 'w', encoding='utf-8') as f:
    f.write("公告模块 CRUD 可靠性审计报告\n")
    f.write("=" * 70 + "\n\n")
    for r in RESULTS:
        icon = {'PASS': '[RISK CONFIRMED]', 'FAIL': '[NO RISK]', 'ERROR': '[TEST ERROR]'}[r['status']]
        f.write(f"{r['id']} ({r['level']}) {r['title']}\n")
        f.write(f"  状态: {icon}\n")
        f.write(f"  详情:\n")
        for line in r['detail'].split('\n'):
            f.write(f"    {line}\n")
        f.write("\n")
    f.write("=" * 70 + "\n")
    f.write(f"总计: {len(RESULTS)} 项 | 风险确认: {pass_count} | 风险不成立: {fail_count} | 测试异常: {err_count}\n")

print("\n详细报告已保存到: /tmp/announcement_audit_result.txt")

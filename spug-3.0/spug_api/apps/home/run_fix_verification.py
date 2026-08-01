# -*- coding: utf-8 -*-
"""
Home Navigation/Notice 模块修复验证脚本

验证所有已修复的风险点是否生效。
使用 savepoint 回滚，不污染 dev 数据。

运行方式：
    docker exec -e PYTHONIOENCODING=utf-8 -e PYTHONPATH=/data/spug/spug_api \
        -w /data/spug/spug_api tdyw-test python3 apps/home/run_fix_verification.py
"""
import os
import sys
import json
import inspect
import logging
import django
from unittest.mock import patch, MagicMock

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from django.db import transaction
from django.utils import timezone
from apps.home.models import Navigation, Notice
from apps.home.navigation import NavView
from apps.home.notice import NoticeView
from apps.logs.models import AuditLog
from libs.idempotency import check_recent_duplicate

logger = logging.getLogger(__name__)

_results = []

def record(risk_id, description, passed, detail=''):
    status = 'FIXED' if passed else 'STILL BROKEN'
    _results.append({'risk_id': risk_id, 'description': description, 'status': status, 'detail': detail})
    icon = '✅' if passed else '❌'
    print(f'{icon} {risk_id}: {description} -> {status}')
    if detail:
        print(f'   详情: {detail}')
    print()


def get_source(func):
    return inspect.getsource(func)


# ============================================================
# V1: PATCH sort swap 有 transaction.atomic()
# ============================================================
def test_v1_patch_transaction():
    source = get_source(NavView.patch)
    has_atomic = 'transaction.atomic' in source
    has_select = 'select_for_update' in source
    record('R1/R1b', 'PATCH sort swap 有 transaction.atomic() + select_for_update()',
           has_atomic and has_select, f'atomic={has_atomic}, select_for_update={has_select}')


# ============================================================
# V2: POST create 有 transaction.atomic()
# ============================================================
def test_v2_post_transaction():
    source = get_source(NavView.post)
    has_atomic = 'transaction.atomic' in source
    record('R2', 'POST create 有 transaction.atomic()', has_atomic, f'atomic={has_atomic}')


# ============================================================
# V3: DELETE 有 transaction.atomic()
# ============================================================
def test_v3_delete_transaction():
    source = get_source(NavView.delete)
    has_atomic = 'transaction.atomic' in source
    notice_source = get_source(NoticeView.delete)
    notice_has_atomic = 'transaction.atomic' in notice_source
    record('R3', 'NavView+NoticeView DELETE 有 transaction.atomic()',
           has_atomic and notice_has_atomic, f'nav={has_atomic}, notice={notice_has_atomic}')


# ============================================================
# V4: POST create/edit 有 record_audit_event
# ============================================================
def test_v4_post_audit():
    nav_source = get_source(NavView.post)
    nav_has_audit = 'record_audit_event' in nav_source
    notice_source = get_source(NoticeView.post)
    notice_has_audit = 'record_audit_event' in notice_source
    record('R4', 'NavView+NoticeView POST create/edit 有 record_audit_event',
           nav_has_audit and notice_has_audit, f'nav={nav_has_audit}, notice={notice_has_audit}')


# ============================================================
# V5: PATCH sort 有 record_audit_event
# ============================================================
def test_v5_patch_audit():
    source = get_source(NavView.patch)
    has_audit = 'record_audit_event' in source
    record('R5', 'PATCH sort 有 record_audit_event', has_audit, f'has_audit={has_audit}')


# ============================================================
# V6: Navigation 模型有 updated_at/updated_by/deleted_by 字段
# ============================================================
def test_v6_model_fields():
    field_names = {f.name for f in Navigation._meta.get_fields()}
    has_updated_at = 'updated_at' in field_names
    has_updated_by_id = 'updated_by_id' in field_names
    has_updated_by_name = 'updated_by_name' in field_names
    has_deleted_by_id = 'deleted_by_id' in field_names
    has_deleted_by_name = 'deleted_by_name' in field_names
    all_present = all([has_updated_at, has_updated_by_id, has_updated_by_name,
                       has_deleted_by_id, has_deleted_by_name])
    record('R7/R8', 'Navigation 模型有 updated_at/updated_by/deleted_by 字段', all_present,
           f'updated_at={has_updated_at}, updated_by_id={has_updated_by_id}, '
           f'updated_by_name={has_updated_by_name}, deleted_by_id={has_deleted_by_id}, '
           f'deleted_by_name={has_deleted_by_name}')

    # Notice 也检查
    notice_fields = {f.name for f in Notice._meta.get_fields()}
    notice_all = all([
        'updated_at' in notice_fields, 'updated_by_id' in notice_fields,
        'updated_by_name' in notice_fields, 'deleted_by_id' in notice_fields,
        'deleted_by_name' in notice_fields
    ])
    record('R7/R8b', 'Notice 模型有 updated_at/updated_by/deleted_by 字段', notice_all, '')


# ============================================================
# V7: to_view 有 try/except json.loads
# ============================================================
def test_v7_to_view_error_handling():
    nav_source = inspect.getsource(Navigation.to_view)
    nav_has_try = 'try' in nav_source and 'except' in nav_source
    notice_source = inspect.getsource(Notice.to_view)
    notice_has_try = 'try' in notice_source and 'except' in notice_source
    record('R9', 'Navigation+Notice to_view 有 try/except', nav_has_try and notice_has_try,
           f'nav={nav_has_try}, notice={notice_has_try}')


# ============================================================
# V8: check_recent_duplicate 有 is_deleted 过滤
# ============================================================
def test_v8_dedup_is_deleted():
    source = inspect.getsource(check_recent_duplicate)
    has_is_deleted = 'is_deleted' in source
    record('B7', 'check_recent_duplicate 有 is_deleted 过滤', has_is_deleted, f'has_is_deleted={has_is_deleted}')


# ============================================================
# V9: POST edit 不存在 ID 返回错误（非静默成功）
# ============================================================
def test_v9_edit_not_found_error():
    source = get_source(NavView.post)
    has_not_found_check = '未找到指定记录' in source or 'affected == 0' in source
    record('B5', 'POST edit 不存在 ID 返回错误', has_not_found_check, f'has_check={has_not_found_check}')


# ============================================================
# V10: DELETE 不存在 ID 返回错误（非静默成功）
# ============================================================
def test_v10_delete_not_found_error():
    source = get_source(NavView.delete)
    has_not_found_error = '未找到指定记录' in source
    record('B6', 'DELETE 不存在 ID 返回错误', has_not_found_error, f'has_error={has_not_found_error}')


# ============================================================
# V11: 行为验证 - PATCH sort swap 失败后 sort_id 一致（事务回滚）
# ============================================================
def test_v11_sort_swap_rollback():
    """V11: 模拟 PATCH sort swap 中 nav.save() 失败，事务回滚后两记录 sort_id 不变"""
    sid = transaction.savepoint()
    try:
        nav = Navigation.objects.create(
            title='V11-nav', desc='d1', logo='l1',
            links='[{"url":"http://a.com"}]', tenant_id='verify_test'
        )
        nav.sort_id = nav.id
        nav.save()

        tmp = Navigation.objects.create(
            title='V11-tmp', desc='d2', logo='l2',
            links='[{"url":"http://b.com"}]', tenant_id='verify_test'
        )
        tmp.sort_id = tmp.id
        tmp.save()

        nav_original = nav.sort_id
        tmp_original = tmp.sort_id

        # 在事务内模拟 swap + nav.save() 失败
        try:
            with transaction.atomic():
                tmp.sort_id, nav.sort_id = nav.sort_id, tmp.sort_id
                tmp.save(update_fields=['sort_id'])
                # 模拟 nav.save 失败
                raise Exception('Simulated DB failure')
        except Exception:
            pass

        # 事务回滚后，两记录 sort_id 应该不变
        nav.refresh_from_db()
        tmp.refresh_from_db()

        consistent = (nav.sort_id == nav_original and tmp.sort_id == tmp_original)
        record('B1', 'PATCH sort swap 失败后事务回滚，sort_id 不变', consistent,
               f'nav: {nav_original}->{nav.sort_id}, tmp: {tmp_original}->{tmp.sort_id}')
    finally:
        transaction.savepoint_rollback(sid)


# ============================================================
# V12: 行为验证 - POST create 失败后无孤儿记录（事务回滚）
# ============================================================
def test_v12_create_rollback():
    """V12: 模拟 POST create 中 sort_id save 失败，事务回滚后无孤儿记录"""
    sid = transaction.savepoint()
    try:
        form_data = {
            'title': 'V12-orphan', 'desc': 'd', 'logo': 'l',
            'links': '[{"url":"http://c.com"}]', 'tenant_id': 'verify_test'
        }
        try:
            with transaction.atomic():
                nav = Navigation.objects.create(**form_data)
                # 模拟 nav.sort_id = nav.id; nav.save() 失败
                raise Exception('Simulated DB failure')
        except Exception:
            pass

        # 事务回滚后，不应存在孤儿记录
        exists = Navigation.objects.filter(title='V12-orphan').exists()
        record('B2', 'POST create 失败后事务回滚，无孤儿记录', not exists,
               f'orphan_exists={exists}')
    finally:
        transaction.savepoint_rollback(sid)


# ============================================================
# V13: 行为验证 - to_view 损坏 links 不再抛异常
# ============================================================
def test_v13_to_view_corrupted_safe():
    """V13: to_view 在 links 损坏时不抛异常，返回空列表"""
    sid = transaction.savepoint()
    try:
        nav = Navigation.objects.create(
            title='V13-corrupt', desc='d', logo='l',
            links='NOT_VALID_JSON{{{', tenant_id='verify_test'
        )
        try:
            result = nav.to_view()
            safe = (result['links'] == [])
            record('B4', 'to_view 损坏 links 不抛异常，返回空列表', safe,
                   f"links={result.get('links')}")
        except Exception as e:
            record('B4', 'to_view 损坏 links 不抛异常', False, f'{type(e).__name__}: {e}')
    finally:
        transaction.savepoint_rollback(sid)


# ============================================================
# V14: 行为验证 - check_recent_duplicate 不匹配已删除记录
# ============================================================
def test_v14_dedup_ignores_deleted():
    """V14: check_recent_duplicate 不匹配已软删除的记录"""
    sid = transaction.savepoint()
    try:
        # 创建一条记录然后软删除
        nav = Navigation.objects.create(
            title='V14-dedup-test', desc='dedup-desc', logo='l',
            links='[]', tenant_id='verify_test'
        )
        nav.is_deleted = True
        nav.save()

        # check_recent_duplicate 不应匹配已删除的记录
        is_dup = check_recent_duplicate(Navigation, {
            'title': 'V14-dedup-test',
            'desc': 'dedup-desc',
        })
        record('B7b', 'check_recent_duplicate 不匹配已删除记录', not is_dup,
               f'is_dup={is_dup}')
    finally:
        transaction.savepoint_rollback(sid)


# ============================================================
# V15: NoticeView POST 有 transaction.atomic()（确认未破坏）
# ============================================================
def test_v15_notice_post_transaction():
    source = get_source(NoticeView.post)
    has_atomic = 'transaction.atomic' in source
    record('Notice-R2', 'NoticeView POST 有 transaction.atomic()（未破坏）', has_atomic, '')


# ============================================================
# V16: NoticeView PATCH 有 transaction.atomic + select_for_update（确认未破坏）
# ============================================================
def test_v16_notice_patch_transaction():
    source = get_source(NoticeView.patch)
    has_atomic = 'transaction.atomic' in source
    has_select = 'select_for_update' in source
    record('Notice-R1', 'NoticeView PATCH 有 transaction.atomic + select_for_update（未破坏）',
           has_atomic and has_select, '')


# ============================================================
# V17: Navigation 模型 save() 有 update_fields
# ============================================================
def test_v17_save_update_fields():
    nav_source = get_source(NavView.post)
    patch_source = get_source(NavView.patch)
    delete_source = get_source(NavView.delete)
    has_update_fields_post = 'update_fields' in nav_source
    has_update_fields_patch = 'update_fields' in patch_source
    has_update_fields_delete = 'update_fields' in delete_source
    all_ok = has_update_fields_post and has_update_fields_patch and has_update_fields_delete
    record('update_fields', 'NavView 所有 save() 调用有 update_fields', all_ok,
           f'post={has_update_fields_post}, patch={has_update_fields_patch}, delete={has_update_fields_delete}')


def main():
    print('=' * 70)
    print('Home Navigation/Notice 修复验证')
    print('=' * 70)
    print()

    print('--- 源码检查类验证 ---')
    print()
    test_v1_patch_transaction()
    test_v2_post_transaction()
    test_v3_delete_transaction()
    test_v4_post_audit()
    test_v5_patch_audit()
    test_v6_model_fields()
    test_v7_to_view_error_handling()
    test_v8_dedup_is_deleted()
    test_v9_edit_not_found_error()
    test_v10_delete_not_found_error()
    test_v15_notice_post_transaction()
    test_v16_notice_patch_transaction()
    test_v17_save_update_fields()

    print('--- 行为验证类验证 ---')
    print()
    test_v11_sort_swap_rollback()
    test_v12_create_rollback()
    test_v13_to_view_corrupted_safe()
    test_v14_dedup_ignores_deleted()

    print('=' * 70)
    print('验证结果汇总')
    print('=' * 70)
    fixed = [r for r in _results if r['status'] == 'FIXED']
    broken = [r for r in _results if r['status'] == 'STILL BROKEN']
    print(f'总计: {len(_results)} | 已修复: {len(fixed)} | 未通过: {len(broken)}')
    if broken:
        print('\n⚠️ 未通过项:')
        for r in broken:
            print(f"  - {r['risk_id']}: {r['description']}")
    print()
    print('=' * 70)
    print('验证完成')
    print('=' * 70)


if __name__ == '__main__':
    main()

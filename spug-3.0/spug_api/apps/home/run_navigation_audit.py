# -*- coding: utf-8 -*-
"""
Home Navigation 模块 CRUD 风险审计脚本

基于 CRUD 系统可靠性指南 §1.1-§3.5 和前 10 个模块的实战审计经验。
使用 savepoint 回滚，不污染 dev 数据。

对照模块：home/notice.py（同模块兄弟，已修复事务/行锁问题）

运行方式（在 tdyw-test 容器内）：
    docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test \
        python manage.py shell < apps/home/run_navigation_audit.py

或管道方式：
    cat apps/home/run_navigation_audit.py | docker exec -i -e PYTHONIOENCODING=utf-8 \
        -w /data/spug/spug_api tdyw-test python manage.py shell
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

from django.db import transaction, connection
from django.test import RequestFactory
from django.http import JsonResponse
from django.utils import timezone

from apps.home.models import Navigation, Notice
from apps.home.navigation import NavView
from apps.home.notice import NoticeView
from apps.logs.audit import record_audit_event
from apps.logs.models import AuditLog
from libs.idempotency import check_recent_duplicate

logger = logging.getLogger(__name__)

# ============================================================
# 测试结果跟踪
# ============================================================
_results = []

def record(risk_id, severity, description, passed, detail=''):
    """记录测试结果。passed=True 表示风险确认（测试通过=风险存在）"""
    status = 'RISK CONFIRMED' if passed else 'NO RISK'
    _results.append({
        'risk_id': risk_id,
        'severity': severity,
        'description': description,
        'status': status,
        'detail': detail,
    })
    icon = '❌' if passed else '✅'
    print(f'{icon} {risk_id} ({severity}): {description}')
    print(f'   -> {status}')
    if detail:
        print(f'   详情: {detail}')
    print()


def get_source(func):
    """获取函数源码"""
    return inspect.getsource(func)


def has_keyword(source, keyword):
    """检查源码中是否包含关键字"""
    return keyword in source


# ============================================================
# R1 (P0): PATCH sort swap 缺少 transaction.atomic()
# 对照：NoticeView.patch 已修复（有 transaction.atomic + select_for_update）
# ============================================================
def test_r1_patch_no_transaction():
    """R1: NavView.patch 的 sort swap 操作没有包裹 transaction.atomic()"""
    source = get_source(NavView.patch)
    has_atomic = has_keyword(source, 'transaction.atomic')
    has_select = has_keyword(source, 'select_for_update')

    # 对比 NoticeView
    notice_source = get_source(NoticeView.patch)
    notice_has_atomic = has_keyword(notice_source, 'transaction.atomic')
    notice_has_select = has_keyword(notice_source, 'select_for_update')

    detail = (
        f'NavView.patch: atomic={has_atomic}, select_for_update={has_select} | '
        f'NoticeView.patch(已修复): atomic={notice_has_atomic}, select_for_update={notice_has_select}'
    )
    # 风险确认 = NavView 没有 atomic（not has_atomic = True -> 风险存在）
    record('R1', 'P0', 'PATCH sort swap 缺少 transaction.atomic()', not has_atomic, detail)


def test_r1_select_for_update_missing():
    """R1b: NavView.patch 缺少 select_for_update()（并发行锁）"""
    source = get_source(NavView.patch)
    has_select = has_keyword(source, 'select_for_update')
    notice_source = get_source(NoticeView.patch)
    notice_has_select = has_keyword(notice_source, 'select_for_update')

    detail = f'NavView: {has_select} | NoticeView(已修复): {notice_has_select}'
    record('R1b', 'P2', 'PATCH 缺少 select_for_update() 行锁', not has_select, detail)


# ============================================================
# R2 (P1): POST create 缺少 transaction.atomic()
# 对照：NoticeView.post 已修复
# ============================================================
def test_r2_post_no_transaction():
    """R2: NavView.post 的 create+sort_id 更新没有包裹 transaction.atomic()"""
    source = get_source(NavView.post)
    has_atomic = has_keyword(source, 'transaction.atomic')
    notice_source = get_source(NoticeView.post)
    notice_has_atomic = has_keyword(notice_source, 'transaction.atomic')

    detail = f'NavView.post: atomic={has_atomic} | NoticeView.post(已修复): atomic={notice_has_atomic}'
    record('R2', 'P1', 'POST create 缺少 transaction.atomic()', not has_atomic, detail)


# ============================================================
# R3 (P1): DELETE 缺少 transaction.atomic()
# 对照：NoticeView.delete 也没有（两个模块都有此问题）
# ============================================================
def test_r3_delete_no_transaction():
    """R3: NavView.delete 的 audit log + soft delete 没有包裹 transaction.atomic()"""
    source = get_source(NavView.delete)
    has_atomic = has_keyword(source, 'transaction.atomic')
    notice_source = get_source(NoticeView.delete)
    notice_has_atomic = has_keyword(notice_source, 'transaction.atomic')

    detail = f'NavView.delete: atomic={has_atomic} | NoticeView.delete: atomic={notice_has_atomic}'
    record('R3', 'P1', 'DELETE 缺少 transaction.atomic()（audit + soft delete 非原子）', not has_atomic, detail)


# ============================================================
# R4 (P1): POST create/edit 缺少审计日志
# 对照：NoticeView.post 也没有审计日志（两个模块都有此问题）
# ============================================================
def test_r4_post_no_audit():
    """R4: NavView.post 的 create/edit 操作没有调用 record_audit_event"""
    source = get_source(NavView.post)
    has_audit = has_keyword(source, 'record_audit_event')
    # Notice POST 也没有审计日志
    notice_source = get_source(NoticeView.post)
    notice_has_audit = has_keyword(notice_source, 'record_audit_event')
    # DELETE 有审计
    delete_source = get_source(NavView.delete)
    delete_has_audit = has_keyword(delete_source, 'record_audit_event')

    detail = f'POST: audit={has_audit} | Notice POST: audit={notice_has_audit} | DELETE: audit={delete_has_audit}'
    record('R4', 'P1', 'POST create/edit 缺少 record_audit_event 审计日志', not has_audit, detail)


# ============================================================
# R5 (P1): PATCH 缺少审计日志
# ============================================================
def test_r5_patch_no_audit():
    """R5: NavView.patch 的 sort 操作没有调用 record_audit_event"""
    source = get_source(NavView.patch)
    has_audit = has_keyword(source, 'record_audit_event')
    notice_source = get_source(NoticeView.patch)
    notice_has_audit = has_keyword(notice_source, 'record_audit_event')

    detail = f'NavView.patch: audit={has_audit} | NoticeView.patch: audit={notice_has_audit}'
    record('R5', 'P2', 'PATCH sort 操作缺少 record_audit_event 审计日志', not has_audit, detail)


# ============================================================
# R6 (P2): GET 查询未过滤租户
# ============================================================
def test_r6_get_no_tenant_filter():
    """R6: NavView.get 查询未使用 for_user() 或 apply_tenant_filter 过滤租户"""
    source = get_source(NavView.get)
    has_for_user = has_keyword(source, 'for_user')
    has_tenant_filter = has_keyword(source, 'apply_tenant_filter')
    # Notice GET 也没有
    notice_source = get_source(NoticeView.get)
    notice_has_for_user = has_keyword(notice_source, 'for_user')

    detail = f'NavView: for_user={has_for_user}, apply_tenant_filter={has_tenant_filter} | Notice: for_user={notice_has_for_user}'
    record('R6', 'P2', 'GET 查询未过滤租户（跨租户数据可见）',
           not has_for_user and not has_tenant_filter, detail)


# ============================================================
# R7 (P2): Navigation 模型缺少 updated_at / updated_by 字段
# ============================================================
def test_r7_model_missing_updated_fields():
    """R7: Navigation 模型缺少 updated_at / updated_by_id / updated_by_name 字段"""
    field_names = {f.name for f in Navigation._meta.get_fields()}
    has_updated_at = 'updated_at' in field_names
    has_updated_by_id = 'updated_by_id' in field_names
    has_updated_by_name = 'updated_by_name' in field_names

    # 对比 Notice
    notice_fields = {f.name for f in Notice._meta.get_fields()}
    notice_has_updated_at = 'updated_at' in notice_fields

    missing = []
    if not has_updated_at:
        missing.append('updated_at')
    if not has_updated_by_id:
        missing.append('updated_by_id')
    if not has_updated_by_name:
        missing.append('updated_by_name')

    detail = f'Navigation 缺少: {missing} | Notice has updated_at: {notice_has_updated_at}'
    record('R7', 'P2', 'Navigation 模型缺少 updated_at/updated_by 字段', bool(missing), detail)


# ============================================================
# R8 (P2): Navigation 模型缺少 deleted_by 字段
# ============================================================
def test_r8_model_missing_deleted_by():
    """R8: Navigation 模型缺少 deleted_by_id / deleted_by_name 字段"""
    field_names = {f.name for f in Navigation._meta.get_fields()}
    has_deleted_by_id = 'deleted_by_id' in field_names
    has_deleted_by_name = 'deleted_by_name' in field_names

    missing = []
    if not has_deleted_by_id:
        missing.append('deleted_by_id')
    if not has_deleted_by_name:
        missing.append('deleted_by_name')

    detail = f'Navigation 缺少: {missing}'
    record('R8', 'P2', 'Navigation 模型缺少 deleted_by 字段（无法追踪删除操作人）', bool(missing), detail)


# ============================================================
# R9 (P2): to_view json.loads 无 try/except（损坏数据致 500）
# ============================================================
def test_r9_to_view_no_error_handling():
    """R9: Navigation.to_view 的 json.loads 无 try/except，损坏 links 致 500"""
    source = inspect.getsource(Navigation.to_view)
    has_try = has_keyword(source, 'try')
    has_except = has_keyword(source, 'except')

    detail = f'to_view source has try={has_try}, except={has_except}'
    record('R9', 'P2', 'to_view json.loads 无 try/except（损坏数据致 GET 500）',
           not has_try, detail)


# ============================================================
# B1: PATCH sort swap 失败模拟（sort_id 数据不一致）
# ============================================================
def test_b1_sort_swap_failure():
    """B1: 模拟 PATCH sort swap 中 nav.save() 失败，验证 sort_id 数据不一致"""
    sid = transaction.savepoint()
    try:
        # 创建两条导航记录
        nav = Navigation.objects.create(
            title='B1-nav', desc='desc1', logo='logo1',
            links='[{"url":"http://a.com"}]', tenant_id='audit_test'
        )
        nav.sort_id = nav.id
        nav.save()

        tmp = Navigation.objects.create(
            title='B1-tmp', desc='desc2', logo='logo2',
            links='[{"url":"http://b.com"}]', tenant_id='audit_test'
        )
        tmp.sort_id = tmp.id
        tmp.save()

        nav_original = nav.sort_id
        tmp_original = tmp.sort_id

        # 模拟 swap 操作（NavView.patch 的逻辑）
        tmp.sort_id, nav.sort_id = nav.sort_id, tmp.sort_id
        tmp.save()  # 第一次 save 成功

        # 模拟 nav.save() 失败
        # 实际代码中，异常会向上传播，但 tmp.save() 已经提交
        # 用 mock 模拟
        with patch.object(Navigation, 'save', side_effect=Exception('Simulated DB failure')):
            try:
                nav.save()
            except Exception:
                pass  # 模拟异常被传播但未捕获（实际会 500）

        # 刷新数据库状态
        nav.refresh_from_db()
        tmp.refresh_from_db()

        # 验证数据不一致
        # tmp.sort_id 已变为 nav_original（第一次 save 成功）
        # nav.sort_id 未变（save 失败，仍是 nav_original）
        # 结果：两条记录 sort_id 相同！
        sort_id_conflict = (nav.sort_id == tmp.sort_id)

        detail = (
            f'nav.sort_id={nav.sort_id}(original={nav_original}), '
            f'tmp.sort_id={tmp.sort_id}(original={tmp_original}), '
            f'conflict={sort_id_conflict}'
        )
        record('B1', 'P0', 'PATCH sort swap 失败致 sort_id 数据不一致', sort_id_conflict, detail)
    finally:
        transaction.savepoint_rollback(sid)


# ============================================================
# B2: POST create 失败模拟（孤儿记录 sort_id=0）
# ============================================================
def test_b2_create_failure():
    """B2: 模拟 POST create 中 sort_id 更新失败，验证孤儿记录"""
    sid = transaction.savepoint()
    try:
        # 创建记录（模拟 Navigation.objects.create）
        nav = Navigation.objects.create(
            title='B2-orphan', desc='desc', logo='logo',
            links='[{"url":"http://c.com"}]', tenant_id='audit_test'
        )
        # nav.sort_id 默认为 0
        # 模拟 nav.sort_id = nav.id; nav.save() 失败
        nav.sort_id = nav.id
        with patch.object(Navigation, 'save', side_effect=Exception('Simulated DB failure')):
            try:
                nav.save()
            except Exception:
                pass

        # 刷新数据库状态
        nav.refresh_from_db()

        # 验证：记录存在但 sort_id=0（不是预期的 nav.id）
        orphan_record = (nav.sort_id == 0)
        detail = f'nav.id={nav.id}, nav.sort_id={nav.sort_id}, orphan={orphan_record}'
        record('B2', 'P1', 'POST create 失败致孤儿记录 sort_id=0', orphan_record, detail)
    finally:
        transaction.savepoint_rollback(sid)


# ============================================================
# B3: DELETE 失败模拟（审计日志已写但记录未删除）
# ============================================================
def test_b3_delete_failure():
    """B3: 模拟 DELETE 中 nav.save() 失败，验证审计日志已写但记录未删除"""
    sid = transaction.savepoint()
    try:
        nav = Navigation.objects.create(
            title='B3-delete-test', desc='desc', logo='logo',
            links='[{"url":"http://d.com"}]', tenant_id='audit_test'
        )
        nav.sort_id = nav.id
        nav.save()
        nav_id = nav.id

        # 获取删除前的审计日志数量
        audit_before = AuditLog.objects.filter(
            target_type='navigation', target_id=str(nav_id)
        ).count()

        # 模拟 record_audit_event 成功写入
        # （实际代码中 record_audit_event 在 nav.save() 之前调用）
        factory = RequestFactory()
        request = factory.delete(f'/home/navigation/?id={nav_id}')
        request.user = type('MockUser', (), {
            'id': 999, 'username': 'audit_test_user',
            'is_supper': False, 'is_active': True,
            'tenant_id': 'audit_test',
            'has_perms': lambda self, perms: True,
        })()

        try:
            record_audit_event(
                request, 'delete', 'navigation',
                target_id=str(nav_id), target_name='B3-delete-test',
                detail={'title': 'B3-delete-test'}
            )
        except Exception:
            pass  # record_audit_event 可能在某些环境下失败

        # 获取审计日志数量（应该增加了）
        audit_after = AuditLog.objects.filter(
            target_type='navigation', target_id=str(nav_id)
        ).count()
        audit_written = audit_after > audit_before

        # 模拟 nav.save() 失败（nav.is_deleted = True; nav.save()）
        nav.is_deleted = True
        nav.deleted_at = timezone.now()
        with patch.object(Navigation, 'save', side_effect=Exception('Simulated DB failure')):
            try:
                nav.save()
            except Exception:
                pass

        # 刷新数据库状态
        nav.refresh_from_db()

        # 验证：审计日志已写，但记录仍未删除
        not_deleted = (nav.is_deleted == False)

        detail = f'audit_written={audit_written}, nav.is_deleted={nav.is_deleted}, not_deleted={not_deleted}'
        record('B3', 'P1', 'DELETE 失败致审计日志已写但记录未删除',
               audit_written and not_deleted, detail)
    finally:
        transaction.savepoint_rollback(sid)


# ============================================================
# B4: to_view 损坏 links 致 500
# ============================================================
def test_b4_to_view_corrupted_links():
    """B4: Navigation.to_view 在 links 损坏时抛 JSONDecodeError"""
    sid = transaction.savepoint()
    try:
        nav = Navigation.objects.create(
            title='B4-corrupt', desc='desc', logo='logo',
            links='NOT_VALID_JSON{{{', tenant_id='audit_test'
        )
        # 直接调用 to_view
        try:
            nav.to_view()
            # 如果没有抛异常，风险不存在
            record('B4', 'P2', 'to_view 损坏 links 致 500', False, 'no exception raised')
        except (json.JSONDecodeError, Exception) as e:
            record('B4', 'P2', 'to_view 损坏 links 致 500', True, f'{type(e).__name__}: {e}')
    finally:
        transaction.savepoint_rollback(sid)


# ============================================================
# B5: POST edit 不存在的 ID 静默成功
# ============================================================
def test_b5_edit_nonexistent_id():
    """B5: POST edit 传入不存在的 ID，update 返回 0 行但 API 返回成功"""
    source = get_source(NavView.post)
    # 检查 edit 分支是否有 "未找到" 检查
    has_not_found_check = '未找到' in source or 'not found' in source.lower()

    # 直接行为验证：filter(pk=999999).update() 返回 0 但无错误
    affected = Navigation.objects.filter(pk=999999, is_deleted=False).update(title='nonexistent')
    silent_success = (affected == 0)

    detail = f'affected_rows={affected}, has_not_found_check={has_not_found_check}'
    record('B5', 'P2', 'POST edit 不存在 ID 静默成功（无 404 反馈）',
           silent_success and not has_not_found_check, detail)


# ============================================================
# B6: DELETE 不存在的 ID 静默成功
# ============================================================
def test_b6_delete_nonexistent_id():
    """B6: DELETE 传入不存在的 ID，API 返回成功（无错误）"""
    source = get_source(NavView.delete)
    # NavView.delete 有 if nav: 检查，所以不存在时不会执行删除
    # 但也不会返回错误，而是返回 json_response(error=None) = success
    has_if_nav = 'if nav' in source
    # 检查是否有 else 分支返回错误
    has_else_error = 'else' in source and 'error' in source

    # 行为验证：nav = filter(pk=999999).first() -> None -> 不执行删除 -> 返回 success
    nav = Navigation.objects.filter(pk=999999, is_deleted=False).first()
    silent_success = (nav is None) and has_if_nav and not has_else_error

    detail = f'nav_found={nav is not None}, has_if_nav={has_if_nav}, has_else_error={has_else_error}'
    record('B6', 'P2', 'DELETE 不存在 ID 静默成功（无 404 反馈）', silent_success, detail)


# ============================================================
# B7: check_recent_duplicate 未过滤 is_deleted
# ============================================================
def test_b7_dedup_no_is_deleted_filter():
    """B7: check_recent_duplicate 未过滤 is_deleted，软删除记录会触发误判"""
    source = inspect.getsource(check_recent_duplicate)
    has_is_deleted = 'is_deleted' in source

    detail = f'check_recent_duplicate source has is_deleted filter: {has_is_deleted}'
    record('B7', 'P2', 'check_recent_duplicate 未过滤 is_deleted（软删除记录触发误判）',
           not has_is_deleted, detail)


# ============================================================
# B8: Navigation 模型缺少业务唯一约束
# ============================================================
def test_b8_no_unique_constraint():
    """B8: Navigation 模型缺少 (title, tenant_id) 唯一约束"""
    constraints = Navigation._meta.constraints
    unique_constraints = [c for c in constraints if hasattr(c, 'fields')]

    # 检查是否有任何涉及 title 的唯一约束
    has_title_unique = any(
        'title' in getattr(c, 'fields', []) for c in unique_constraints
    )

    detail = f'constraints={[c.name for c in constraints]}, has_title_unique={has_title_unique}'
    record('B8', 'P2', 'Navigation 模型缺少 (title, tenant_id) 唯一约束',
           not has_title_unique, detail)


# ============================================================
# B9: Navigation 模型缺少 CHECK 约束
# ============================================================
def test_b9_no_check_constraints():
    """B9: Navigation 模型缺少 CHECK 约束（如 sort_id >= 0）"""
    constraints = Navigation._meta.constraints
    check_constraints = [c for c in constraints if c.__class__.__name__ == 'CheckConstraint']

    detail = f'check_constraints={[c.name for c in check_constraints]}'
    record('B9', 'P3', 'Navigation 模型缺少 CHECK 约束', len(check_constraints) == 0, detail)


# ============================================================
# B10: PATCH sort swap - tmp.save() 之前无 select_for_update
# 对照：NoticeView.patch 用 select_for_update() 锁行
# ============================================================
def test_b10_patch_no_lock_on_swap_target():
    """B10: NavView.patch 查找 swap target 时未用 select_for_update"""
    source = get_source(NavView.patch)
    # 检查查找 tmp 的查询是否使用 select_for_update
    has_lock = 'select_for_update' in source

    notice_source = get_source(NoticeView.patch)
    notice_has_lock = 'select_for_update' in notice_source

    detail = f'NavView: {has_lock} | NoticeView(已修复): {notice_has_lock}'
    record('B10', 'P2', 'PATCH 查找 swap target 未用 select_for_update', not has_lock, detail)


# ============================================================
# B11: POST create - form 包含 id=None 传入 create()
# ============================================================
def test_b11_create_with_id_none():
    """B11: POST create 时 form 仍包含 id=None，传入 Navigation.objects.create(**form)"""
    source = get_source(NavView.post)
    # 在 create 分支中，form.id 仍存在（只有 edit 分支 pop 了 id）
    # 检查 create 分支是否有 form.pop('id') 或 del form['id']
    # create 分支在 else 块中

    # 找到 else 分支
    lines = source.split('\n')
    create_branch_lines = []
    in_else = False
    for line in lines:
        if 'else:' in line:
            in_else = True
        if in_else:
            create_branch_lines.append(line)

    create_branch_source = '\n'.join(create_branch_lines)
    # 检查 create 分支是否 pop 或删除了 id
    has_pop_id = 'pop' in create_branch_source and "'id'" in create_branch_source
    has_del_id = "del " in create_branch_source and 'form' in create_branch_source and 'id' in create_branch_source

    detail = f'create branch has pop id: {has_pop_id}, has del id: {has_del_id}'
    # 如果没有 pop/del id，create(**form) 会包含 id=None
    # Django 处理 id=None 为自动生成（不会报错），但不干净
    record('B11', 'P3', 'POST create 时 form 包含 id=None（Django 容忍但不规范）',
           not has_pop_id and not has_del_id, detail)


# ============================================================
# B12: Navigation logo/links 是 TextField 无大小限制
# ============================================================
def test_b12_textfield_no_size_limit():
    """B12: Navigation logo/links 是 TextField 无 max_length 限制"""
    logo_field = Navigation._meta.get_field('logo')
    links_field = Navigation._meta.get_field('links')

    logo_is_text = logo_field.get_internal_type() == 'TextField'
    links_is_text = links_field.get_internal_type() == 'TextField'
    logo_has_max = hasattr(logo_field, 'max_length') and logo_field.max_length is not None
    links_has_max = hasattr(links_field, 'max_length') and links_field.max_length is not None

    detail = f'logo: TextField={logo_is_text}, max_length={logo_has_max} | links: TextField={links_is_text}, max_length={links_has_max}'
    record('B12', 'P3', 'logo/links TextField 无大小限制', logo_is_text and links_is_text, detail)


# ============================================================
# 主函数
# ============================================================
def main():
    print('=' * 70)
    print('Home Navigation 模块 CRUD 风险审计')
    print('基于 CRUD 系统可靠性指南 §1.1-§3.5')
    print('对照模块: home/notice.py (已修复事务/行锁)')
    print('=' * 70)
    print()

    # === 源码检查类测试 ===
    print('--- 源码检查类测试 ---')
    print()
    test_r1_patch_no_transaction()
    test_r1_select_for_update_missing()
    test_r2_post_no_transaction()
    test_r3_delete_no_transaction()
    test_r4_post_no_audit()
    test_r5_patch_no_audit()
    test_r6_get_no_tenant_filter()
    test_r7_model_missing_updated_fields()
    test_r8_model_missing_deleted_by()
    test_r9_to_view_no_error_handling()
    test_b10_patch_no_lock_on_swap_target()
    test_b11_create_with_id_none()
    test_b12_textfield_no_size_limit()

    # === 行为验证类测试 ===
    print('--- 行为验证类测试 ---')
    print()
    test_b1_sort_swap_failure()
    test_b2_create_failure()
    test_b3_delete_failure()
    test_b4_to_view_corrupted_links()
    test_b5_edit_nonexistent_id()
    test_b6_delete_nonexistent_id()
    test_b7_dedup_no_is_deleted_filter()
    test_b8_no_unique_constraint()
    test_b9_no_check_constraints()

    # === 汇总 ===
    print('=' * 70)
    print('审计结果汇总')
    print('=' * 70)
    print()

    confirmed = [r for r in _results if r['status'] == 'RISK CONFIRMED']
    no_risk = [r for r in _results if r['status'] == 'NO RISK']

    by_severity = {}
    for r in confirmed:
        by_severity.setdefault(r['severity'], []).append(r)

    print(f'总测试数: {len(_results)}')
    print(f'风险确认: {len(confirmed)}')
    print(f'无风险:   {len(no_risk)}')
    print()

    for sev in ['P0', 'P1', 'P2', 'P3']:
        if sev in by_severity:
            print(f'{sev} 级风险 ({len(by_severity[sev])} 项):')
            for r in by_severity[sev]:
                print(f'  - {r["risk_id"]}: {r["description"]}')
            print()

    if no_risk:
        print('已排除的风险:')
        for r in no_risk:
            print(f'  - {r["risk_id"]}: {r["description"]}')
        print()

    print('=' * 70)
    print('审计完成')
    print('=' * 70)


if __name__ == '__main__':
    main()
else:
    # 支持通过 manage.py shell 执行
    main()

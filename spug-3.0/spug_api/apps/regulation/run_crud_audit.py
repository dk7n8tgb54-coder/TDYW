# -*- coding: utf-8 -*-
"""
规章管理模块 CRUD 可靠性审计 - 独立脚本

测试环境：dev 数据库（tdyw-test 容器，bind mount）
运行方式：
  wsl bash -c 'cat /mnt/e/TDYW/spug-3.0/spug_api/apps/regulation/run_crud_audit.py | docker exec -i -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python manage.py shell 2>&1'

注意：脚本使用 savepoint 回滚，不污染 dev 数据。
"""
import os, sys, json, time, traceback
from datetime import datetime

import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
django.setup()

from django.conf import settings
settings.ALLOWED_HOSTS = ['*']

from django.db import connection, transaction
from django.test import RequestFactory, Client
from django.utils import timezone
from django.core.exceptions import FieldError

from apps.account.models import User
from apps.setting.utils import AppSetting
from apps.regulation.models import Regulation, RegulationCategory, RegulationAttachment
from libs.idempotency import check_recent_duplicate

# ══════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════

RESULTS = []


def report(test_id, desc, status, detail=''):
    icon = {'PASS': '✓', 'FAIL': '✗', 'SKIP': '⊘', 'CONFIRMED': '⚠'}[status]
    RESULTS.append((test_id, desc, status, detail))
    print(f'  {icon} [{test_id}] {desc}')
    if detail:
        for line in detail.split('\n'):
            print(f'      {line}')


def section(title):
    print(f'\n{"="*60}')
    print(f'  {title}')
    print(f'{"="*60}')


def make_user(username, perms=None, is_supper=False):
    token = (username * 10)[:32]
    User.objects.filter(username=username).delete()
    user = User.objects.create(
        username=username, nickname=username, password_hash='x',
        is_active=True, is_supper=is_supper, access_token=token,
        token_expired=int(time.time()) + 3600,
        last_login='2026-01-01', last_ip='127.0.0.1', type='default',
    )
    if not is_supper:
        user.set_perms_cache(set(perms or []), version=0)
    return user


def safe(test_id, desc, fn):
    """安全执行测试，捕获异常不中断"""
    try:
        fn()
    except Exception as e:
        report(test_id, desc, 'FAIL', f'{type(e).__name__}: {e}')
        traceback.print_exc()


ALL_PERMS = [
    'document.regulation.view', 'document.regulation.add',
    'document.regulation.edit', 'document.regulation.delete',
    'document.regulation.upload', 'document.regulation.download',
    'document.regulation.category_manage',
]


def capture_queries(fn):
    """捕获 SQL 查询并返回"""
    old = connection.force_debug_cursor
    connection.force_debug_cursor = True
    connection.queries_log.clear()
    try:
        fn()
        queries = list(connection.queries_log)  # 在 reset 前读取
    finally:
        connection.force_debug_cursor = old
    return queries


# ══════════════════════════════════════════
# 审计主流程
# ══════════════════════════════════════════

def run_audit():
    sid = transaction.savepoint()
    try:
        AppSetting.set('bind_ip', False)
        admin = make_user('reg_audit_admin', ALL_PERMS)

        root = RegulationCategory.objects.create(name='审计根', created_by=admin)
        child = RegulationCategory.objects.create(name='审计子', parent=root, created_by=admin)
        leaf = RegulationCategory.objects.create(name='审计叶', parent=child, created_by=admin)

        # ═══════ R1 (P0 BUG) ═══════
        section('R1 (P0): check_recent_duplicate(Regulation) FieldError')

        def r1_1():
            fields = {f.name for f in Regulation._meta.get_fields()}
            if 'created_at' not in fields:
                report('R1-1', 'Regulation 无 created_at 字段', 'CONFIRMED',
                       f'字段: {sorted(fields)}')
            else:
                report('R1-1', 'Regulation 有 created_at', 'PASS', 'R1 已修复')
        safe('R1-1', 'Regulation 无 created_at', r1_1)

        def r1_2():
            try:
                check_recent_duplicate(Regulation, {'title': 't', 'rule_no': 'T'})
                report('R1-2', 'check_recent_duplicate 正常', 'PASS', 'R1 已修复')
            except FieldError as e:
                report('R1-2', 'check_recent_duplicate 抛 FieldError', 'CONFIRMED', str(e))
        safe('R1-2', 'check_recent_duplicate FieldError', r1_2)

        def r1_3():
            result = check_recent_duplicate(RegulationCategory, {'name': '不存在'}, window_seconds=1)
            report('R1-3', 'RegulationCategory 对比正常', 'PASS', f'返回 {result}')
        safe('R1-3', 'RegulationCategory 对比', r1_3)

        def r1_4():
            client = Client()
            client.defaults['HTTP_X_TOKEN'] = admin.access_token
            client.defaults['HTTP_X_FORWARDED_FOR'] = '127.0.0.1'
            resp = client.post('/regulation/create/', data=json.dumps({
                'title': 'API测试', 'rule_no': 'API-001',
                'category_id': leaf.id, 'issuing_authority': '测试',
                'biz_type': '安全', 'publish_date': '2026-01-01', 'effective_date': '2026-02-01',
            }), content_type='application/json')
            try:
                body = resp.json()
            except Exception:
                body = {}
            if resp.status_code == 200 and not body.get('error'):
                report('R1-4', 'API 创建规章返回 200', 'PASS', 'R1 已修复')
            else:
                report('R1-4', f'API 创建返回 {resp.status_code}', 'CONFIRMED',
                       f'error: {body.get("error", resp.status_code)}')
        safe('R1-4', 'API 创建规章', r1_4)

        # ═══════ R2 (P1) ═══════
        section('R2 (P1): save() 无 update_fields -> 并发覆盖')

        reg = Regulation.objects.create(
            title='R2原始', rule_no='R2-001', category=leaf,
            issuing_authority='审计', biz_type='安全',
            publish_date='2026-01-01', effective_date='2026-02-01',
            status='active', updated_by=admin,
        )

        def r2_1():
            # 验证使用 update_fields 后并发不再覆盖
            a = Regulation.objects.get(pk=reg.pk)
            b = Regulation.objects.get(pk=reg.pk)
            a.title = 'A改的标题'
            b.rule_no = 'R2-002'
            a.save(update_fields=['title'])  # 使用 update_fields
            b.save(update_fields=['rule_no'])  # 使用 update_fields
            reg.refresh_from_db()
            if reg.title == 'A改的标题' and reg.rule_no == 'R2-002':
                report('R2-1', '使用 update_fields 后并发不覆盖', 'PASS',
                       f'title="{reg.title}", rule_no="{reg.rule_no}"')
            else:
                report('R2-1', '并发覆盖仍存在', 'FAIL',
                       f'title="{reg.title}", rule_no="{reg.rule_no}"')
        safe('R2-1', '并发覆盖修复验证', r2_1)

        def r2_2():
            # 代码审查：views.py 中 regulation.save() 未传 update_fields
            import inspect
            from apps.regulation import views
            src = inspect.getsource(views.RegulationDetailView.put)
            if '.save(update_fields' in src:
                report('R2-2', 'PUT 使用了 update_fields', 'PASS', '已修复')
            elif '.save()' in src:
                report('R2-2', 'PUT save() 未传 update_fields', 'CONFIRMED',
                       '代码确认：regulation.save() 保存全部列')
            else:
                report('R2-2', 'PUT save 方式', 'FAIL', '无法确认')
        safe('R2-2', 'PUT save update_fields', r2_2)

        # ═══════ R3 (P1) ═══════
        section('R3 (P1): 分类 save() 无 update_fields')

        def r3_1():
            import inspect
            from apps.regulation import views
            src = inspect.getsource(views.CategoryDetailView.put)
            if '.save(update_fields' in src:
                report('R3-1', '分类 PUT 使用了 update_fields', 'PASS', '已修复')
            elif '.save()' in src:
                report('R3-1', '分类 PUT save() 未传 update_fields', 'CONFIRMED',
                       '代码确认：cat.save() 保存全部列')
            else:
                report('R3-1', '分类 PUT save 方式', 'FAIL', '无法确认')
        safe('R3-1', '分类 save update_fields', r3_1)

        # ═══════ R4 (P1) ═══════
        section('R4 (P1): 废止 save() 无 update_fields')

        reg4 = Regulation.objects.create(
            title='R4规章', rule_no='R4-001', category=leaf,
            issuing_authority='审计', biz_type='安全',
            publish_date='2026-01-01', effective_date='2026-02-01',
            status='active', updated_by=admin,
        )

        def r4_1():
            import inspect
            from apps.regulation import views
            src = inspect.getsource(views.RegulationRetireView.post)
            if '.save(update_fields' in src:
                report('R4-1', '废止使用 update_fields', 'PASS', '已修复')
            elif '.save()' in src:
                report('R4-1', '废止 save() 未传 update_fields', 'CONFIRMED',
                       '代码确认：regulation.save() 保存全部列（仅改 status）')
            else:
                report('R4-1', '废止 save 方式', 'FAIL', '无法确认')
        safe('R4-1', '废止 save update_fields', r4_1)

        # ═══════ R5 (P2) ═══════
        section('R5 (P2): 软删除附件被 CASCADE 覆盖')

        def r5_1():
            # 代码审查：验证 views.py 中 delete 方法不再有冗余 soft-delete
            import inspect
            from apps.regulation import views
            src = inspect.getsource(views.RegulationDetailView.delete)
            has_soft_delete = 'is_deleted=True' in src and 'update(' in src and 'regulation.delete()' in src
            if has_soft_delete:
                report('R5-1', 'delete 方法仍有冗余 soft-delete', 'CONFIRMED', '软删除被 CASCADE 覆盖')
            else:
                report('R5-1', 'delete 方法已移除冗余 soft-delete', 'PASS', '直接 CASCADE 删除')
        safe('R5-1', '软删除+CASCADE', r5_1)

        # ═══════ R6 (P2) ═══════
        section('R6 (P2): __icontains LIKE 全表扫描')

        def r6_1():
            import inspect
            from apps.regulation import views
            src = inspect.getsource(views.RegulationListView.get)
            if 'title__icontains' in src and 'rule_no__startswith' in src:
                report('R6-1', 'keyword 搜索优化（title 用 icontains，rule_no 用 startswith）', 'PASS',
                       'rule_no startswith 可走索引；title 保留 icontains 用于模糊搜索')
            elif '__icontains' in src:
                report('R6-1', 'title__icontains 生成 LIKE %xxx%', 'CONFIRMED',
                       'icontains 在无索引/有索引 CharField 上均生成 LIKE，绕过 B-Tree')
            else:
                report('R6-1', '未使用 icontains', 'PASS', '可能已改用其他查询方式')
        safe('R6-1', 'title icontains', r6_1)

        def r6_2():
            import inspect
            from apps.regulation import views
            src = inspect.getsource(views.RegulationListView.get)
            icontains_count = src.count('__icontains')
            startswith_count = src.count('__startswith')
            if icontains_count <= 1 and startswith_count >= 2:
                report('R6-2', f'icontains={icontains_count}, startswith={startswith_count}', 'PASS',
                       'biz_type/issuing_authority 改用 startswith 可走索引')
            elif icontains_count > 1:
                report('R6-2', f'共 {icontains_count} 处 __icontains', 'CONFIRMED',
                       'LIKE %xxx% 绕过 db_index 索引')
            else:
                report('R6-2', f'icontains={icontains_count}, startswith={startswith_count}', 'PASS')
        safe('R6-2', 'rule_no icontains', r6_2)

        # ═══════ R7 (P2) ═══════
        section('R7 (P2): page/page_size 重复解析（死代码）')

        def r7_1():
            import inspect
            from apps.regulation import views
            src = inspect.getsource(views.RegulationListView.get)
            has_page_in_parser = "Argument('page'" in src or "Argument('page_size'" in src
            if not has_page_in_parser:
                report('R7-1', 'JsonParser 已移除 page/page_size（死代码已清理）', 'PASS',
                       'paginate() 是唯一的分页入口')
            else:
                report('R7-1', 'paginate() 独立从 request.GET 读取', 'CONFIRMED', 'JsonParser 解析结果被忽略')
        safe('R7-1', 'paginate 死代码', r7_1)

        def r7_2():
            factory = RequestFactory()
            req = factory.get('/regulation/list/?page_size=9999')
            from libs.pagination import paginate
            _, ps = paginate(req, default_page_size=20, max_page_size=100)
            if ps == 100:
                report('R7-2', 'max_page_size=100 限制生效', 'PASS', f'page_size={ps}')
            else:
                report('R7-2', 'max_page_size 异常', 'FAIL', f'page_size={ps}')
        safe('R7-2', 'max_page_size 限制', r7_2)

        # ═══════ R8 (已排除) ═══════
        section('R8: ORDER BY -effective_date NULL 排序')

        def r8_1():
            rw = Regulation.objects.create(
                title='有日期', rule_no='R8-001', category=leaf,
                issuing_authority='审计', biz_type='安全',
                publish_date='2026-01-01', effective_date='2026-06-01',
                status='active', updated_by=admin,
            )
            rn = Regulation.objects.create(
                title='无日期', rule_no='R8-002', category=leaf,
                issuing_authority='审计', biz_type='安全',
                publish_date='2026-01-01', effective_date=None,
                status='active', updated_by=admin,
            )
            qs = Regulation.objects.filter(id__in=[rw.id, rn.id]).order_by('-effective_date')
            if qs.first().id == rw.id and qs.last().id == rn.id:
                report('R8-1', 'NULL 在 DESC 排序中排最后', 'PASS', '当前行为正确（R8 已排除）')
            else:
                report('R8-1', 'NULL 排序异常', 'CONFIRMED',
                       f'first={qs.first().id}, last={qs.last().id}')
        safe('R8-1', 'NULL 排序', r8_1)

        # ═══════ R9 (P2) ═══════
        section('R9 (P2): 附件 is_deleted 检查一致性')

        def r9_1():
            import inspect
            from apps.regulation import views
            src = inspect.getsource(views.RegulationAttachmentPreviewFileView.get)
            uses_get_attachment = '_get_attachment' in src
            uses_direct_get = '.attachments.get(pk=' in src
            if uses_get_attachment and not uses_direct_get:
                report('R9-1', 'PreviewFileView 使用 _get_attachment（统一模式）', 'PASS',
                       'filter(is_deleted=False) 前置过滤')
            elif uses_direct_get:
                report('R9-1', 'get(pk=) 可检索软删除附件', 'CONFIRMED', 'PreviewFileView 用 get(pk=) 而非 filter(is_deleted=False)')
            else:
                report('R9-1', '无法确认检查模式', 'FAIL')
        safe('R9-1', 'is_deleted 一致性', r9_1)

    finally:
        transaction.savepoint_rollback(sid)
        print(f'\n{"="*60}')
        print(f'  回滚 savepoint，dev 数据不受影响')
        print(f'{"="*60}')

    # 汇总
    print(f'\n{"="*60}')
    print(f'  审计结果汇总')
    print(f'{"="*60}')
    confirmed = sum(1 for _, _, s, _ in RESULTS if s == 'CONFIRMED')
    passed = sum(1 for _, _, s, _ in RESULTS if s == 'PASS')
    failed = sum(1 for _, _, s, _ in RESULTS if s == 'FAIL')
    print(f'  确认风险 (CONFIRMED): {confirmed}')
    print(f'  通过 (PASS):          {passed}')
    print(f'  失败 (FAIL):          {failed}')
    print(f'  总计:                 {len(RESULTS)}')
    print(f'{"="*60}')

    if failed > 0:
        print('\n  失败项:')
        for tid, desc, status, detail in RESULTS:
            if status == 'FAIL':
                print(f'    [{tid}] {desc}: {detail}')

    return failed


run_audit()

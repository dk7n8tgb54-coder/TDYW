#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""规章管理风险点验证脚本"""
import os, sys, time, traceback, threading
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django; django.setup()
from django.conf import settings
settings.ALLOWED_HOSTS = ['*']
from django.db import connection, transaction
from django.core.exceptions import FieldError
from apps.account.models import User
from apps.regulation.models import Regulation, RegulationCategory
from libs.idempotency import check_recent_duplicate

RESULTS = []
def report(tid, desc, st, det=''):
    icon = {'PASS':'\u2713','FAIL':'\u2717','SKIP':'\u2298','CONFIRMED':'\u26a0'}[st]
    RESULTS.append((tid, desc, st, det))
    print(f'  {icon} [{tid}] {desc}')
    for l in det.split('\n') if det else []:
        print(f'      {l}')
def safe(tid, desc, fn):
    try: fn()
    except Exception as e:
        report(tid, desc, 'FAIL', f'{type(e).__name__}: {e}')
        traceback.print_exc()
def make_user():
    u, _ = User.objects.get_or_create(username='risk_verify_reg', defaults={
        'nickname':'Risk Reg','password_hash':'x','access_token':'risk_verify_reg_token_32ch_',
        'tenant_id':'risk_verify_reg','is_supper':True,'last_ip':'127.0.0.1'})
    return u

def test_full_field_save():
    """P1: 规章无变更时全字段 save()"""
    from apps.regulation.views import RegulationDetailView
    import inspect
    src = inspect.getsource(RegulationDetailView.put)
    if 'if changed' not in src:
        report('REG-FULLSAVE','P1: 无变更全字段 save','CONFIRMED','无 if changed 分支')
        return
    lines = src.split('\n')
    in_else = bare = False
    for l in lines:
        if l.strip().startswith('else:'): in_else = True; continue
        if in_else:
            if '.save()' in l and 'update_fields' not in l:
                bare = True; break
    report('REG-FULLSAVE','P1: 无变更全字段 save','CONFIRMED' if bare else 'PASS',
           'else 分支有裸 save()' if bare else '')

def test_soft_deleted_orphan():
    """P2: 删除规章时只清理非软删除附件"""
    from apps.regulation.views import RegulationDetailView
    import inspect
    src = inspect.getsource(RegulationDetailView.delete)
    if 'is_deleted=False' in src:
        report('REG-ORPHAN','P2: 软删除附件清理遗漏','CONFIRMED',
               '只过滤 is_deleted=False，之前软删除的附件物理文件不清理')
    else:
        report('REG-ORPHAN','P2: 软删除附件清理遗漏','PASS','')

def test_upload_crash_window():
    """P2: 附件上传文件写入在事务外"""
    from apps.regulation.views import RegulationAttachmentUploadView
    import inspect
    src = inspect.getsource(RegulationAttachmentUploadView.post)
    lines = src.split('\n')
    su = next((i for i,l in enumerate(lines) if 'save_upload_file' in l), None)
    tx = next((i for i,l in enumerate(lines) if 'transaction.atomic' in l), None)
    if su is not None and tx is not None and su < tx:
        gap = [l for l in lines[su+1:tx] if l.strip() and not l.strip().startswith('#')]
        report('REG-UPLOAD','P2: 上传崩溃窗口','CONFIRMED',
               f'save_upload_file L{su+1} -> tx.atomic L{tx+1}, 中间{len(gap)}行可执行代码')
    else:
        report('REG-UPLOAD','P2: 上传崩溃窗口','PASS','')

def test_is_leaf_race():
    """P2: 分类 is_leaf 竞态"""
    from apps.regulation.views import CategoryDetailView
    import inspect
    src = inspect.getsource(CategoryDetailView.delete)
    has_leaf = 'is_leaf' in src
    has_sfu = 'select_for_update' in src
    if has_leaf and not has_sfu:
        report('REG-ISLEAF','P2: 分类 is_leaf 竞态','CONFIRMED',
               'is_leaf 检查-设置无 select_for_update 行锁')
    else:
        report('REG-ISLEAF','P2: 分类 is_leaf 竞态','PASS','')

def test_search_no_index():
    """P2: title__icontains 搜索无索引"""
    from apps.regulation.views import RegulationListView
    import inspect
    src = inspect.getsource(RegulationListView.get)
    if '__icontains' not in src:
        report('REG-SEARCH','P2: 搜索无索引','PASS','')
        return
    # 检查表是否存在
    table_name = Regulation._meta.db_table
    with connection.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=%s", [table_name])
        if cur.fetchone()[0] == 0:
            report('REG-SEARCH','P2: 搜索无索引','SKIP',f'表 {table_name} 不存在')
            return
        cur.execute(f"SHOW INDEX FROM {table_name} WHERE Column_name='title'")
        idx = cur.fetchall()
    if idx:
        report('REG-SEARCH','P2: 搜索无索引','CONFIRMED',
               'title 有索引但 __icontains 生成 LIKE %%xxx%% 无法利用 B+ 树')
    else:
        report('REG-SEARCH','P2: 搜索无索引','CONFIRMED','title 无索引，全表扫描')

def test_idempotency():
    """P0: check_recent_duplicate FieldError"""
    from apps.regulation.views import RegulationCreateView
    import inspect
    src = inspect.getsource(RegulationCreateView.post)
    if 'check_recent_duplicate' not in src:
        report('REG-IDEMPOTENCY','P0: check_recent_duplicate','PASS','未使用')
        return
    user = make_user()
    try:
        check_recent_duplicate(Regulation, {'title':'test_dup'}, window_seconds=30)
        report('REG-IDEMPOTENCY','P0: check_recent_duplicate','PASS','调用成功')
    except FieldError as e:
        report('REG-IDEMPOTENCY','P0: check_recent_duplicate FieldError','CONFIRMED',str(e))
    except Exception as e:
        report('REG-IDEMPOTENCY','P0: check_recent_duplicate','FAIL',f'{type(e).__name__}: {e}')

def test_concurrent_save():
    """P1: 并发编辑规章时 update_fields 防覆盖（REG-FULLSAVE 修复后验证）"""
    user = make_user()
    try:
        field_names = [f.name for f in Regulation._meta.fields]
        create_kwargs = {}
        if 'title' in field_names:
            create_kwargs['title'] = f'concurrent_test_{int(time.time())}'
        if 'rule_no' in field_names:
            create_kwargs['rule_no'] = f'CN-{int(time.time())}'

        # 检查表是否存在
        table_name = Regulation._meta.db_table
        with connection.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name=%s", [table_name])
            if cur.fetchone()[0] == 0:
                report('REG-CONCURRENT','P1: 并发 save 覆盖','SKIP',f'表 {table_name} 不存在')
                return

        # 1. 静态验证：源码中无 else 分支裸 save()
        from apps.regulation.views import RegulationDetailView
        import inspect
        src = inspect.getsource(RegulationDetailView.put)
        has_else_bare_save = False
        lines = src.split('\n')
        in_else = False
        for l in lines:
            if l.strip().startswith('else:'):
                in_else = True; continue
            if in_else:
                if '.save()' in l and 'update_fields' not in l:
                    has_else_bare_save = True; break
                if l.strip() and not l.startswith(' ') and not l.startswith('\t'):
                    break

        if has_else_bare_save:
            report('REG-CONCURRENT','P1: 并发 save 覆盖（未修复）','CONFIRMED',
                   '源码 else 分支仍有裸 save()')
            return

        # 2. 动态验证：两个 update_fields 并发编辑不互相覆盖
        reg = Regulation.objects.create(**create_kwargs)
        expected_title = f'{create_kwargs.get("title","")}_v1'
        expected_rule_no = f'{create_kwargs.get("rule_no","")}-v2'

        def edit1():
            if 'title' in field_names:
                reg.title = expected_title
                reg.save(update_fields=['title'])
        def edit2():
            if 'rule_no' in field_names:
                reg.rule_no = expected_rule_no
                reg.save(update_fields=['rule_no'])

        t1 = threading.Thread(target=edit1)
        t2 = threading.Thread(target=edit2)
        t1.start(); t2.start()
        t1.join(); t2.join()
        reg.refresh_from_db()

        title_ok = 'title' not in field_names or reg.title == expected_title
        rule_no_ok = 'rule_no' not in field_names or reg.rule_no == expected_rule_no

        if title_ok and rule_no_ok:
            report('REG-CONCURRENT','P1: 并发 save 覆盖（已修复）','PASS',
                   '源码已删除 else 裸 save()，两字段 update_fields 并发不互相覆盖\n'
                   f'  title={reg.title}, rule_no={reg.rule_no}')
        else:
            report('REG-CONCURRENT','P1: 并发 save 覆盖','CONFIRMED',
                   f'title_ok={title_ok}({reg.title} vs {expected_title}), rule_no_ok={rule_no_ok}')

        reg.delete()
    except Exception as e:
        report('REG-CONCURRENT','P1: 并发 save 覆盖','FAIL',f'{type(e).__name__}: {e}')
        traceback.print_exc()

if __name__ == '__main__':
    print('='*60)
    print('  规章管理（Regulation）风险点验证')
    print('='*60)
    safe('REG-FULLSAVE','P1: 无变更全字段 save', test_full_field_save)
    safe('REG-ORPHAN','P2: 软删除附件清理遗漏', test_soft_deleted_orphan)
    safe('REG-UPLOAD','P2: 上传崩溃窗口', test_upload_crash_window)
    safe('REG-ISLEAF','P2: 分类 is_leaf 竞态', test_is_leaf_race)
    safe('REG-SEARCH','P2: 搜索无索引', test_search_no_index)
    safe('REG-IDEMPOTENCY','P0: check_recent_duplicate', test_idempotency)
    safe('REG-CONCURRENT','P1: 并发全字段 save 覆盖', test_concurrent_save)
    print('\n'+'='*60)
    print('  结果汇总')
    print('='*60)
    p = sum(1 for _,_,s,_ in RESULTS if s=='PASS')
    c = sum(1 for _,_,s,_ in RESULTS if s=='CONFIRMED')
    f = sum(1 for _,_,s,_ in RESULTS if s=='FAIL')
    sk = sum(1 for _,_,s,_ in RESULTS if s=='SKIP')
    for tid,desc,st,_ in RESULTS:
        icon = {'PASS':'\u2713','FAIL':'\u2717','SKIP':'\u2298','CONFIRMED':'\u26a0'}[st]
        print(f'  {icon} [{tid}] {desc} -> {st}')
    print(f'\n  PASS: {p}  CONFIRMED: {c}  FAIL: {f}  SKIP: {sk}')

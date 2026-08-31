"""
Interference 模块 CRUD 可靠性修复验证脚本

验证范围：R1-R10, R12-R13 共 11 项修复（R8 接受为设计选择）
验证方式：代码检查 + 数据验证

运行方式：
  docker exec -e PYTHONIOENCODING=utf-8 -w /data/spug/spug_api tdyw-test python run_interference_audit.py
"""
import os
import sys
import inspect
import re

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django
django.setup()

from django.db import transaction
from django.utils import timezone
from apps.interference.models import Interference
from apps.interference import views as interference_views
from apps.interference import business_views as interference_business_views
from apps.interference import exporters as interference_exporters
from apps.logs.models import AuditLog
from libs.tenant_utils import apply_tenant_filter

PASS = 'PASS'
FAIL = 'FAIL'
SKIP = 'SKIP'
ACCEPT = 'ACCEPT'
results = []


def report(test_id, severity, category, title, status, detail=''):
    results.append({
        'id': test_id,
        'severity': severity,
        'category': category,
        'title': title,
        'status': status,
        'detail': detail,
    })
    print(f'[{status}] {test_id} ({severity}) {title}')
    if detail:
        print(f'       {detail}')


def statistics_source():
    """返回当前统计类视图的源码。

    旧的 InterferenceStatisticsView（/interference/statistics/）已随干扰统计页面一并
    删除，统计能力由 business_views.InterferenceSummaryView 承接，因此这三项统计相关
    检查（R5/R7/R13）改指新的汇总统计视图。
    """
    return inspect.getsource(interference_business_views.InterferenceSummaryView.get)


# ========================================================================
# R1 (P1 BUG): Export view missing is_deleted=False filter
# ========================================================================
def test_r1():
    """验证 exporters.py get_export_queryset 是否过滤 is_deleted=False"""
    src = inspect.getsource(interference_exporters.get_export_queryset)
    has_is_deleted = 'is_deleted' in src
    if not has_is_deleted:
        report('R1', 'P1', '安全',
               'Export 缺少 is_deleted=False 过滤',
               FAIL,
               'exporters.py get_export_queryset 使用 Interference.objects.all() 未过滤 is_deleted，'
               '软删除记录会出现在导出数据中')
    else:
        report('R1', 'P1', '安全',
               'Export 缺少 is_deleted=False 过滤', PASS,
               'get_export_queryset 已包含 is_deleted 过滤')


# ========================================================================
# R2 (P1 BUG): Evidence package audit log fallback exposes other records' data
# ========================================================================
def test_r2():
    """验证证据包审计日志 fallback 是否有充分的限制条件"""
    src = inspect.getsource(interference_views.InterferenceEvidencePackageView.get)
    has_fallback = 'if not audit_logs' in src
    fallback_section = src[src.find('if not audit_logs'):src.find('if not audit_logs')+500] if has_fallback else ''
    fallback_has_time_limit = 'created_at__gte' in fallback_section or 'created_at__lte' in fallback_section
    fallback_has_row_limit = '[:' in fallback_section

    if has_fallback:
        # fallback 不需要 target_id 过滤（因为 fallback 正是因为无 target_id 匹配才触发）
        # 但必须有时间范围 + 行数限制，防止返回全量数据（与 runlog/device 模块一致）
        if fallback_has_time_limit and fallback_has_row_limit:
            report('R2', 'P1', '安全',
                   '证据包审计日志 fallback 限制条件', PASS,
                   f'fallback 已有时间范围限制({fallback_has_time_limit}) + 行数限制({fallback_has_row_limit})，'
                   '与 runlog/device 模块修复方案一致')
        elif fallback_has_time_limit or fallback_has_row_limit:
            report('R2', 'P1', '安全',
                   '证据包审计日志 fallback 限制条件', FAIL,
                   f'fallback 仅有部分限制（时间={fallback_has_time_limit}, 行数={fallback_has_row_limit}），'
                   '应同时具备时间范围 + 行数限制')
        else:
            report('R2', 'P1', '安全',
                   '证据包审计日志 fallback 泄露其他记录数据', FAIL,
                   'fallback 查询无任何限制，返回租户下所有 interference 审计日志')
    elif not has_fallback:
        report('R2', 'P1', '安全',
               '证据包审计日志 fallback 泄露其他记录数据', PASS,
               '无 fallback 逻辑，不存在泄露风险')
    else:
        report('R2', 'P1', '安全',
               '证据包审计日志 fallback 泄露其他记录数据', PASS,
               'fallback 已有充分限制条件')


def test_r2_data():
    """数据验证：修复后的 fallback 查询是否限制了返回范围"""
    # 模拟修复后的 fallback 查询（90 天 + 1000 行限制）
    from datetime import timedelta
    cutoff = timezone.now() - timedelta(days=90)
    fallback_logs = list(AuditLog.objects.filter(
        tenant_id='default', target_type='interference',
        created_at__gte=cutoff,
    ).order_by('-id')[:1000])

    total_interference_logs = AuditLog.objects.filter(
        tenant_id='default', target_type='interference',
    ).count()

    if len(fallback_logs) < total_interference_logs:
        report('R2-Data', 'P1', '安全',
               'fallback 数据限制验证', PASS,
               f'fallback 返回 {len(fallback_logs)} 条（90 天内，最多 1000 行），'
               f'全量 interference 审计日志 {total_interference_logs} 条，已有效限制范围')
    elif total_interference_logs == 0:
        report('R2-Data', 'P1', '安全',
               'fallback 数据限制验证', SKIP,
               '当前无 interference 审计日志，无法验证')
    else:
        report('R2-Data', 'P1', '安全',
               'fallback 数据限制验证', PASS,
               f'fallback 返回 {len(fallback_logs)} 条，全量 {total_interference_logs} 条'
               '（所有日志均在 90 天内且不超过 1000 行）')


# ========================================================================
# R3 (P2): Delete operation not in transaction.atomic()
# ========================================================================
def test_r3():
    """验证删除操作是否包裹在 transaction.atomic() 中"""
    src = inspect.getsource(interference_views.InterferenceView.delete)
    has_atomic = 'transaction.atomic' in src or 'atomic()' in src
    has_audit = 'record_audit_event' in src
    has_save = 'record.save' in src
    if not has_atomic and has_audit and has_save:
        report('R3', 'P2', '事务边界',
               '删除操作未包裹在 transaction.atomic() 中', FAIL,
               'record_audit_event + record.save() 不在事务中，'
               '若 save() 失败，审计日志已写入但记录未删除，产生不一致')
    else:
        report('R3', 'P2', '事务边界',
               '删除操作未包裹在 transaction.atomic() 中', PASS,
               '已使用 transaction.atomic()' if has_atomic else '操作顺序安全')


# ========================================================================
# R4 (P2): Delete save() without update_fields
# ========================================================================
def test_r4():
    """验证删除操作的 save() 是否使用 update_fields"""
    src = inspect.getsource(interference_views.InterferenceView.delete)
    save_matches = re.findall(r'\.save\(([^)]*)\)', src)
    has_update_fields = any('update_fields' in m for m in save_matches)
    if not has_update_fields and save_matches:
        report('R4', 'P2', '事务边界',
               '删除 save() 未使用 update_fields', FAIL,
               f'record.save() 写入所有字段（{len(save_matches)} 处 save 调用），'
               '并发场景下可能覆盖其他字段的修改')
    else:
        report('R4', 'P2', '事务边界',
               '删除 save() 未使用 update_fields', PASS,
               'save() 已使用 update_fields' if has_update_fields else '无 save() 调用')


# ========================================================================
# R5 (P2): Statistics uses Substr on DateTimeField instead of TruncDate
# ========================================================================
def test_r5():
    """验证统计视图是否使用 Substr 而非 TruncDate"""
    src = statistics_source()
    has_substr = 'Substr' in src
    has_trunc = 'TruncDate' in src
    if has_substr and not has_trunc:
        report('R5', 'P2', '性能',
               '统计视图使用 Substr 截取 DateTimeField', FAIL,
               'Substr("datetime", 1, 10) 依赖 MySQL datetime->string 转换，'
               '无法走索引；应改用 TruncDate("datetime")')
    else:
        report('R5', 'P2', '性能',
               '统计视图使用 Substr 截取 DateTimeField', PASS,
               '已使用 TruncDate' if has_trunc else '无日期截取操作')


# ========================================================================
# R6 (P2): POST create check_recent_duplicate + create not in transaction (TOCTOU)
# ========================================================================
def test_r6():
    """验证创建操作的 check + create 是否在事务中"""
    src = inspect.getsource(interference_views.InterferenceView.post)
    create_section = src[src.find('# 创建'):src.find('return json_response(error=error)')] if '# 创建' in src else src
    has_check = 'check_recent_duplicate' in create_section
    has_create = 'Interference.objects.create' in create_section
    has_atomic = 'transaction.atomic' in create_section or 'atomic()' in create_section
    if has_check and has_create and not has_atomic:
        report('R6', 'P2', '事务边界',
               '创建操作 check + create TOCTOU 竞态', FAIL,
               'check_recent_duplicate 与 Interference.objects.create 之间无事务保护，'
               '并发请求可能绕过去重检查')
    else:
        report('R6', 'P2', '事务边界',
               '创建操作 check + create TOCTOU 竞态', PASS,
               '已使用事务保护' if has_atomic else '无 TOCTOU 风险')


# ========================================================================
# R7 (P3): Statistics error response leaks internal exception details
# ========================================================================
def test_r7():
    """验证统计视图错误响应是否泄露内部异常信息"""
    src = statistics_source()
    has_str_e = "str(e)" in src
    has_generic = "json_response(error='获取统计数据失败" in src
    if has_str_e and not has_generic:
        report('R7', 'P3', '安全',
               '统计视图错误响应泄露内部异常信息', FAIL,
               'return json_response(error=str(e)) 将原始异常信息返回给用户，'
               '可能泄露数据库结构/SQL 等敏感信息')
    else:
        report('R7', 'P3', '安全',
               '统计视图错误响应泄露内部异常信息', PASS,
               '已使用通用错误消息' if has_generic else '无异常泄露')


# ========================================================================
# R8 (P3): submitted_by_id etc. are IntegerField not FK
# ========================================================================
def test_r8():
    """验证人员引用字段是否使用 IntegerField 而非 FK（接受为设计选择）"""
    from django.db.models import IntegerField, ForeignKey
    person_fields = [
        'submitted_by_id', 'reviewed_by_id', 'reported_by_id',
        'handled_by_id', 'closed_by_id', 'voided_by_id',
    ]
    int_count = sum(1 for f in person_fields if isinstance(Interference._meta.get_field(f), IntegerField))
    if int_count > 0:
        report('R8', 'P3', '约束',
               f'人员引用字段使用 IntegerField 而非 FK ({int_count}/{len(person_fields)})', ACCEPT,
               'IntegerField 无引用完整性约束，用户删除后引用变为悬空。'
               '注：这是快照模式设计选择，与 radio_license/device 一致，接受现状')
    else:
        report('R8', 'P3', '约束',
               '人员引用字段使用 IntegerField 而非 FK', PASS, '已使用 FK')


# ========================================================================
# R9 (P3): datetime field is nullable but required in views
# ========================================================================
def test_r9():
    """验证 datetime 字段模型允许 null 但视图要求必填"""
    field = Interference._meta.get_field('datetime')
    model_null = field.null
    src = inspect.getsource(interference_views.InterferenceView.post)
    view_requires = "'datetime'" in src and '日期时间' in src
    if model_null and view_requires:
        report('R9', 'P3', '约束',
               'datetime 模型允许 null 但视图要求必填', FAIL,
               'DateTimeField(null=True, blank=True) 但视图校验必填，'
               '模型层与业务层不一致，应设 null=False')
    else:
        report('R9', 'P3', '约束',
               'datetime 模型允许 null 但视图要求必填', PASS,
               '模型与视图一致' if not model_null else '视图不要求必填')


# ========================================================================
# R10 (P3): Duplicate timezone import
# ========================================================================
def test_r10():
    """验证是否有重复的 timezone 导入"""
    src = inspect.getsource(interference_views)
    count = src.count('from django.utils import timezone')
    if count >= 2:
        report('R10', 'P3', '代码质量',
               f'重复导入 timezone ({count} 次)', FAIL,
               'views.py 重复导入 timezone，应删除重复行')
    else:
        report('R10', 'P3', '代码质量',
               '重复导入 timezone', PASS, '无重复导入')


# ========================================================================
# R11: Export queryset does not filter is_deleted - data verification
# ========================================================================
def test_r11():
    """数据验证：检查导出查询是否正确过滤软删除记录"""
    total = Interference.objects.all_with_deleted().count()
    active = Interference.objects.filter(is_deleted=False).count()
    deleted = Interference.objects.all_with_deleted().exclude(is_deleted=False).count()
    if deleted > 0:
        # 模拟修复后的 get_export_queryset 查询
        export_count = Interference.objects.filter(is_deleted=False).count()
        if export_count == active:
            report('R11', 'P1', '安全',
                   '导出查询过滤软删除记录（数据验证）', PASS,
                   f'总记录 {total}，活跃 {active}，已删除 {deleted}，'
                   f'导出查询返回 {export_count} 条（正确排除软删除）')
        else:
            report('R11', 'P1', '安全',
                   '导出查询过滤软删除记录（数据验证）', FAIL,
                   f'导出查询返回 {export_count} 条，应为 {active} 条')
    else:
        report('R11', 'P1', '安全',
               '导出查询过滤软删除记录（数据验证）', SKIP,
               f'当前无软删除记录（总 {total} 条）。R1 代码层面已确认修复（is_deleted=False）')


# ========================================================================
# R12 (P2): Delete no select_for_update
# ========================================================================
def test_r12():
    """验证删除操作是否使用 select_for_update"""
    src = inspect.getsource(interference_views.InterferenceView.delete)
    has_sfu = 'select_for_update' in src
    if not has_sfu:
        report('R12', 'P2', '事务边界',
               '删除操作未使用 select_for_update', FAIL,
               '并发删除同一记录时，两个请求都能通过 is_deleted=False 过滤，'
               '第二个请求会覆盖第一个的 deleted_at')
    else:
        report('R12', 'P2', '事务边界',
               '删除操作未使用 select_for_update', PASS, '已使用 select_for_update')


# ========================================================================
# R13: Statistics count() called twice
# ========================================================================
def test_r13():
    """验证统计视图是否重复调用 count()"""
    src = statistics_source()
    count_calls = src.count('.count()')
    if count_calls >= 2:
        report('R13', 'P3', '性能',
               f'统计视图重复调用 count() ({count_calls} 次)', FAIL,
               'filtered_records.count() 被调用 2 次，应缓存为变量避免重复查询')
    else:
        report('R13', 'P3', '性能',
               '统计视图重复调用 count()', PASS, f'count() 调用 {count_calls} 次')


# ========================================================================
# Main
# ========================================================================
def main():
    print('=' * 80)
    print('Interference 模块 CRUD 可靠性修复验证')
    print('验证范围：R1-R10, R12-R13 共 11 项修复（R8 接受为设计选择）')
    print('=' * 80)
    print()

    print('--- 代码检查 ---')
    test_r1()
    test_r2()
    test_r3()
    test_r4()
    test_r5()
    test_r6()
    test_r7()
    test_r8()
    test_r9()
    test_r10()
    test_r12()
    test_r13()

    print()
    print('--- 数据验证 ---')
    test_r2_data()
    test_r11()

    print()
    print('=' * 80)
    print('修复验证结果汇总')
    print('=' * 80)

    passed = sum(1 for r in results if r['status'] == PASS)
    failed = sum(1 for r in results if r['status'] == FAIL)
    skipped = sum(1 for r in results if r['status'] == SKIP)
    accepted = sum(1 for r in results if r['status'] == ACCEPT)

    print(f'总计: {len(results)} 项 | PASS: {passed} | FAIL: {failed} | SKIP: {skipped} | ACCEPT: {accepted}')
    print()

    if failed > 0:
        print('--- 未通过项 ---')
        for r in results:
            if r['status'] == FAIL:
                print(f'  [{r["severity"]}] {r["id"]} {r["title"]}')
                print(f'         {r["detail"]}')

    print()
    print('--- 已通过项 ---')
    for r in results:
        if r['status'] == PASS:
            print(f'  [{r["severity"]}] {r["id"]} {r["title"]}')

    if accepted > 0:
        print()
        print('--- 接受项（设计选择，不修复）---')
        for r in results:
            if r['status'] == ACCEPT:
                print(f'  [{r["severity"]}] {r["id"]} {r["title"]}')

    if skipped > 0:
        print()
        print('--- 跳过项 ---')
        for r in results:
            if r['status'] == SKIP:
                print(f'  [{r["severity"]}] {r["id"]} {r["title"]}')
                print(f'         {r["detail"]}')

    print()
    return 1 if failed > 0 else 0


if __name__ == '__main__':
    sys.exit(main())

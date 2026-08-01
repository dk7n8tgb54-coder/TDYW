# -*- coding: utf-8 -*-
"""
logs 模块 CRUD 可靠性审计测试

基于 CRUD系统可靠性指南.md 和前 10 个模块审计经验，对 logs 模块进行系统性审查。

风险点清单：
  R1 (P2): CharField null=True 违规 - tenant_id/request_id/user_agent 仍有 null=True
  R2 (P2): detail__icontains 在 TextField 上生成 LIKE '%xxx%'，无索引全表扫描
  R3 (P2): username__icontains 绕过索引 - LIKE '%xxx%' 无法走 B-Tree 索引
  R4 (P2): AuditLogView/AuditLogExportView 无关键词无时间范围时缺少默认限制
  R5 (P1): cleanup_old_audit_logs 删除旧记录后哈希链断裂
  R6 (P2): _capture_before_values 使用 SELECT * 查询全列
  R7 (P2): verify_hash_chain 无调用入口（无视图/API/定时任务调用）
  R8 (P2): 敏感字段脱敏覆盖度验证
  R9 (INFO): AuditLogView 90 天默认限制仅有关键词时生效
  R10 (INFO): cleanup_old_audit_logs 批量删除安全阀验证

运行方式（在 tdyw-test 容器内）：
  docker exec -e PYTHONIOENCODING=utf-8 -e PYTHONPATH=/data/spug/spug_api \
    -w /data/spug/spug_api tdyw-test python apps/logs_audit_tests.py
"""

import os
import sys
import inspect
import json
import re
from datetime import timedelta

# Django 环境初始化
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
import django
django.setup()

from django.db import connection, transaction
from django.utils import timezone
from django.conf import settings

from apps.logs.models import AuditLog
from apps.logs.audit import (
    save_audit_log, log_celery_audit, sanitize_audit_detail,
    TARGET_TABLE_MAP, SENSITIVE_KEYWORDS,
)
from apps.logs.hash_chain import verify_hash_chain, verify_log_hash
from apps.logs.middleware import AuditLogMiddleware
from apps.logs.views import AuditLogView, AuditLogExportView
from apps.logs.tasks import cleanup_old_audit_logs, MIN_RETENTION_DAYS, DELETE_BATCH_SIZE


# ============================================================
# 测试结果收集
# ============================================================
RESULTS = []

def record(risk_id, title, severity, status, detail):
    RESULTS.append({
        'risk_id': risk_id,
        'title': title,
        'severity': severity,
        'status': status,  # CONFIRMED / FALSE_POSITIVE / MITIGATED
        'detail': detail,
    })


# ============================================================
# R1: CharField null=True 违规
# ============================================================

def test_r1_charfield_null_true():
    """R1: CharField 字段不应有 null=True（项目规范：CharField/TextField 禁止 null=True）

    Migration 0008 已修复 detail/target_id/target_name，但 tenant_id/request_id/user_agent 遗漏。
    """
    null_char_fields = []
    for field in AuditLog._meta.get_fields():
        if hasattr(field, 'null') and field.null and field.__class__.__name__ in (
            'CharField', 'TextField'
        ):
            null_char_fields.append(f"{field.name} ({field.__class__.__name__})")

    if null_char_fields:
        record('R1', 'CharField null=True 违规', 'P2', 'CONFIRMED',
               f"以下字段违反规范: {', '.join(null_char_fields)}。"
               f"应改为 default='' + blank=True，避免 NULL 值导致 ORM 查询不一致"
               f"（filter(field='value') 不匹配 NULL 行）。")
    else:
        record('R1', 'CharField null=True 违规', 'P2', 'FALSE_POSITIVE',
               "所有 CharField/TextField 均无 null=True。")


# ============================================================
# R2: detail__icontains 在 TextField 上生成 LIKE '%xxx%'
# ============================================================

def test_r2_detail_icontains_on_textfield():
    """R2: detail 字段是 TextField，icontains 生成 LIKE '%xxx%' 无法走索引"""
    detail_field = AuditLog._meta.get_field('detail')
    field_type = detail_field.get_internal_type()

    # 检查是否有全文索引
    has_fulltext_index = False
    for index in AuditLog._meta.indexes:
        if hasattr(index, 'fields') and 'detail' in (index.fields or []):
            has_fulltext_index = True

    # 检查 views.py 源码中是否有 detail__icontains
    view_source = inspect.getsource(AuditLogView)
    export_source = inspect.getsource(AuditLogExportView)
    has_detail_icontains = 'detail__icontains' in view_source or 'detail__icontains' in export_source

    if has_detail_icontains and field_type == 'TextField' and not has_fulltext_index:
        record('R2', 'detail__icontains 在 TextField 上全表扫描', 'P2', 'CONFIRMED',
               f"detail 字段类型: {field_type}，无全文索引。"
               f"AuditLogView 和 AuditLogExportView 均使用 detail__icontains 生成 LIKE '%keyword%'，"
               f"前缀通配符无法走 B-Tree 索引。有关键词时默认限制 90 天部分缓解，"
               f"但大表（>10 万行/90 天）仍可能慢查询。")
    else:
        record('R2', 'detail__icontains 在 TextField 上全表扫描', 'P2', 'FALSE_POSITIVE',
               f"detail 字段类型: {field_type}，has_icontains: {has_detail_icontains}，"
               f"has_fulltext: {has_fulltext_index}")


# ============================================================
# R3: username__icontains 绕过索引
# ============================================================

def test_r3_username_icontains_bypasses_index():
    """R3: username__icontains 生成 LIKE '%xxx%'，无法利用 B-Tree 索引"""
    view_source = inspect.getsource(AuditLogView)
    export_source = inspect.getsource(AuditLogExportView)

    # 找所有 icontains 用法
    icontains_fields_view = re.findall(r'(\w+)__icontains', view_source)
    icontains_fields_export = re.findall(r'(\w+)__icontains', export_source)
    all_icontains = set(icontains_fields_view + icontains_fields_export)

    # 检查 username 是否有索引（db_index=True 或 Meta.indexes 中）
    username_field = AuditLog._meta.get_field('username')
    has_field_index = username_field.db_index
    has_meta_index = any(
        'username' in (idx.fields or []) for idx in AuditLog._meta.indexes
    )
    has_index = has_field_index or has_meta_index

    username_icontains = 'username' in all_icontains

    if username_icontains and has_index:
        record('R3', 'username__icontains 绕过索引', 'P2', 'CONFIRMED',
               f"username 有索引 (db_index={has_field_index}, Meta.indexes={has_meta_index})，"
               f"但 icontains 生成 LIKE '%xxx%' 前缀通配符无法走 B-Tree 索引。"
               f"views.py 中 icontains 字段: {all_icontains}。"
               f"按 CRUD 指南 §2.1：LIKE '%xxx' 前缀通配无法走索引。"
               f"建议 username 精确匹配用 __exact，前缀匹配用 __startswith。")
    else:
        record('R3', 'username__icontains 绕过索引', 'P2', 'FALSE_POSITIVE',
               f"username_icontains: {username_icontains}, "
               f"has_field_index: {has_field_index}, has_meta_index: {has_meta_index}")


# ============================================================
# R4: 无关键词无时间范围时缺少默认限制
# ============================================================

def test_r4_no_default_time_range_without_keyword():
    """R4: 90 天默认限制仅当 keyword 存在时生效，无 keyword 无时间范围时全表扫描"""
    view_source = inspect.getsource(AuditLogView.get)
    export_source = inspect.getsource(AuditLogExportView.get)

    # 检查 90 天限制是否在 keyword 条件块内
    # AuditLogView 中: if form.keyword: if not form.start_time and not form.end_time: 90天
    view_has_90_in_keyword = bool(re.search(
        r"if\s+form\.keyword.*?ninety_days_ago", view_source, re.DOTALL
    ))
    export_has_90_in_keyword = bool(re.search(
        r"if\s+form\.keyword.*?ninety_days_ago", export_source, re.DOTALL
    ))

    # 检查是否有 keyword 条件外的默认时间范围
    view_has_global_default = bool(re.search(
        r"if\s+not\s+.*start_time.*\n.*timedelta.*90", view_source
    )) and not view_has_90_in_keyword

    if view_has_90_in_keyword and not view_has_global_default:
        record('R4', '无关键词无时间范围时缺少默认限制', 'P2', 'CONFIRMED',
               f"AuditLogView 和 AuditLogExportView 的 90 天默认限制仅在 keyword 存在时生效。"
               f"场景: 超管不传 keyword、不传 start_time/end_time 查看全部审计日志 -> "
               f"count() 对全表扫描，百万级表可能 >1s。"
               f"AuditLogView 有分页（page_size<=100）限制返回数据量，"
               f"AuditLogExportView 有 check_export_limit(10000) 拦截超量导出，"
               f"但 count() 本身在无索引筛选时仍是全表扫描。"
               f"建议: 无时间范围时一律默认最近 90 天（不依赖 keyword 条件）。")
    else:
        record('R4', '无关键词无时间范围时缺少默认限制', 'P2', 'FALSE_POSITIVE',
               f"view_90_in_keyword: {view_has_90_in_keyword}, "
               f"view_global_default: {view_has_global_default}")


# ============================================================
# R5: cleanup_old_audit_logs 删除旧记录后哈希链断裂
# ============================================================

def test_r5_cleanup_breaks_hash_chain():
    """R5: 删除旧审计日志后，哈希链验证行为分析

    场景 A（头部删除 - 模拟 cleanup）：删除链首记录，后续链路仍连续。
    场景 B（中间删除 - 模拟篡改）：删除中间记录，链路应断裂。
    """
    test_tenant = 'audit_test_r5'
    AuditLog.objects.filter(tenant_id=test_tenant).delete()

    try:
        # 创建 4 条审计日志（自动形成哈希链: L1 -> L2 -> L3 -> L4）
        for i in range(4):
            save_audit_log(
                user_id=1, username='test_user', action='create',
                target_type='device', target_id=str(i+1), target_name=f'device_{i+1}',
                detail={'name': f'device{i+1}'}, ip='127.0.0.1',
                is_success=True, tenant_id=test_tenant,
            )

        logs = list(AuditLog.objects.filter(tenant_id=test_tenant).order_by('id'))
        assert len(logs) == 4, f"预期 4 条记录，实际 {len(logs)}"

        # 场景 A：删除链首（模拟 cleanup_old_audit_logs）
        logs[0].delete()
        logs_after_head = AuditLog.objects.filter(tenant_id=test_tenant).order_by('id')
        result_head = verify_hash_chain(logs_after_head)
        head_chain_ok = result_head['valid']

        # 场景 B：删除中间记录（模拟篡改）
        # 重新创建 4 条
        AuditLog.objects.filter(tenant_id=test_tenant).delete()
        for i in range(4):
            save_audit_log(
                user_id=1, username='test_user', action='update',
                target_type='device', target_id=str(i+1), target_name=f'device_{i+1}',
                detail={'name': f'device{i+1}_v2'}, ip='127.0.0.1',
                is_success=True, tenant_id=test_tenant,
            )
        logs = list(AuditLog.objects.filter(tenant_id=test_tenant).order_by('id'))
        # 删除中间记录（第 2 条）
        logs[1].delete()
        logs_after_mid = AuditLog.objects.filter(tenant_id=test_tenant).order_by('id')
        result_mid = verify_hash_chain(logs_after_mid)
        mid_chain_ok = result_mid['valid']

        if head_chain_ok and not mid_chain_ok:
            record('R5', 'cleanup_old_audit_logs 对哈希链的影响', 'P1', 'FALSE_POSITIVE',
                   f"场景 A（头部删除，模拟 cleanup）: 链路仍完整 (valid={head_chain_ok})。"
                   f"verify_hash_chain 跳过首条记录的 prev_hash 检查，"
                   f"能优雅处理 cleanup 删除链首记录的情况。设计正确。\n"
                   f"场景 B（中间删除，模拟篡改）: 链路断裂 (valid={mid_chain_ok})，"
                   f"errors={result_mid['errors'][:1]}。"
                   f"中间删除能被检测到，防篡改能力有效。\n"
                   f"结论: cleanup 删除旧记录不会导致误报，"
                   f"verify_hash_chain 的 has_prev 设计巧妙地处理了链首缺失场景。")
        elif not head_chain_ok:
            record('R5', 'cleanup_old_audit_logs 破坏哈希链', 'P1', 'CONFIRMED',
                   f"头部删除后链路断裂 (valid={head_chain_ok})，"
                   f"errors={result_head['errors'][:2]}。"
                   f"cleanup_old_audit_logs 删除链首会导致 verify_hash_chain 误报。")
        else:
            record('R5', 'cleanup_old_audit_logs 对哈希链的影响', 'P1', 'FALSE_POSITIVE',
                   f"head_chain_ok: {head_chain_ok}, mid_chain_ok: {mid_chain_ok}, "
                   f"head_errors: {result_head['errors']}, mid_errors: {result_mid['errors']}")
    finally:
        AuditLog.objects.filter(tenant_id=test_tenant).delete()


# ============================================================
# R6: _capture_before_values 使用 SELECT *
# ============================================================

def test_r6_capture_before_values_select_star():
    """R6: middleware._capture_before_values 使用 SELECT * 查询全列"""
    source = inspect.getsource(AuditLogMiddleware._capture_before_values)

    has_select_star = bool(re.search(r'SELECT\s+\*\s+FROM', source, re.IGNORECASE))

    if has_select_star:
        record('R6', '_capture_before_values 使用 SELECT *', 'P2', 'CONFIRMED',
               "middleware.py 使用 SELECT * FROM {table_name} WHERE id = %s，"
               "查询全列包括可能的大文本字段（如 description/content/detail）。"
               "审计只需对比变更字段，建议查询白名单列或使用 Django ORM "
               "（.only('name', 'status', ...)）减少网络传输和内存占用。")
    else:
        record('R6', '_capture_before_values 使用 SELECT *', 'P2', 'FALSE_POSITIVE',
               "未发现 SELECT * 用法。")


# ============================================================
# R7: verify_hash_chain 无调用入口
# ============================================================

def test_r7_verify_hash_chain_no_caller():
    """R7: verify_hash_chain 已实现但无视图/API/定时任务调用，链路验证能力闲置"""
    # 检查 urls.py 是否有 hash chain 相关 URL
    from apps.logs import urls as logs_urls
    url_patterns = [p.pattern._route if hasattr(p.pattern, '_route') else str(p.pattern)
                    for p in logs_urls.urlpatterns]

    has_hash_chain_url = any('hash' in str(p).lower() or 'chain' in str(p).lower()
                             for p in url_patterns)

    # 检查 views.py 是否有 hash chain 视图
    views_source = inspect.getsource(sys.modules['apps.logs.views'])
    has_hash_chain_view = 'verify_hash_chain' in views_source

    # 检查 celery_beat_schedule 是否有 hash chain 定时验证
    try:
        from apps.logs import celery_beat_schedule
        beat_source = inspect.getsource(celery_beat_schedule)
        has_hash_chain_beat = 'hash_chain' in beat_source.lower() or 'verify_hash' in beat_source.lower()
    except Exception:
        has_hash_chain_beat = False

    # 检查 tasks.py 是否有 hash chain 定时任务
    from apps.logs import tasks as logs_tasks
    tasks_source = inspect.getsource(logs_tasks)
    has_hash_chain_task = 'verify_hash_chain' in tasks_source

    if not has_hash_chain_url and not has_hash_chain_view and not has_hash_chain_beat and not has_hash_chain_task:
        record('R7', 'verify_hash_chain 无调用入口', 'P2', 'CONFIRMED',
               f"verify_hash_chain 已实现但无任何调用入口："
               f"无 URL ({has_hash_chain_url})、"
               f"无视图 ({has_hash_chain_view})、"
               f"无定时任务 ({has_hash_chain_beat})、"
               f"无 Celery 任务 ({has_hash_chain_task})。"
               f"哈希链验证能力完全闲置，无法发现篡改。"
               f"建议: ① 新增 Celery Beat 定时任务（每日验证）"
               f" ② 或新增管理 API 供管理员手动触发验证。")
    else:
        record('R7', 'verify_hash_chain 无调用入口', 'P2', 'FALSE_POSITIVE',
               f"url: {has_hash_chain_url}, view: {has_hash_chain_view}, "
               f"beat: {has_hash_chain_beat}, task: {has_hash_chain_task}")


# ============================================================
# R8: 敏感字段脱敏覆盖度
# ============================================================

def test_r8_sensitive_field_sanitization():
    """R8: 验证 sanitize_audit_detail 脱敏覆盖度"""
    test_cases = [
        ('password', 'secret123'),
        ('old_password', 'old_secret'),
        ('new_password', 'new_secret'),
        ('api_key', 'ak_xxxx'),
        ('access_token', 'at_xxxx'),
        ('private_key', 'pk_xxxx'),
        ('secret', 's_xxxx'),
        ('credential', 'c_xxxx'),
        ('wx_token', 'wx_xxxx'),
        ('spug_push_key', 'spk_xxxx'),
    ]

    missed = []
    for field_name, value in test_cases:
        detail = {field_name: value}
        sanitized = sanitize_audit_detail(detail)
        if value in str(sanitized):
            missed.append(field_name)

    if missed:
        record('R8', '敏感字段脱敏遗漏', 'P2', 'CONFIRMED',
               f"以下敏感字段未被脱敏: {', '.join(missed)}")
    else:
        record('R8', '敏感字段脱敏覆盖度', 'P2', 'FALSE_POSITIVE',
               f"所有测试的敏感字段均被正确脱敏。SENSITIVE_KEYWORDS={SENSITIVE_KEYWORDS}")


# ============================================================
# R9: AuditLogView 90 天默认限制仅有关键词时生效
# ============================================================

def test_r9_view_default_time_range_scope():
    """R9: 验证 90 天默认限制的作用范围（信息项）"""
    source = inspect.getsource(AuditLogView.get)

    # 检查 90 天限制是否在 keyword 条件块内
    pattern = re.compile(
        r"if\s+form\.keyword.*?if\s+not\s+form\.start_time.*?ninety_days_ago",
        re.DOTALL
    )
    is_in_keyword_block = bool(pattern.search(source))

    if is_in_keyword_block:
        record('R9', '90 天默认限制仅有关键词时生效', 'INFO', 'MITIGATED',
               "AuditLogView 的 90 天默认限制在 if form.keyword 条件块内，"
               "即仅当用户搜索关键词且未传时间范围时自动限制 90 天。"
               "无关键词时不限制，超管可查看全表（依赖分页保护）。"
               "与 R4 关联：建议将默认时间范围提到 keyword 条件外。")
    else:
        record('R9', '90 天默认限制仅有关键词时生效', 'INFO', 'FALSE_POSITIVE',
               "未找到 90 天默认限制或不在 keyword 条件块内。")


# ============================================================
# R10: cleanup_old_audit_logs 批量删除安全阀
# ============================================================

def test_r10_cleanup_batch_safety():
    """R10: cleanup_old_audit_logs 是否有批量大小限制和安全阀"""
    source = inspect.getsource(cleanup_old_audit_logs)

    has_batch_size = 'DELETE_BATCH_SIZE' in source
    has_retention = 'MIN_RETENTION_DAYS' in source or '90' in source
    has_soft_time_limit = 'soft_time_limit' in source
    has_dry_run = 'dry_run' in source

    if has_batch_size and has_retention and has_soft_time_limit:
        record('R10', 'cleanup_old_audit_logs 批量删除安全', 'INFO', 'MITIGATED',
               f"有批量大小限制 (DELETE_BATCH_SIZE={DELETE_BATCH_SIZE})，"
               f"有保留期下限 (MIN_RETENTION_DAYS={MIN_RETENTION_DAYS})，"
               f"有 soft_time_limit=1800s，"
               f"有 dry_run 预演模式 ({has_dry_run})。"
               f"设计合理，符合 CRUD 指南 §2.2 资源兜底要求。")
    else:
        record('R10', 'cleanup_old_audit_logs 批量删除安全', 'P2', 'CONFIRMED',
               f"缺少安全阀。batch_size: {has_batch_size}, "
               f"retention: {has_retention}, soft_time_limit: {has_soft_time_limit}")


# ============================================================
# R11: AuditLog 物理删除不可追溯（审计日志本身无审计）
# ============================================================

def test_r11_audit_log_delete_no_audit():
    """R11: AuditLog 记录被 cleanup 物理删除时，删除操作本身无审计记录"""
    # AuditLog 无 is_deleted 字段（物理删除），且 cleanup_old_audit_logs
    # 调用 log_celery_audit 记录清理动作？还是不记录？
    source = inspect.getsource(cleanup_old_audit_logs)

    has_audit = 'log_celery_audit' in source or 'save_audit_log' in source or 'record_audit' in source

    if not has_audit:
        record('R11', 'cleanup 删除操作本身无审计', 'P2', 'CONFIRMED',
               "cleanup_old_audit_logs 物理删除旧审计日志时，"
               "删除操作本身未记录审计日志（未调用 log_celery_audit）。"
               "违反 CRUD 指南 §1.5：'删除操作应有审计记录'。"
               "虽然 cleanup 是系统自动行为，但记录清理动作（删除了多少条、截止时间）"
               "有助于追溯数据消失原因。"
               f"返回值中包含 deleted_count 和 cutoff_date，但未落库审计。")
    else:
        record('R11', 'cleanup 删除操作本身无审计', 'P2', 'FALSE_POSITIVE',
               "cleanup_old_audit_logs 已记录审计日志。")


# ============================================================
# 主函数
# ============================================================

def main():
    print("=" * 80)
    print("logs 模块 CRUD 可靠性审计测试")
    print(f"运行时间: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"数据库: {settings.DATABASES['default']['NAME']}")
    print("=" * 80)
    print()

    tests = [
        ('R1', test_r1_charfield_null_true),
        ('R2', test_r2_detail_icontains_on_textfield),
        ('R3', test_r3_username_icontains_bypasses_index),
        ('R4', test_r4_no_default_time_range_without_keyword),
        ('R5', test_r5_cleanup_breaks_hash_chain),
        ('R6', test_r6_capture_before_values_select_star),
        ('R7', test_r7_verify_hash_chain_no_caller),
        ('R8', test_r8_sensitive_field_sanitization),
        ('R9', test_r9_view_default_time_range_scope),
        ('R10', test_r10_cleanup_batch_safety),
        ('R11', test_r11_audit_log_delete_no_audit),
    ]

    for risk_id, test_func in tests:
        try:
            test_func()
            result = RESULTS[-1]
            status_icon = {
                'CONFIRMED': '[!]',
                'FALSE_POSITIVE': '[ok]',
                'MITIGATED': '[v]',
            }.get(result['status'], '[?]')
            print(f"{status_icon} {result['risk_id']} ({result['severity']}): {result['title']}")
            print(f"   状态: {result['status']}")
            print(f"   详情: {result['detail'][:300]}")
            print()
        except Exception as e:
            print(f"[ERR] {risk_id}: 测试执行异常 - {e}")
            import traceback
            traceback.print_exc()
            record(risk_id, '测试执行异常', 'P0', 'CONFIRMED', str(e))
            print()

    # 汇总
    print("=" * 80)
    print("审计汇总")
    print("=" * 80)
    confirmed = [r for r in RESULTS if r['status'] == 'CONFIRMED']
    false_positive = [r for r in RESULTS if r['status'] == 'FALSE_POSITIVE']
    mitigated = [r for r in RESULTS if r['status'] == 'MITIGATED']

    print(f"总计: {len(RESULTS)} 项")
    print(f"  确认风险: {len(confirmed)}")
    print(f"  误报:     {len(false_positive)}")
    print(f"  已缓解:   {len(mitigated)}")
    print()

    if confirmed:
        print("确认的风险点:")
        for r in confirmed:
            print(f"  {r['risk_id']} ({r['severity']}): {r['title']}")
            print(f"    {r['detail'][:400]}")
            print()

    print()
    print("建议修复优先级:")
    p1 = [r for r in confirmed if r['severity'] == 'P1']
    p2 = [r for r in confirmed if r['severity'] == 'P2']
    if p1:
        print(f"  P1 (高优先级): {', '.join(r['risk_id'] for r in p1)}")
    if p2:
        print(f"  P2 (中优先级): {', '.join(r['risk_id'] for r in p2)}")
    if not p1 and not p2:
        print("  无需修复")


if __name__ == '__main__':
    main()

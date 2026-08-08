# -*- coding: utf-8 -*-
"""
数据库结构与数据质量统一审计入口

通过 Django manage.py shell 执行，只做只读查询。
用法:
  cat audit_database.py | docker exec -i -e PYTHONIOENCODING=utf-8 \
    -w /data/spug/spug_api tdyw-test python manage.py shell

输出: JSON 格式审计结果
"""
import json
import sys
from collections import defaultdict
from django.db import connection


def q(sql):
    """执行只读查询"""
    with connection.cursor() as cur:
        cur.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
    return cols, rows


def check_tables():
    """1. 表清单"""
    cols, rows = q("""
        SELECT TABLE_NAME, TABLE_ROWS, ENGINE, TABLE_COLLATION
        FROM information_schema.TABLES
        WHERE TABLE_SCHEMA = DATABASE() ORDER BY TABLE_NAME
    """)
    return [dict(zip(cols, r)) for r in rows]


def check_columns():
    """2. 列信息"""
    cols, rows = q("""
        SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE,
               COLUMN_DEFAULT, COLUMN_KEY, EXTRA
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
        ORDER BY TABLE_NAME, ORDINAL_POSITION
    """)
    return [dict(zip(cols, r)) for r in rows]


def check_indexes():
    """3. 索引信息"""
    cols, rows = q("""
        SELECT TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX, COLUMN_NAME,
               NON_UNIQUE, INDEX_TYPE
        FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA = DATABASE()
        ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX
    """)
    return [dict(zip(cols, r)) for r in rows]


def check_constraints():
    """4. 约束信息"""
    cols, rows = q("""
        SELECT TABLE_NAME, CONSTRAINT_NAME, CONSTRAINT_TYPE
        FROM information_schema.TABLE_CONSTRAINTS
        WHERE TABLE_SCHEMA = DATABASE() ORDER BY TABLE_NAME
    """)
    return [dict(zip(cols, r)) for r in rows]


def check_foreign_keys():
    """5. 外键信息"""
    cols, rows = q("""
        SELECT TABLE_NAME, COLUMN_NAME, CONSTRAINT_NAME,
               REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME
        FROM information_schema.KEY_COLUMN_USAGE
        WHERE TABLE_SCHEMA = DATABASE()
          AND REFERENCED_TABLE_NAME IS NOT NULL
        ORDER BY TABLE_NAME
    """)
    return [dict(zip(cols, r)) for r in rows]


def check_migrations():
    """6. 迁移状态"""
    cols, rows = q("SELECT app, name, applied FROM django_migrations ORDER BY app, name")
    return [dict(zip(cols, r)) for r in rows]


def check_permissions():
    """7. 权限数据"""
    cols, rows = q("SELECT id, content_type_id, codename, name FROM auth_permission ORDER BY id")
    return [dict(zip(cols, r)) for r in rows]


def check_content_types():
    """8. Content Type"""
    cols, rows = q("SELECT app_label, model FROM django_content_type ORDER BY app_label, model")
    return [dict(zip(cols, r)) for r in rows]


def check_tenant_null(columns, tables):
    """9. tenant_id NULL 检查"""
    business = [t for t in tables
                if not t['TABLE_NAME'].startswith('django_')
                and not t['TABLE_NAME'].startswith('auth_')
                and t['TABLE_NAME'] != 'django_session'
                and not t['TABLE_NAME'].startswith('django_celery')]
    checks = []
    for t in business:
        tn = t['TABLE_NAME']
        has_tenant = any(c['TABLE_NAME'] == tn and c['COLUMN_NAME'] == 'tenant_id'
                         for c in columns)
        if has_tenant:
            try:
                _, r2 = q("SELECT COUNT(*), SUM(CASE WHEN tenant_id IS NULL THEN 1 ELSE 0 END) FROM `%s`" % tn)
                checks.append({'table': tn, 'total': r2[0][0], 'null_tenant': r2[0][1]})
            except Exception as e:
                checks.append({'table': tn, 'error': str(e)})
    return checks


def check_soft_delete(columns, tables):
    """10. is_deleted 统计"""
    business = [t for t in tables
                if not t['TABLE_NAME'].startswith('django_')
                and not t['TABLE_NAME'].startswith('auth_')
                and t['TABLE_NAME'] != 'django_session'
                and not t['TABLE_NAME'].startswith('django_celery')]
    checks = []
    for t in business:
        tn = t['TABLE_NAME']
        has_sd = any(c['TABLE_NAME'] == tn and c['COLUMN_NAME'] == 'is_deleted'
                     for c in columns)
        if has_sd:
            try:
                _, r2 = q("SELECT COUNT(*), SUM(CASE WHEN is_deleted=1 THEN 1 ELSE 0 END) FROM `%s`" % tn)
                checks.append({'table': tn, 'total': r2[0][0], 'deleted': r2[0][1]})
            except Exception as e:
                checks.append({'table': tn, 'error': str(e)})
    return checks


def check_orphans(fks):
    """11. 孤儿数据检查"""
    checks = []
    for fk in fks:
        tn, cn = fk['TABLE_NAME'], fk['COLUMN_NAME']
        rtn, rcn = fk['REFERENCED_TABLE_NAME'], fk['REFERENCED_COLUMN_NAME']
        try:
            _, r2 = q(
                "SELECT COUNT(*) FROM `%s` t1 LEFT JOIN `%s` t2 "
                "ON t1.`%s`=t2.`%s` WHERE t1.`%s` IS NOT NULL AND t2.`%s` IS NULL"
                % (tn, rtn, cn, rcn, cn, rcn)
            )
            if r2[0][0] > 0:
                checks.append({'table': tn, 'col': cn, 'ref_table': rtn, 'orphan_count': r2[0][0]})
        except:
            pass
    return checks


def check_pending_clean(columns, tables):
    """12. is_pending_clean 检查"""
    pending_tables = [t for t in tables
                      if any(c['TABLE_NAME'] == t['TABLE_NAME'] and c['COLUMN_NAME'] == 'is_pending_clean'
                             for c in columns)]
    checks = []
    for t in pending_tables:
        try:
            _, r2 = q("SELECT COUNT(*) FROM `%s` WHERE is_pending_clean=1" % t['TABLE_NAME'])
            checks.append({'table': t['TABLE_NAME'], 'pending': r2[0][0]})
        except Exception as e:
            checks.append({'table': t['TABLE_NAME'], 'error': str(e)})
    return checks


def check_char_null(columns):
    """13. CharField/TextField null=True 检查"""
    findings = []
    for c in columns:
        ct = c['COLUMN_TYPE'].lower()
        if ('char' in ct or 'text' in ct) and c['IS_NULLABLE'] == 'YES':
            tn = c['TABLE_NAME']
            if not tn.startswith('django_') and not tn.startswith('auth_'):
                findings.append({'table': tn, 'column': c['COLUMN_NAME'], 'type': c['COLUMN_TYPE']})
    return findings


def check_duplicate_indexes(indexes):
    """14. 重复索引检查"""
    table_indexes = defaultdict(list)
    for idx in indexes:
        table_indexes[idx['TABLE_NAME']].append(
            (idx['INDEX_NAME'], idx['COLUMN_NAME'], idx['SEQ_IN_INDEX'], idx['NON_UNIQUE'])
        )
    duplicates = []
    for table, idxs in table_indexes.items():
        idx_groups = defaultdict(list)
        for name, col, seq, non_unique in idxs:
            idx_groups[name].append((col, seq, non_unique))
        idx_cols = {}
        for name, cols in idx_groups.items():
            col_tuple = tuple(sorted([c[0] for c in cols]))
            is_unique = all(c[2] == 0 for c in cols)
            if col_tuple in idx_cols:
                prev_name, prev_unique = idx_cols[col_tuple]
                if is_unique == prev_unique:
                    duplicates.append({
                        'table': table, 'columns': list(col_tuple),
                        'index1': prev_name, 'index2': name
                    })
            else:
                idx_cols[col_tuple] = (name, is_unique)
    return duplicates


def check_missing_tenant_index(columns, indexes):
    """15. 缺少 tenant_id 索引检查"""
    business_tables = set()
    for c in columns:
        if c['COLUMN_NAME'] == 'tenant_id':
            tn = c['TABLE_NAME']
            if not tn.startswith('django_') and not tn.startswith('auth_'):
                business_tables.add(tn)
    
    tables_with_tenant_idx = set()
    for idx in indexes:
        if idx['COLUMN_NAME'] == 'tenant_id':
            tables_with_tenant_idx.add(idx['TABLE_NAME'])
    
    missing = business_tables - tables_with_tenant_idx
    return sorted(missing)


def check_missing_is_deleted_index(columns, indexes):
    """16. 缺少 is_deleted 索引检查"""
    business_tables = set()
    for c in columns:
        if c['COLUMN_NAME'] == 'is_deleted':
            tn = c['TABLE_NAME']
            if not tn.startswith('django_') and not tn.startswith('auth_'):
                business_tables.add(tn)
    
    tables_with_sd_idx = set()
    for idx in indexes:
        if idx['COLUMN_NAME'] == 'is_deleted':
            tables_with_sd_idx.add(idx['TABLE_NAME'])
    
    missing = business_tables - tables_with_sd_idx
    return sorted(missing)


def check_stale_modules(tables, permissions, content_types):
    """17. 已删除模块残留检查"""
    stale = {
        'schedule_tables': [t['TABLE_NAME'] for t in tables
                            if 'schedule' in t['TABLE_NAME'].lower()
                            and not t['TABLE_NAME'].startswith('django_celery')],
        'shift_tables': [t['TABLE_NAME'] for t in tables
                         if 'shift' in t['TABLE_NAME'].lower()],
        'schedule_perms': [p for p in permissions
                           if 'schedule' in p['codename'].lower()
                           and 'celery' not in p['codename'].lower()],
        'schedule_cts': [ct for ct in content_types
                         if 'schedule' in ct['app_label'].lower()
                         and 'celery' not in ct['app_label'].lower()],
    }
    return stale


def main():
    """主审计入口"""
    results = {}
    
    tables = check_tables()
    columns = check_columns()
    indexes = check_indexes()
    fks = check_foreign_keys()
    permissions = check_permissions()
    content_types = check_content_types()
    
    results['tables'] = tables
    results['columns'] = columns
    results['indexes'] = indexes
    results['constraints'] = check_constraints()
    results['foreign_keys'] = fks
    results['migrations'] = check_migrations()
    results['auth_permissions'] = permissions
    results['content_types'] = content_types
    results['tenant_null_checks'] = check_tenant_null(columns, tables)
    results['soft_delete_checks'] = check_soft_delete(columns, tables)
    results['orphan_checks'] = check_orphans(fks)
    results['pending_clean'] = check_pending_clean(columns, tables)
    results['char_null_fields'] = check_char_null(columns)
    results['duplicate_indexes'] = check_duplicate_indexes(indexes)
    results['missing_tenant_index'] = check_missing_tenant_index(columns, indexes)
    results['missing_is_deleted_index'] = check_missing_is_deleted_index(columns, indexes)
    results['stale_modules'] = check_stale_modules(tables, permissions, content_types)
    
    print(json.dumps(results, ensure_ascii=False, default=str))


main()

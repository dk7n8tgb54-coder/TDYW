#!/usr/bin/env python3
"""从 MariaDB ROW binlog 的 DELETE 前镜像恢复被误删的 spug.tdyw_el_* 行。

解析 /tmp/binlog35.txt 中 Annotate_rows 标记的无 WHERE 全表 DELETE
（本次误删语句，形如 `#Q> DELETE FROM tdyw_el_xxx`，无 WHERE），
提取每个 Delete_rows 事件的完整 WHERE 前镜像，按列定义生成
INSERT IGNORE 语句（与现存新行主键冲突时保留新行）。
输出 /tmp/restore_el.sql。
"""
import re

BINLOG = '/tmp/binlog35.txt'
COLUMNS = '/tmp/el_columns.txt'
OUTPUT = '/tmp/restore_el.sql'

# 本次误删的无 WHERE 全表 DELETE（Annotate_rows 原文）
MY_STATEMENTS = {
    'tdyw_el_config_change', 'tdyw_el_config_value', 'tdyw_el_config_field',
    'tdyw_el_systems', 'tdyw_el_system_type',
}

columns = {}
with open(COLUMNS) as f:
    for line in f:
        parts = line.rstrip('\n').split('\t')
        if len(parts) != 4:
            continue
        table, pos, name, dtype = parts
        columns.setdefault(table, []).append((int(pos), name, dtype))

with open(BINLOG) as f:
    lines = f.readlines()

rows = []  # (table, [values])
i = 0
n = len(lines)
current_stmt_table = None
in_my_delete = False
cur_table = None
cur_vals = None

def flush():
    global cur_table, cur_vals
    if cur_table and cur_vals:
        rows.append((cur_table, cur_vals))
    cur_table, cur_vals = None, None

val_re = re.compile(r"^###\s+@(\d+)=((?:'[^']*')|NULL|[-\d.eE+]+)\s*/\*")

while i < n:
    line = lines[i]
    # Annotate_rows：本次误删语句开启收集窗口
    m = re.match(r'^#Q> DELETE FROM (tdyw_el_\w+)\s*$', line)
    if m:
        flush()
        in_my_delete = m.group(1) in MY_STATEMENTS
        current_stmt_table = m.group(1)
        i += 1
        continue
    # 其他 Annotate（非本次语句）关闭窗口
    if line.startswith('#Q> '):
        flush()
        in_my_delete = False
        current_stmt_table = None
        i += 1
        continue
    if in_my_delete:
        m = re.match(r'^### DELETE FROM `spug`\.`(tdyw_el_\w+)`', line)
        if m:
            flush()
            cur_table = m.group(1)
            cur_vals = {}
            i += 1
            continue
        if cur_table is not None:
            m = val_re.match(line)
            if m:
                idx = int(m.group(1))
                raw = m.group(2)
                if raw == 'NULL':
                    val = None
                elif raw.startswith("'"):
                    val = raw[1:-1].replace("''", "'")
                else:
                    val = raw
                cur_vals[idx] = val
                i += 1
                continue
            if line.startswith('### SET') or line.startswith('# at ') or line.startswith('#26'):
                # SET 段意味着 Update_rows 或事件结束
                if line.startswith('### SET'):
                    # Update_rows 事件（SET 段）结束本行收集
                    flush()
                i += 1
                continue
    i += 1

flush()

# 生成 SQL（按外键依赖排序）
order = ['tdyw_el_system_type', 'tdyw_el_systems', 'tdyw_el_config_field',
         'tdyw_el_config_value', 'tdyw_el_config_change']
by_table = {}
for table, vals in rows:
    by_table.setdefault(table, []).append(vals)

def quote(val, dtype):
    if val is None:
        return 'NULL'
    if dtype in ('int', 'bigint', 'smallint', 'tinyint', 'mediumint'):
        return str(val)
    if dtype in ('float', 'double', 'decimal'):
        return str(val)
    return "'" + str(val).replace("\\", "\\\\").replace("'", "''") + "'"

with open(OUTPUT, 'w') as out:
    out.write('-- restored from binlog row images (DELETE front mirror)\n')
    out.write('SET FOREIGN_KEY_CHECKS=0;\n')
    for table in order:
        cols = sorted(columns.get(table, []))
        if not cols:
            continue
        col_names = [c[1] for c in cols]
        col_types = {c[0]: c[2] for c in cols}
        data = by_table.get(table, [])
        out.write('-- %s: %d rows\n' % (table, len(data)))
        for vals in data:
            values = []
            for pos, name, dtype in cols:
                values.append(quote(vals.get(pos), dtype))
            out.write("INSERT IGNORE INTO `%s` (%s) VALUES (%s);\n" % (
                table, ', '.join('`%s`' % c for c in col_names), ', '.join(values)))
    out.write('SET FOREIGN_KEY_CHECKS=1;\n')

total = sum(len(v) for v in by_table.values())
print('rows recovered:', total)
for t in order:
    print(t, len(by_table.get(t, [])))

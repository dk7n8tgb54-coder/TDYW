#!/bin/bash
# ================================================================================
# 一次性运维脚本：删除生产库中已退役 device/fault 模块的 4 张空表（2026-10-24）
# --------------------------------------------------------------------------------
# 背景：apps/device 与 apps/fault 已于 2026-09-27 从代码库整体移除，生产 tdyw 库
# 中遗留 4 张空表（无对应模型、无入向外键、COUNT(*)=0，已于 2026-10-24 只读核实，
# 备份见本目录 ddl_*.sql 与 ddl_backup_all.sql）。
#
# 明确不碰（各自模块迁移链负责）：
#   tdyw_duty_records / tdyw_run_logs / tdyw_run_log_event_types /
#   tdyw_run_log_updates —— duty.0007_delete_dutyrecord 与 runlog.0015 迁移
#   仍在各自模块中，随下次部署 migrate 自动 DROP，避免重复删除。
#
# 注意：经 wsl 调用 docker exec 时 SQL 不得含反引号（wsl 内侧 shell 会做命令
# 替换），目标表名均为小写字母/下划线，无需引用符。
#
# fail-closed：任一前置校验（表存在、行数=0、无入向外键、目标库核对）不满足
# 时，整个脚本在任何 DROP 之前以非零码退出，不做部分删除。
# 幂等：表已不存在视为已清理（退出 0）。
# ================================================================================
set -uo pipefail

# 口令不入库不入 Git：必须由执行环境显式提供（如部署主机的受保护 .env 或
# 运行前手工 export；不设默认值，缺失即拒绝执行）
DB_CONTAINER="${DB_CONTAINER:-tdyw-db}"
DB_USER="${DB_USER:-tdyw}"
DB_PASS="${DB_PASS:?必须通过环境变量 DB_PASS 提供数据库口令（不得写入本文件）}"
DB_NAME="${DB_NAME:-tdyw}"

# 只允许这四张表；新增目标必须先评审本脚本
TARGET_TABLES=(tdyw_device_event tdyw_device_resume tdyw_fault_parts tdyw_fault_records)
# 绝不允许触碰的表（误配置防护）：duty/runlog 旧表与 upgrade 表
FORBIDDEN=(tdyw_duty_records tdyw_run_logs tdyw_run_log_event_types tdyw_run_log_updates tdyw_upgrade_records tdyw_upgrade_templates tdyw_upgrade_systems tdyw_upgrade_plan_steps tdyw_upgrade_record_steps tdyw_upgrade_status_logs)

fail() { echo "[FAIL-CLOSED] $1" >&2; exit 1; }

mysql_exec() {
    # wsl.exe 偶发瞬时故障（空输出/非零码）：重试 3 次 + CRLF 归一化；
    # 重试后仍失败则显式报错退出（fail-closed）
    local out=""
    for _ in 1 2 3; do
        out=$(wsl docker exec "$DB_CONTAINER" mysql -u"$DB_USER" -p"$DB_PASS" "$DB_NAME" -N -B -e "$1" 2>/dev/null | tr -d '\r\n')
        if [ -n "$out" ]; then break; fi
        sleep 2
    done
    [ -n "$out" ] || fail "数据库查询失败（重试 3 次仍无输出）: $1"
    echo "$out"
}

# 0. 目标库核对：必须是 tdyw 且含 tdyw_upgrade_records（生产库指纹）
DB_ACTUAL=$(mysql_exec "SELECT DATABASE();")
[ "$DB_ACTUAL" = "$DB_NAME" ] || fail "目标库名不符: $DB_ACTUAL"
UPG=$(mysql_exec "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='tdyw_upgrade_records';")
[ "$UPG" = "1" ] || fail "目标库缺少 tdyw_upgrade_records，不是预期的生产库"
echo "[OK] 目标库核对: $DB_NAME（含 upgrade 表）"

# 1. 目标表必须全部在本脚明白名单内（防误改数组）
for t in "${TARGET_TABLES[@]}"; do
    for f in "${FORBIDDEN[@]}"; do
        [ "$t" = "$f" ] && fail "目标表 $t 在禁碰名单中"
    done
done

PENDING=()
for t in "${TARGET_TABLES[@]}"; do
    EXISTS=$(mysql_exec "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='$t';")
    if [ "$EXISTS" = "0" ]; then
        echo "[SKIP] $t 不存在（已清理过，幂等）"
        continue
    fi
    # 2. 行数必须为 0
    CNT=$(mysql_exec "SELECT COUNT(*) FROM $t;")
    [ "$CNT" = "0" ] || fail "$t 行数=$CNT（要求 0），拒绝删除"
    # 3. 无任何入向外键
    FK=$(mysql_exec "SELECT COUNT(*) FROM information_schema.key_column_usage WHERE table_schema=DATABASE() AND referenced_table_name='$t';")
    [ "$FK" = "0" ] || fail "$t 存在 $FK 条入向外键引用，拒绝删除"
    PENDING+=("$t")
    echo "[OK] $t 预检通过（存在/0 行/无入向 FK）"
done

if [ ${#PENDING[@]} -eq 0 ]; then
    echo "[DONE] 无待删除表"
    exit 0
fi

# 4. DROP 前重验与执行：注意预检（第 3 步）与 DROP 是**不同数据库连接**，
#    存在理论上的 TOCTOU 窗口；本步通过"每轮 DROP 前用新查询重验四表行数
#    仍为 0 再拼 DROP"尽量缩小时窗，但不等于单会话原子保证。执行后仍有第
#    5 步后置复核兜底。语句均为无反引号的受控拼接。
#    wsl 偶发瞬时故障（0x8007274c）：重试 3 次。
DROP_OK=0
for attempt in 1 2 3; do
    for t in "${TARGET_TABLES[@]}"; do
        EXISTS=$(mysql_exec "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='$t';")
        [ "$EXISTS" = "1" ] || { echo "[SKIP-DROP] $t 已不存在"; continue; }
        CNT=$(mysql_exec "SELECT COUNT(*) FROM $t;")
        [ "$CNT" = "0" ] || fail "重验失败：$t 行数=$CNT"
    done
    DROP_SQL=""
    for t in "${TARGET_TABLES[@]}"; do
        EXISTS=$(mysql_exec "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='$t';")
        [ "$EXISTS" = "1" ] && DROP_SQL="$DROP_SQL DROP TABLE IF EXISTS $t;"
    done
    if [ -z "$DROP_SQL" ]; then DROP_OK=1; break; fi
    if wsl docker exec "$DB_CONTAINER" mysql -u"$DB_USER" -p"$DB_PASS" "$DB_NAME" -e "$DROP_SQL" 2>/dev/null; then
        DROP_OK=1
        break
    fi
    sleep 3
done
[ "$DROP_OK" = "1" ] || fail "DROP 执行失败（重试 3 次）"

# 5. 后置复核：四表全部不存在；upgrade 数据仍在
for t in "${TARGET_TABLES[@]}"; do
    LEFT=$(mysql_exec "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='$t';")
    [ "$LEFT" = "0" ] || fail "后置复核失败：$t 仍存在"
done
UPG_AFTER=$(mysql_exec "SELECT CONCAT((SELECT COUNT(*) FROM tdyw_upgrade_records), '/', (SELECT COUNT(*) FROM tdyw_upgrade_templates), '/', (SELECT COUNT(*) FROM tdyw_upgrade_systems));")
echo "[OK] 后置复核：四表已删除；upgrade 行数 records/templates/systems = $UPG_AFTER"
echo "[DONE] 清理完成 $(date '+%F %T')"

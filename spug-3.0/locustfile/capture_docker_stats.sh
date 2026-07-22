#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# =============================================================================
# capture_docker_stats.sh —— 压测期间后台采集 docker stats → CSV
#
# 与 locust 报告归档到同一 REPORT_DIR,便于对照 SLA_THRESHOLDS.md 的
# 资源类阈值(DB 连接数 / 容器内存)判定是否达标。
#
# 用法:
#   1) 前台运行(另开终端,压测期间保持,Ctrl+C 停止):
#        ./capture_docker_stats.sh [REPORT_DIR] [采样间隔秒,默认5]
#
#   2) 后台运行(start 后,压测结束调用 stop):
#        ./capture_docker_stats.sh start [REPORT_DIR] [间隔]
#        ./capture_docker_stats.sh stop
#
# 输出文件: <REPORT_DIR>/docker_stats.csv
#   CSV 列: timestamp,container,cpu_percent,mem_usage,mem_percent,net_io,block_io,pids
#   mem_usage 形如 "1.2GiB / 2GiB"(已用 / 上限),对照 SLA 内存阈值时看前半段。
# =============================================================================

set -u

# 监控目标容器(不存在的自动跳过)
CONTAINER_RE="^(tdyw|tdyw-db|kkfileview)$"

cmd="${1:-}"
case "$cmd" in
    start)
        shift
        REPORT_DIR="${1:-${REPORT_DIR:-./locust_reports_$(date +%Y%m%d_%H%M%S)}}"
        INTERVAL="${2:-5}"
        mkdir -p "$REPORT_DIR"
        # 后台自运行(内部模式 _bg),记录 PID 便于 stop
        nohup "$0" _bg "$REPORT_DIR" "$INTERVAL" >/dev/null 2>&1 &
        echo $! > /tmp/capture_docker_stats.pid
        echo "后台采集已启动 (PID $!), 输出 → ${REPORT_DIR}/docker_stats.csv"
        echo "压测结束后运行: $0 stop"
        exit 0
        ;;
    stop)
        PIDFILE=/tmp/capture_docker_stats.pid
        if [ -f "$PIDFILE" ]; then
            PID=$(cat "$PIDFILE")
            if kill "$PID" 2>/dev/null; then
                echo "已停止采集 (PID $PID)"
            else
                echo "进程 $PID 已不存在"
            fi
            rm -f "$PIDFILE"
        else
            echo "未找到运行中的采集进程"
        fi
        exit 0
        ;;
    _bg)
        REPORT_DIR="$2"
        INTERVAL="$3"
        ;;
    *)
        REPORT_DIR="${1:-${REPORT_DIR:-./locust_reports_$(date +%Y%m%d_%H%M%S)}}"
        INTERVAL="${2:-5}"
        ;;
esac

OUT_CSV="${REPORT_DIR}/docker_stats.csv"
mkdir -p "$REPORT_DIR"

# 单次采样(无流模式,每次输出一行,带时间戳前缀)
# 每次重新探测目标容器,以兼容压测中途才启动的容器(如 kkfileview)
sample_once() {
    local ts
    ts=$(date +%Y-%m-%dT%H:%M:%S)
    local containers=()
    mapfile -t containers < <(docker ps --format '{{.Names}}' | grep -E "$CONTAINER_RE")
    local args=(docker stats --no-stream --format "{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}},{{.NetIO}},{{.BlockIO}},{{.PIDs}}")
    if [ ${#containers[@]} -gt 0 ]; then
        args+=("${containers[@]}")
    fi
    "${args[@]}" 2>/dev/null | while IFS= read -r line; do
        echo "${ts},${line}"
    done
}

# 写表头
echo "timestamp,container,cpu_percent,mem_usage,mem_percent,net_io,block_io,pids" > "$OUT_CSV"

echo "开始采集 docker stats → $OUT_CSV (间隔 ${INTERVAL}s)"
echo "监控目标: tdyw / tdyw-db / kkfileview (仅采集运行中的)"
if [ "$cmd" != "_bg" ]; then
    echo "前台模式:Ctrl+C 停止"
fi

while true; do
    sample_once >> "$OUT_CSV" || true
    sleep "$INTERVAL"
done

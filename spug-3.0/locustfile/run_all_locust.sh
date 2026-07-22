#!/usr/bin/env bash
# -*- coding: utf-8 -*-
# =============================================================================
# locustfile 统一 runner —— 批量跑所有压测脚本并汇总 CSV 报告
#
# 默认用 Docker 跑 locust 官方镜像(locustio/locust),无需在 WSL 装任何依赖。
# 首次运行会自动拉取镜像(~50MB),之后有缓存。
#
# 用法:
#   ./run_all_locust.sh                      # Docker 模式,跑上线前必补(推荐)
#   ./run_all_locust.sh --all                # Docker 模式,跑全部(含上线后可补)
#   ./run_all_locust.sh --only pdf_export    # 只跑指定脚本
#   ./run_all_locust.sh --list               # 列出所有可用脚本
#   ./run_all_locust.sh --local ...          # 用本地 Python 跑(需自行装 locust)
#
# 环境变量:
#   LOCUST_HOST    目标地址(默认 http://localhost,即生产容器 tdyw 的 80 端口)
#   LOCUST_IMAGE   locust Docker 镜像(默认 locustio/locust)
#   LOCUST_U       覆盖 -u(并发用户数),仅 --only 生效,用于尖峰测试
#   LOCUST_R       覆盖 -r(ramp 速率),仅 --only 生效
#   LOCUST_T       覆盖 -t(运行时长),仅 --only 生效
#   例: LOCUST_U=100 LOCUST_R=20 LOCUST_T=3m ./run_all_locust.sh --only document_stress --local
# =============================================================================
set -euo pipefail

HOST="${LOCUST_HOST:-http://localhost}"
LOCUST_IMAGE="${LOCUST_IMAGE:-locustio/locust}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPORT_DIR="${REPORT_DIR:-./locust_reports_$(date +%Y%m%d_%H%M%S)}"
USE_DOCKER=true

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 解析 --local 标志(其余参数原样保留)
ARGS=()
for arg in "$@"; do
    if [ "$arg" = "--local" ]; then
        USE_DOCKER=false
    else
        ARGS+=("$arg")
    fi
done
set -- "${ARGS[@]:-}"

# =========================================================================
# 运行模式探测
# =========================================================================
if [ "$USE_DOCKER" = true ]; then
    # Docker 模式:检查 docker 可用
    if ! command -v docker &>/dev/null; then
        echo -e "${RED}错误: docker 未找到。请用 --local 模式或安装 Docker。${NC}"
        exit 1
    fi
    RUN_MODE="Docker (${LOCUST_IMAGE})"
else
    # 本地模式:检查 python + locust
    if command -v python3 &>/dev/null; then
        PYTHON=python3
    elif command -v python &>/dev/null; then
        PYTHON=python
    else
        echo -e "${RED}错误: 未找到 python/python3${NC}"
        exit 1
    fi
    PY_VER=$("$PYTHON" -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
    if [ -n "$PY_VER" ] && [ -d "$HOME/.local/lib/$PY_VER/site-packages" ]; then
        export PYTHONPATH="$HOME/.local/lib/$PY_VER/site-packages:${PYTHONPATH:-}"
    fi
    if ! "$PYTHON" -c "import locust" 2>/tmp/locust_import_err; then
        echo -e "${RED}错误: locust 未安装。建议用 Docker 模式(默认),或:$PYTHON -m pip install locust${NC}"
        cat /tmp/locust_import_err 2>/dev/null
        exit 1
    fi
    RUN_MODE="Local ($PYTHON)"
fi

mkdir -p "$REPORT_DIR"

# =========================================================================
# 脚本清单
# =========================================================================
# 并发基准: 对照 SLA_THRESHOLDS.md「部署规模与并发标定」
#   目标负载 = 40 并发 (≈38 账号全活跃 + 突发余量), 尖峰 = 80 并发。
#   常规功能场景统一按目标负载 40 并发跑; 尖峰 80 如需验证请临时改 -u 或 --only。
# token 池模式: 5 账号登录一次, N 用户复用 token, 不触发登录限流。
# 注意: account_login_stress.py (真实登录压测) 有意不纳入 runner ——
#       单账号高频登录会触发限流/封号; 如需测登录请单独小并发手动跑。

# 上线前必补脚本(🔴 必跑)
PRE_RELEASE_SCRIPTS=(
    "document_stress:资料CRUD+分片上传:40:8:5m"
    "locustfile_pdf_export:PDF导出:40:8:3m"
    "locustfile_download:大文件下载:40:8:3m"
    "locustfile_kkfileview_preview:kkFileView预览:40:8:3m"
    "locustfile_audit_log:审计日志:40:8:5m"
    "locustfile_mixed_workload:混合负载:40:8:5m"
    "locustfile_department_duty_log:值班日志全功能:40:8:5m"
)

# 上线后可补脚本(🟡 选跑)
POST_RELEASE_SCRIPTS=(
    "locustfile_multi_tenant:多租户并发:40:8:5m"
    "locustfile_permission_cache:权限缓存击穿:40:8:5m"
    "locustfile_celery_queue:Celery队列积压:40:8:10m"
    # 保留低并发: 每虚拟用户持续循环上传多个小文件, 9 并发的写入压力已远超单请求场景
    "locustfile_bulk_upload:小文件批量上传:9:3:5m"
    "locustfile_websocket:WebSocket推送:40:8:5m"
    # 保留低并发: 8h 长稳测试用常态负载, 不宜用峰值并发长跑
    "locustfile_soak_test:长时间稳定性:20:2:8h"
)

# =========================================================================
# 运行单个脚本
# =========================================================================
run_script() {
    local entry="$1"
    local name="${entry%%:*}"
    local rest="${entry#*:}"
    local desc="${rest%%:*}"
    rest="${rest#*:}"
    local u="${rest%%:*}"
    rest="${rest#*:}"
    local r="${rest%%:*}"
    rest="${rest#*:}"
    local t="${rest}"

    local script_file="${SCRIPT_DIR}/${name}.py"
    if [ ! -f "$script_file" ]; then
        echo -e "${RED}  [SKIP] ${name} 不存在${NC}"
        return 1
    fi

    echo -e "${GREEN}  [RUN] ${name} (${desc}) -u ${u} -r ${r} -t ${t}${NC}"

    if [ "$USE_DOCKER" = true ]; then
        # Docker 模式:用 locustio/locust 镜像跑
        docker run --rm --network host \
            -e KEEP_TEST_DATA \
            -v "${SCRIPT_DIR}":/mnt/locustfile \
            -v "${REPORT_DIR}":/mnt/reports \
            "$LOCUST_IMAGE" \
            -f /mnt/locustfile/${name}.py \
            -H "$HOST" --headless -u "$u" -r "$r" -t "$t" \
            --csv=/mnt/reports/${name} 2>&1 | tee "${REPORT_DIR}/${name}.log" || {
            echo -e "${RED}  [FAIL] ${name} 执行失败${NC}"
            return 1
        }
    else
        # 本地模式
        "$PYTHON" -m locust -f "$script_file" -H "$HOST" \
            --headless -u "$u" -r "$r" -t "$t" \
            --csv="${REPORT_DIR}/${name}" 2>&1 | tee "${REPORT_DIR}/${name}.log" || {
            echo -e "${RED}  [FAIL] ${name} 执行失败${NC}"
            return 1
        }
    fi
    echo -e "${GREEN}  [DONE] ${name} → ${REPORT_DIR}/${name}_stats.csv${NC}"
    # 脚本间冷却 10 秒(避免连续登录触发限流)
    sleep 30  # 高并发后冷却 30s(让 DB 连接/缓存恢复)
}

# =========================================================================
# 列出脚本
# =========================================================================
list_scripts() {
    echo -e "${RED}=== 上线前必补 (🔴 必跑) ===${NC}"
    for entry in "${PRE_RELEASE_SCRIPTS[@]}"; do
        name="${entry%%:*}"; desc="${entry#*:}"; desc="${desc%%:*}"
        printf "  %-35s %s\n" "$name" "$desc"
    done
    echo ""
    echo -e "${YELLOW}=== 上线后可补 (🟡 选跑) ===${NC}"
    for entry in "${POST_RELEASE_SCRIPTS[@]}"; do
        name="${entry%%:*}"; desc="${entry#*:}"; desc="${desc%%:*}"
        printf "  %-35s %s\n" "$name" "$desc"
    done
}

# =========================================================================
# 主流程
# =========================================================================
echo "============================================================"
echo "locustfile 统一 runner"
echo "  Mode:    $RUN_MODE"
echo "  Host:    $HOST"
echo "  Report:  $REPORT_DIR"
echo "============================================================"

case "${1:-}" in
    --list)
        list_scripts
        exit 0
        ;;
    --all)
        echo -e "${RED}=== 阶段 1: 上线前必补 ===${NC}"
        for entry in "${PRE_RELEASE_SCRIPTS[@]}"; do
            run_script "$entry" || true
        done
        echo ""
        echo -e "${YELLOW}=== 阶段 2: 上线后可补 ===${NC}"
        for entry in "${POST_RELEASE_SCRIPTS[@]}"; do
            run_script "$entry" || true
        done
        ;;
    --only)
        if [ -z "${2:-}" ]; then
            echo "用法: $0 --only <script_name>"
            exit 1
        fi
        # 尖峰/自定义并发覆盖(仅 --only 生效): LOCUST_U / LOCUST_R / LOCUST_T
        # 未设置时回退默认 40:8:5m,与你平时三行跑法行为一致
        run_script "${2}:手动指定:${LOCUST_U:-40}:${LOCUST_R:-8}:${LOCUST_T:-5m}"
        ;;
    "")
        echo -e "${RED}=== 上线前必补 ===${NC}"
        for entry in "${PRE_RELEASE_SCRIPTS[@]}"; do
            run_script "$entry" || true
        done
        ;;
    *)
        echo "用法: $0 [--all | --only <name> | --list | --local]"
        echo "  无参数      Docker 模式,跑上线前必补(推荐)"
        echo "  --all       Docker 模式,跑全部"
        echo "  --only X    只跑指定脚本"
        echo "  --list      列出所有脚本"
        echo "  --local     用本地 Python 跑(加在其他参数后)"
        exit 1
        ;;
esac

echo ""
echo "============================================================"
echo "压测完成。CSV 报告: $REPORT_DIR"
echo "对照 SLA_THRESHOLDS.md 判定是否达标"
echo "============================================================"

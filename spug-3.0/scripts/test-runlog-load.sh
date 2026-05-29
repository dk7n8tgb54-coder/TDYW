#!/bin/bash
# 运行日志模块压力测试 - Shell 脚本
# 用于快速运行 Locust 压力测试

set -e

# 默认参数
HOST="http://localhost:80"
USERS=50
SPAWN_RATE=10
DURATION="5m"
INTERACTIVE=false

# 解析参数
while [[ $# -gt 0 ]]; do
    case $1 in
        -H|--host)
            HOST="$2"
            shift 2
            ;;
        -u|--users)
            USERS="$2"
            shift 2
            ;;
        -s|--spawn-rate)
            SPAWN_RATE="$2"
            shift 2
            ;;
        -d|--duration)
            DURATION="$2"
            shift 2
            ;;
        -i|--interactive)
            INTERACTIVE=true
            shift
            ;;
        -h|--help)
            echo "用法: $0 [选项]"
            echo ""
            echo "选项:"
            echo "  -H, --host HOST        目标主机 (默认: http://localhost:80)"
            echo "  -u, --users NUM       并发用户数 (默认: 50)"
            echo "  -s, --spawn-rate NUM  启动速率 (默认: 10)"
            echo "  -d, --duration TIME   测试时长 (默认: 5m)"
            echo "  -i, --interactive     交互式模式"
            echo "  -h, --help           显示帮助信息"
            echo ""
            echo "示例:"
            echo "  $0                                          # 默认配置"
            echo "  $0 -i                                      # 交互式模式"
            echo "  $0 -u 100 -s 20 -d 10m                    # 100用户，10分钟"
            echo "  $0 -H http://192.168.1.100:80 -u 200 -s 30 # 远程主机"
            exit 0
            ;;
        *)
            echo "未知选项: $1"
            echo "使用 -h 或 --help 查看帮助"
            exit 1
            ;;
    esac
done

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  运行日志模块压力测试${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""

# 检查 Locust 是否安装
echo -e "${YELLOW}检查 Locust 是否安装...${NC}"
if command -v locust &> /dev/null; then
    VERSION=$(locust --version 2>&1 | head -n 1)
    echo -e "${GREEN}✓ Locust 已安装: $VERSION${NC}"
elif python -m locust --version &> /dev/null; then
    VERSION=$(python -m locust --version 2>&1 | head -n 1)
    echo -e "${GREEN}✓ Locust 已安装: $VERSION${NC}"
else
    echo -e "${RED}✗ Locust 未安装${NC}"
    echo -e "${YELLOW}请运行: python -m pip install locust${NC}"
    exit 1
fi

echo ""
echo -e "${CYAN}测试配置:${NC}"
echo -e "${WHITE}  Host: $HOST${NC}"
echo -e "${WHITE}  Users: $USERS${NC}"
echo -e "${WHITE}  Spawn Rate: $SPAWN_RATE${NC}"
echo -e "${WHITE}  Duration: $DURATION${NC}"
echo -e "${WHITE}  Mode: $(if [ "$INTERACTIVE" = true ]; then echo '交互式'; else echo '命令行'; fi)${NC}"
echo ""

# 运行测试
echo -e "${GREEN}开始压力测试...${NC}"
echo ""

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
CSV_PREFIX="runlog_test_${TIMESTAMP}"

if [ "$INTERACTIVE" = true ]; then
    # 交互式模式
    echo -e "${CYAN}启动交互式模式，请在浏览器中打开 http://localhost:8089${NC}"
    echo ""

    locust -f locustfile/locustfile_runlog.py -H "$HOST"
else
    # 命令行模式
    echo -e "${CYAN}运行命令行模式测试...${NC}"
    echo ""

    locust -f locustfile/locustfile_runlog.py \
        -H "$HOST" \
        --users "$USERS" \
        --spawn-rate "$SPAWN_RATE" \
        --run-time "$DURATION" \
        --headless \
        --csv "$CSV_PREFIX"

    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${GREEN}测试完成！${NC}"
    echo -e "${CYAN}========================================${NC}"
    echo ""
    echo -e "${YELLOW}测试报告已生成:${NC}"
    echo -e "${WHITE}  - ${CSV_PREFIX}_stats.csv${NC}"
    echo -e "${WHITE}  - ${CSV_PREFIX}_stats_history.csv${NC}"
    echo -e "${WHITE}  - ${CSV_PREFIX}_failures.csv${NC}"
    echo ""
fi

# 测试场景说明
echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}测试场景说明${NC}"
echo -e "${CYAN}========================================${NC}"
echo ""
echo -e "${WHITE}1. 高频查询 (weight=15):${NC}"
echo "   - 获取日志列表"
echo ""
echo -e "${WHITE}2. 中频查询 (weight=8):${NC}"
echo "   - 获取事件详情"
echo "   - 获取统计数据 (weight=5)"
echo ""
echo -e "${WHITE}3. 中频操作 (weight=8):${NC}"
echo "   - 添加动态"
echo ""
echo -e "${WHITE}4. 低频操作:${NC}"
echo "   - 创建事件 (weight=3)"
echo "   - 更新事件 (weight=4)"
echo "   - 编辑动态 (weight=2)"
echo "   - 上传图片 (weight=3)"
echo ""
echo -e "${WHITE}5. 极低频 (weight=1):${NC}"
echo "   - 删除事件"
echo "   - 删除动态 (weight=1)"
echo ""
echo -e "${WHITE}6. 高并发测试 (weight=5):${NC}"
echo "   - 同时添加动态（测试序号计算）"
echo ""
echo -e "${CYAN}========================================${NC}"
echo ""

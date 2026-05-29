#!/bin/bash
# 回收站API手动测试脚本
# 用于在Docker环境中测试API接口

set -e

BASE_URL="http://localhost:8000"
TOKEN=""

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 登录获取Token
login() {
    echo -e "${BLUE}[测试] 用户登录...${NC}"
    RESPONSE=$(curl -s -X POST "${BASE_URL}/api/account/login/" \
        -H "Content-Type: application/json" \
        -d '{
            "username": "admin",
            "password": "spug"
        }' || echo "{}")
    
    TOKEN=$(echo $RESPONSE | grep -o '"token":"[^"]*' | cut -d'"' -f4)
    
    if [ -z "$TOKEN" ]; then
        echo -e "${RED}[错误] 登录失败${NC}"
        echo "响应: $RESPONSE"
        exit 1
    fi
    
    echo -e "${GREEN}[✓] 登录成功，获取Token${NC}"
    echo ""
}

# 测试获取回收站列表
test_get_recycle_bin_list() {
    echo -e "${BLUE}[测试] 获取回收站列表...${NC}"
    RESPONSE=$(curl -s -X GET "${BASE_URL}/api/document/recycle-bin/?page=1&page_size=10" \
        -H "Authorization: Bearer ${TOKEN}" \
        -H "X-Requested-With: XMLHttpRequest" || echo "{}")
    
    echo "响应: $RESPONSE" | head -c 500
    echo ""
    
    if echo "$RESPONSE" | grep -q '"data"'; then
        echo -e "${GREEN}[✓] 获取列表成功${NC}"
    else
        echo -e "${YELLOW}[警告] 响应异常${NC}"
    fi
    echo ""
}

# 测试获取回收站统计
test_get_recycle_bin_stats() {
    echo -e "${BLUE}[测试] 获取回收站统计...${NC}"
    RESPONSE=$(curl -s -X GET "${BASE_URL}/api/document/recycle-bin/stats/" \
        -H "Authorization: Bearer ${TOKEN}" \
        -H "X-Requested-With: XMLHttpRequest" || echo "{}")
    
    echo "响应: $RESPONSE"
    
    if echo "$RESPONSE" | grep -q '"total_count"'; then
        echo -e "${GREEN}[✓] 获取统计成功${NC}"
    else
        echo -e "${YELLOW}[警告] 响应异常${NC}"
    fi
    echo ""
}

# 测试恢复文件（需要已删除的文件ID）
test_restore_file() {
    local file_id=${1:-1}
    echo -e "${BLUE}[测试] 恢复文件 (ID: $file_id)...${NC}"
    RESPONSE=$(curl -s -X POST "${BASE_URL}/api/document/recycle-bin/restore/" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${TOKEN}" \
        -H "X-Requested-With: XMLHttpRequest" \
        -d "{
            \"file_ids\": [$file_id],
            \"restore_mode\": \"original\"
        }" || echo "{}")
    
    echo "响应: $RESPONSE"
    
    if echo "$RESPONSE" | grep -q '"success_count"'; then
        echo -e "${GREEN}[✓] 恢复请求发送成功${NC}"
    else
        echo -e "${YELLOW}[警告] 响应异常（可能是文件不存在）${NC}"
    fi
    echo ""
}

# 测试彻底删除文件
test_permanent_delete() {
    local file_id=${1:-1}
    echo -e "${BLUE}[测试] 彻底删除文件 (ID: $file_id)...${NC}"
    RESPONSE=$(curl -s -X POST "${BASE_URL}/api/document/recycle-bin/permanent/" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${TOKEN}" \
        -H "X-Requested-With: XMLHttpRequest" \
        -d "{
            \"file_ids\": [$file_id]
        }" || echo "{}")
    
    echo "响应: $RESPONSE"
    
    if echo "$RESPONSE" | grep -q '"success_count"\|"async"'; then
        echo -e "${GREEN}[✓] 删除请求发送成功${NC}"
    else
        echo -e "${YELLOW}[警告] 响应异常（可能是文件不存在）${NC}"
    fi
    echo ""
}

# 显示使用说明
show_usage() {
    echo "=========================================="
    echo "    回收站API测试脚本"
    echo "=========================================="
    echo ""
    echo "使用方法:"
    echo "  $0 all              - 执行所有测试"
    echo "  $0 login            - 测试登录"
    echo "  $0 list             - 测试获取列表"
    echo "  $0 stats            - 测试获取统计"
    echo "  $0 restore [id]     - 测试恢复文件"
    echo "  $0 delete [id]      - 测试彻底删除"
    echo ""
    echo "注意: 确保Docker容器已启动"
    echo "      默认使用 http://localhost:8000"
    echo ""
}

# 主逻辑
case "${1:-all}" in
    all)
        login
        test_get_recycle_bin_list
        test_get_recycle_bin_stats
        echo -e "${YELLOW}提示: 恢复和删除测试需要有效的文件ID${NC}"
        echo "      先查看列表获取已删除文件的ID"
        ;;
    login)
        login
        ;;
    list)
        login
        test_get_recycle_bin_list
        ;;
    stats)
        login
        test_get_recycle_bin_stats
        ;;
    restore)
        login
        test_restore_file "${2:-1}"
        ;;
    delete)
        login
        test_permanent_delete "${2:-1}"
        ;;
    help|--help|-h)
        show_usage
        ;;
    *)
        echo -e "${RED}[错误] 未知命令: $1${NC}"
        show_usage
        exit 1
        ;;
esac

echo "=========================================="
echo -e "${GREEN}    测试执行完成！${NC}"
echo "=========================================="

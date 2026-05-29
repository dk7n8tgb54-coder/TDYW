#!/bin/bash
# 【任务5.1】代码检查脚本
# 统一运行前端和后端的代码检查工具

set -e

echo "=========================================="
echo "       代码质量检查工具 - 任务5.1          "
echo "=========================================="
echo ""

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查前端代码
echo -e "${YELLOW}[1/2] 检查前端代码 (ESLint)...${NC}"
echo "----------------------------------------"
cd "$(dirname "$0")/../spug_web"

if command -v npx &> /dev/null; then
    # 运行 ESLint 检查
    npx eslint src/ --ext .js,.jsx --format stylish || {
        echo -e "${RED}前端代码检查失败！${NC}"
        exit 1
    }
    echo -e "${GREEN}前端代码检查通过 ✓${NC}"
else
    echo -e "${YELLOW}警告: npx 未安装，跳过前端检查${NC}"
fi

echo ""

# 检查后端代码
echo -e "${YELLOW}[2/2] 检查后端代码 (Flake8)...${NC}"
echo "----------------------------------------"
cd "$(dirname "$0")/../spug_api"

if command -v flake8 &> /dev/null; then
    # 运行 Flake8 检查
    flake8 apps/ libs/ consumer/ --count --show-source --statistics || {
        echo -e "${RED}后端代码检查失败！${NC}"
        exit 1
    }
    echo -e "${GREEN}后端代码检查通过 ✓${NC}"
else
    echo -e "${YELLOW}警告: Flake8 未安装，跳过后端检查${NC}"
    echo "安装命令: pip install flake8"
fi

echo ""
echo "=========================================="
echo -e "${GREEN}       所有检查通过！✓${NC}"
echo "=========================================="

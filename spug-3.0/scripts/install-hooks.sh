#!/bin/bash
# 安装 Git Hooks 脚本

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
HOOKS_DIR="$PROJECT_ROOT/.git/hooks"

echo "=========================================="
echo "       安装 Git Hooks"
echo "=========================================="
echo ""

# 检查是否在 git 仓库中
if [ ! -d "$PROJECT_ROOT/.git" ]; then
    echo "❌ 错误: 当前目录不是 Git 仓库"
    exit 1
fi

# 创建 hooks 目录
mkdir -p "$HOOKS_DIR"

# 安装 pre-commit hook
if [ -f "$SCRIPT_DIR/hooks/pre-commit" ]; then
    cp "$SCRIPT_DIR/hooks/pre-commit" "$HOOKS_DIR/pre-commit"
    chmod +x "$HOOKS_DIR/pre-commit"
    echo "✓ 已安装 pre-commit hook"
else
    echo "❌ 错误: 找不到 pre-commit hook 脚本"
    exit 1
fi

echo ""
echo "=========================================="
echo "  Git Hooks 安装完成"
echo "=========================================="
echo ""
echo "已启用的 hooks:"
echo "  - pre-commit: 提交前代码质量检查"
echo ""
echo "如需跳过检查强制提交，使用:"
echo "  git commit --no-verify"
echo ""

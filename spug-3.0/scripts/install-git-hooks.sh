#!/bin/bash
# 【任务5.1】安装 Git 预提交钩子
# 在代码提交前自动运行代码检查

set -e

ScriptDir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ProjectDir="$(dirname "$ScriptDir")"

# 查找 Git 仓库根目录（可能在父目录中）
GitRoot="$(cd "$ProjectDir" && git rev-parse --show-toplevel 2>/dev/null || echo "$ProjectDir")"
HookFile="$GitRoot/.git/hooks/pre-commit"

echo "项目目录: $ProjectDir"
echo "Git 根目录: $GitRoot"

echo "=========================================="
echo "       安装 Git 预提交钩子 - 任务5.1       "
echo "=========================================="
echo ""

# 检查是否是 Git 仓库
if [ ! -d "$RootDir/.git" ]; then
    echo "错误: 当前目录不是 Git 仓库"
    exit 1
fi

# 创建预提交钩子
cat > "$HookFile" << 'EOF'
#!/bin/bash
# Git 预提交钩子 - 代码质量检查
# 由 scripts/install-git-hooks.sh 自动生成

echo "Running pre-commit checks..."
echo ""

# 获取脚本所在目录
ScriptDir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RootDir="$(dirname "$ScriptDir")"

# 检查前端代码
if git diff --cached --name-only | grep -q "^spug_web/src/.*\.js"; then
    echo "[1/2] Checking frontend code (ESLint)..."
    cd "$RootDir/spug_web"
    if command -v npx &> /dev/null; then
        npx eslint src/ --ext .js,.jsx --quiet
        if [ $? -ne 0 ]; then
            echo "Frontend linting failed. Please fix the issues before committing."
            exit 1
        fi
    fi
fi

# 检查后端代码
if git diff --cached --name-only | grep -q "^spug_api/.*\.py"; then
    echo "[2/2] Checking backend code (Flake8)..."
    cd "$RootDir/spug_api"
    if command -v flake8 &> /dev/null; then
        flake8 apps/ libs/ consumer/ --count
        if [ $? -ne 0 ]; then
            echo "Backend linting failed. Please fix the issues before committing."
            exit 1
        fi
    fi
fi

echo ""
echo "All checks passed! ✓"
EOF

# 设置执行权限
chmod +x "$HookFile"

echo "✓ Git 预提交钩子已安装到: $HookFile"
echo ""
echo "钩子功能:"
echo "  - 提交前自动检查修改的 JS 文件 (ESLint)"
echo "  - 提交前自动检查修改的 Python 文件 (Flake8)"
echo ""
echo "如需跳过检查，使用: git commit --no-verify"
echo "=========================================="

# 代码门禁使用说明

## 快速开始

### 1. 安装代码门禁

**Windows (PowerShell):**
```powershell
cd e:/TDYW/spug-3.0
.\scripts\install-hooks.ps1
```

**Linux/Mac (Bash):**
```bash
cd e:/TDYW/spug-3.0
bash scripts/install-hooks.sh
```

**手动安装 (通用):**
```bash
# 直接复制钩子文件
copy scripts\hooks\pre-commit .git\hooks\pre-commit
```

### 2. 验证安装

```bash
# 查看已安装的 hook
ls -la .git/hooks/pre-commit
```

### 3. 正常使用

安装后，每次 `git commit` 会自动触发代码检查：

```bash
git add .
git commit -m "xxx"   # ← 自动触发代码门禁检查
```

## 检查规则

| 规则 | 限制 | 说明 |
|------|------|------|
| 文件行数 | ≤ 1000行 | 单个文件不能超过1000行 |
| 函数行数 | ≤ 200行 | 单个函数不能超过200行 |
| 复杂度 | ≤ 15 | 圈复杂度限制 |

## 跳过检查（紧急情况）

```bash
# 强制提交，跳过代码门禁
git commit --no-verify -m "紧急修复"
```

## 手动运行检查

```bash
# 检查整个项目
python scripts/code_quality_check.py

# 只检查后端代码
python scripts/code_quality_check.py --backend-only

# 只检查前端代码
python scripts/code_quality_check.py --frontend-only
```

## 检查失败怎么办

1. **文件行数超标**：拆分文件或提取公共函数
2. **函数行数超标**：将大函数拆分为多个小函数
3. **复杂度过高**：简化逻辑，减少嵌套和分支

## 卸载代码门禁

```bash
rm .git/hooks/pre-commit
```

## 注意事项

- 代码门禁只在本地生效，不会提交到仓库
- 每个开发者需要单独安装
- 建议在团队内统一要求使用

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

门禁采用“历史基线 + 增量收紧”策略，避免历史大文件阻塞所有后续修改：

| 场景 | 文件有效代码行数 | 函数行数 | 圈复杂度 |
|------|------------------:|---------:|---------:|
| 新文件、新增代码、被修改函数 | ≤ 800 行 | ≤ 120 行 | ≤ 15 |
| 历史文件和未修改函数 | ≤ 1000 行 | ≤ 250 行 | ≤ 25 |

历史超标项记录在 `quality/baselines/code_quality_baseline.json`。基线只允许
保持或减少现状；修改到已有超标函数时，立即使用新阈值检查。不得通过删除
测试、关闭检查或扩大基线来掩盖新增复杂度。

JavaScript 函数边界使用 Babel AST 解析；解析失败时跳过该文件的函数长度
扫描并输出警告，前端构建/语法检查仍是必需的兜底检查。门禁会合并工作区
diff、暂存区 diff 和未跟踪文件的变更范围。复杂度是默认非阻断警告，文件长度、
函数长度和语法错误会阻断门禁。

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

# CI 机器可读输出
python scripts/code_quality_check.py --format json

# 首次建立或人工确认历史基线（只在基线变更评审时使用）
python scripts/code_quality_check.py --write-baseline
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

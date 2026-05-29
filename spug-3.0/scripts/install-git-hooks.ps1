# 安装 Git 预提交钩子 (PowerShell)
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir

# 查找 Git 仓库根目录
$OriginalDir = Get-Location
try {
    Set-Location $ProjectDir
    $GitRoot = git rev-parse --show-toplevel 2>$null
} finally {
    Set-Location $OriginalDir
}

if (-not $GitRoot) {
    $GitRoot = $ProjectDir
}

$HookFile = Join-Path $GitRoot ".git/hooks/pre-commit"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "       安装 Git 预提交钩子" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "项目目录: $ProjectDir" -ForegroundColor Gray
Write-Host "Git 根目录: $GitRoot" -ForegroundColor Gray
Write-Host ""

if (-not (Test-Path (Join-Path $GitRoot ".git"))) {
    Write-Host "错误: 找不到 Git 仓库" -ForegroundColor Red
    exit 1
}

$HooksDir = Join-Path $GitRoot ".git/hooks"
if (-not (Test-Path $HooksDir)) {
    New-Item -ItemType Directory -Path $HooksDir -Force | Out-Null
}

# 复制模板文件
$TemplateFile = Join-Path $ScriptDir "hooks/pre-commit-template"
if (-not (Test-Path $TemplateFile)) {
    Write-Host "错误: 找不到模板文件 $TemplateFile" -ForegroundColor Red
    exit 1
}

Copy-Item -Path $TemplateFile -Destination $HookFile -Force

# 设置执行权限
try {
    bash -c "chmod +x '$HookFile'" 2>$null
} catch {
    # 忽略错误
}

Write-Host "Git 预提交钩子已安装到: $HookFile" -ForegroundColor Green
Write-Host ""
Write-Host "如需跳过检查，使用: git commit --no-verify" -ForegroundColor Yellow
Write-Host "==========================================" -ForegroundColor Cyan

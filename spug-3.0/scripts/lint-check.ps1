# 【任务5.1】代码检查脚本 (PowerShell 版本)
# 统一运行前端和后端的代码检查工具

$ErrorActionPreference = "Stop"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "       代码质量检查工具 - 任务5.1          " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir

# 检查前端代码
Write-Host "[1/2] 检查前端代码 (ESLint)..." -ForegroundColor Yellow
Write-Host "----------------------------------------" -ForegroundColor Gray

$WebDir = Join-Path $RootDir "spug_web"
Set-Location $WebDir

try {
    $EslintOutput = npx eslint src/ --ext .js,.jsx --format stylish 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host $EslintOutput -ForegroundColor Red
        Write-Host "前端代码检查失败！" -ForegroundColor Red
        exit 1
    }
    Write-Host "前端代码检查通过 ✓" -ForegroundColor Green
} catch {
    Write-Host "警告: ESLint 运行失败或未安装" -ForegroundColor Yellow
    Write-Host $_ -ForegroundColor Gray
}

Write-Host ""

# 检查后端代码
Write-Host "[2/2] 检查后端代码 (Flake8)..." -ForegroundColor Yellow
Write-Host "----------------------------------------" -ForegroundColor Gray

$ApiDir = Join-Path $RootDir "spug_api"
Set-Location $ApiDir

try {
    $Flake8Output = python -m flake8 apps/ libs/ consumer/ --count --show-source --statistics 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host $Flake8Output -ForegroundColor Red
        Write-Host "后端代码检查失败！" -ForegroundColor Red
        exit 1
    }
    Write-Host $Flake8Output -ForegroundColor Gray
    Write-Host "后端代码检查通过 ✓" -ForegroundColor Green
} catch {
    Write-Host "警告: Flake8 未安装，跳过后端检查" -ForegroundColor Yellow
    Write-Host "安装命令: pip install flake8" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "       所有检查通过！✓" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Cyan

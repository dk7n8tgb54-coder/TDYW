# Windows开发环境设置每日自动备份任务
# 使用方法: .\setup_scheduled_backup.ps1

# ==================== 配置区域 ====================

$TaskName = "Spug开发环境数据库自动备份"
$ScriptPath = Join-Path $PSScriptRoot "auto_backup.ps1"
$ScheduleTime = "02:00"  # 每天凌晨2点执行
$ENCRYPT_PASSWORD = "your_secure_password_here"  # 设置你的加密密码

# ==================== 函数定义 ====================

function Set-BackupPassword {
    Write-Host ""
    Write-Host "设置备份加密密码" -ForegroundColor Cyan
    Write-Host "========================================="
    Write-Host ""
    Write-Host "此密码将用于加密备份文件，请妥善保管!"
    Write-Host ""
    
    $password = Read-Host "请输入加密密码" -AsSecureString
    $BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($password)
    $plainPassword = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
    
    Write-Host ""
    $confirm = Read-Host "确认设置此密码? (yes/no)"
    
    if ($confirm -eq "yes") {
        # 设置用户环境变量（持久化）
        [Environment]::SetEnvironmentVariable("BACKUP_ENCRYPT_PASSWORD", $plainPassword, "User")
        Write-Host "✓ 密码已保存到用户环境变量" -ForegroundColor Green
        Write-Host ""
        Write-Host "提示: 可以通过以下命令查看环境变量:"
        Write-Host "  `[Environment]::GetEnvironmentVariable('BACKUP_ENCRYPT_PASSWORD', 'User')`"
        return $plainPassword
    } else {
        Write-Host "密码未保存"
        return $null
    }
}

function Test-DockerConnection {
    Write-Host ""
    Write-Host "测试Docker连接..." -ForegroundColor Cyan
    
    try {
        $result = docker ps --filter "name=spug-db" --format "{{.Names}}" 2>&1
        if ($result -match "spug-db") {
            Write-Host "✓ Docker连接正常，数据库容器运行中" -ForegroundColor Green
            return $true
        } else {
            Write-Host "✗ 数据库容器 spug-db 未运行" -ForegroundColor Red
            return $false
        }
    } catch {
        Write-Host "✗ Docker命令执行失败: $_" -ForegroundColor Red
        return $false
    }
}

function Test-BackupScript {
    Write-Host ""
    Write-Host "测试备份脚本..." -ForegroundColor Cyan
    
    if (-not (Test-Path $ScriptPath)) {
        Write-Host "✗ 备份脚本不存在: $ScriptPath" -ForegroundColor Red
        return $false
    }
    
    Write-Host "✓ 备份脚本存在: $ScriptPath" -ForegroundColor Green
    return $true
}

function Test-OpenSSL {
    Write-Host ""
    Write-Host "测试OpenSSL..." -ForegroundColor Cyan
    
    $openssl = Get-Command openssl -ErrorAction SilentlyContinue
    if ($openssl) {
        $version = & openssl version
        Write-Host "✓ OpenSSL已安装: $version" -ForegroundColor Green
        return $true
    } else {
        Write-Host "✗ OpenSSL未安装" -ForegroundColor Yellow
        Write-Host "提示: 安装OpenSSL以启用备份加密功能"
        Write-Host "下载地址: https://slproweb.com/products/Win32OpenSSL.html"
        return $false
    }
}

function Register-ScheduledTask {
    param([string]$TaskName, [string]$ScriptPath, [string]$ScheduleTime)
    
    Write-Host ""
    Write-Host "创建计划任务..." -ForegroundColor Cyan
    Write-Host "========================================="
    Write-Host "任务名称: $TaskName"
    Write-Host "脚本路径: $ScriptPath"
    Write-Host "执行时间: 每天 $ScheduleTime"
    Write-Host "========================================="
    Write-Host ""
    
    $confirm = Read-Host "确认创建计划任务? (yes/no)"
    
    if ($confirm -ne "yes") {
        Write-Host "取消创建计划任务"
        return $false
    }
    
    try {
        # 检查是否已存在同名任务
        $existingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
        if ($existingTask) {
            Write-Host "发现已存在的计划任务，是否删除并重新创建?"
            $recreate = Read-Host "重新创建? (yes/no)"
            if ($recreate -eq "yes") {
                Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
                Write-Host "✓ 已删除旧任务" -ForegroundColor Green
            } else {
                Write-Host "保留现有任务"
                return $false
            }
        }
        
        # 创建计划任务
        $action = New-ScheduledTaskAction -Execute "PowerShell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""
        $trigger = New-ScheduledTaskTrigger -Daily -At $ScheduleTime
        $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
        
        Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force | Out-Null
        
        Write-Host ""
        Write-Host "✓ 计划任务创建成功!" -ForegroundColor Green
        Write-Host ""
        Write-Host "任务详情:"
        Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName, State, NextRunTime | Format-Table -AutoSize
        
        return $true
    } catch {
        Write-Host "✗ 计划任务创建失败: $_" -ForegroundColor Red
        return $false
    }
}

function Show-ManualRunInstructions {
    Write-Host ""
    Write-Host "========================================="
    Write-Host "手动运行备份" -ForegroundColor Cyan
    Write-Host "========================================="
    Write-Host ""
    Write-Host "1. 打开PowerShell，切换到备份目录:"
    Write-Host "   cd $($PSScriptRoot)"
    Write-Host ""
    Write-Host "2. 执行备份脚本:"
    Write-Host "   .\auto_backup.ps1"
    Write-Host ""
    Write-Host "3. 查看备份文件:"
    Write-Host "   cd backups"
    Write-Host "   dir"
    Write-Host ""
}

function Show-ScheduledTaskCommands {
    Write-Host ""
    Write-Host "========================================="
    Write-Host "计划任务管理命令" -ForegroundColor Cyan
    Write-Host "========================================="
    Write-Host ""
    Write-Host "查看任务状态:"
    Write-Host "  Get-ScheduledTask -TaskName '$TaskName'"
    Write-Host ""
    Write-Host "启动任务:"
    Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
    Write-Host ""
    Write-Host "停止任务:"
    Write-Host "  Stop-ScheduledTask -TaskName '$TaskName'"
    Write-Host ""
    Write-Host "禁用任务:"
    Write-Host "  Disable-ScheduledTask -TaskName '$TaskName'"
    Write-Host ""
    Write-Host "启用任务:"
    Write-Host "  Enable-ScheduledTask -TaskName '$TaskName'"
    Write-Host ""
    Write-Host "删除任务:"
    Write-Host "  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
    Write-Host ""
    Write-Host "查看任务历史:"
    Write-Host "  Get-EventLog -LogName 'Microsoft-Windows-TaskScheduler/Operational' -Source 'TaskScheduler' -Newest 20"
    Write-Host ""
}

# ==================== 主流程 ====================

Write-Host "========================================="
Write-Host "Spug Windows开发环境自动备份配置"
Write-Host "========================================="
Write-Host ""

# 检查管理员权限
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "⚠ 警告: 需要管理员权限创建计划任务" -ForegroundColor Yellow
    Write-Host "请以管理员身份运行PowerShell"
    Write-Host ""
}

# 环境检查
Write-Host "环境检查:"
Write-Host "========================================="

$dockerOk = Test-DockerConnection
$scriptOk = Test-BackupScript
$opensslOk = Test-OpenSSL

Write-Host ""
Write-Host "检查结果:" -ForegroundColor Cyan
Write-Host "  Docker: $(if ($dockerOk) { '✓ 通过' } else { '✗ 失败' })"
Write-Host "  备份脚本: $(if ($scriptOk) { '✓ 通过' } else { '✗ 失败' })"
Write-Host "  OpenSSL: $(if ($opensslOk) { '✓ 通过' } else { '⚠ 未安装' })"

if (-not $dockerOk -or -not $scriptOk) {
    Write-Host ""
    Write-Host "✗ 环境检查失败，请修复后重试" -ForegroundColor Red
    exit 1
}

# 设置加密密码
$password = Set-BackupPassword
if (-not $password) {
    Write-Host ""
    Write-Host "⚠ 警告: 未设置加密密码" -ForegroundColor Yellow
    Write-Host "备份文件将不会加密"
    Write-Host ""
    $continue = Read-Host "继续配置? (yes/no)"
    if ($continue -ne "yes") {
        exit 0
    }
}

# 创建计划任务
if ($isAdmin) {
    $taskCreated = Register-ScheduledTask $TaskName $ScriptPath $ScheduleTime
    
    if ($taskCreated) {
        Show-ScheduledTaskCommands
    }
} else {
    Write-Host ""
    Write-Host "⚠ 需要管理员权限创建计划任务" -ForegroundColor Yellow
    Write-Host "请以管理员身份运行此脚本"
    Write-Host ""
    Show-ManualRunInstructions
}

Write-Host ""
Write-Host "========================================="
Write-Host "配置完成!" -ForegroundColor Green
Write-Host "========================================="

Show-ManualRunInstructions

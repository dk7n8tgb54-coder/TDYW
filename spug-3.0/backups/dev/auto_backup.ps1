# Spug Windows开发环境自动备份脚本
# 使用方法: .\auto_backup.ps1
# 建议使用Windows任务计划程序设置每日执行

# ==================== 配置区域 ====================

# 数据库配置
$DB_CONTAINER = "spug-db"
$DB_NAME = "spug"
$DB_USER = "spug"
$DB_PASS = "spug.cc"

# 备份文件保存目录
$BACKUP_DIR = Join-Path $PSScriptRoot "backups"
if (-not (Test-Path $BACKUP_DIR)) {
    New-Item -ItemType Directory -Path $BACKUP_DIR -Force | Out-Null
}

# 保留最近多少天的备份
$RETENTION_DAYS = 7

# 加密配置
$ENCRYPT = $true
$ENCRYPT_METHOD = "openssl"
# 建议使用Windows环境变量: [Environment]::SetEnvironmentVariable("BACKUP_ENCRYPT_PASSWORD", "your_password", "User")
$ENCRYPT_PASSWORD = $env:BACKUP_ENCRYPT_PASSWORD
if (-not $ENCRYPT_PASSWORD) {
    $ENCRYPT_PASSWORD = "your_secure_password_here"
}

# 日志文件
$LOG_FILE = Join-Path $BACKUP_DIR "auto_backup.log"

# ==================== 函数定义 ====================

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logLine = "[$timestamp] $Message"
    Write-Host $logLine
    Add-Content -Path $LOG_FILE -Value $logLine
}

function Invoke-OpenSSLEncrypt {
    param([string]$InputFile, [string]$Password)
    
    $openssl = Get-Command openssl -ErrorAction SilentlyContinue
    if (-not $openssl) {
        Write-Log "OpenSSL未找到，跳过加密"
        return $InputFile
    }
    
    $OutputFile = "${InputFile}.enc"
    try {
        & openssl enc -aes-256-cbc -salt -in $InputFile -out $OutputFile -k $Password 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Remove-Item $InputFile -Force
            Write-Log "✓ OpenSSL加密成功"
            return $OutputFile
        } else {
            Write-Log "✗ OpenSSL加密失败"
            return $InputFile
        }
    } catch {
        Write-Log "✗ 加密出错: $_"
        return $InputFile
    }
}

function Invoke-GzipCompress {
    param([string]$InputFile)
    
    $OutputFile = "${InputFile}.gz"
    try {
        $7zip = Get-Command 7z -ErrorAction SilentlyContinue
        if ($7zip) {
            & 7z a -tgzip $OutputFile $InputFile -y | Out-Null
        } else {
            $bytes = [System.IO.File]::ReadAllBytes($InputFile)
            $outputStream = [System.IO.File]::Create($OutputFile)
            $gzipStream = New-Object System.IO.Compression.GZipStream($outputStream, [System.IO.Compression.CompressionLevel]::Optimal)
            $gzipStream.Write($bytes, 0, $bytes.Length)
            $gzipStream.Close()
            $outputStream.Close()
        }
        
        Remove-Item $InputFile -Force
        Write-Log "✓ 压缩成功"
        return $OutputFile
    } catch {
        Write-Log "✗ 压缩失败: $_"
        return $InputFile
    }
}

# ==================== 备份流程 ====================

Write-Log "========================================="
Write-Log "Spug Windows开发环境自动备份开始"
Write-Log "========================================="

# 检查Docker
try {
    $dockerPs = docker ps --filter "name=$DB_CONTAINER" --format "{{.Names}}" 2>&1
    if (-not $dockerPs -or $dockerPs -notmatch $DB_CONTAINER) {
        Write-Log "✗ 数据库容器 $DB_CONTAINER 未运行!"
        exit 1
    }
    Write-Log "✓ 数据库容器运行正常"
} catch {
    Write-Log "✗ Docker命令执行失败: $_"
    exit 1
}

# 获取当前日期
$TODAY = Get-Date -Format "yyyyMMdd"
$BACKUP_FILE = Join-Path $BACKUP_DIR "spug_dev_auto_${TODAY}.sql"

# 执行备份
Write-Log "开始备份数据库: $DB_NAME"
try {
    docker exec $DB_CONTAINER mysqldump -h localhost -P 3306 -u $DB_USER -p$DB_PASS `
        --single-transaction `
        --routines `
        --triggers `
        --events `
        --databases $DB_NAME --result-file $BACKUP_FILE 2>&1 | Out-Null
    
    if (Test-Path $BACKUP_FILE) {
        $size = [math]::Round((Get-Item $BACKUP_FILE).Length / 1KB, 2)
        Write-Log "✓ 数据库备份成功 (${size} KB)"
    } else {
        Write-Log "✗ 数据库备份失败!"
        exit 1
    }
} catch {
    Write-Log "✗ 备份出错: $_"
    exit 1
}

# 压缩
$COMPRESSED_FILE = Invoke-GzipCompress $BACKUP_FILE
if (-not $COMPRESSED_FILE.EndsWith(".gz")) {
    Write-Log "✗ 压缩失败"
    exit 1
}

# 加密
if ($ENCRYPT) {
    if ($ENCRYPT_METHOD -eq "openssl") {
        $FINAL_FILE = Invoke-OpenSSLEncrypt $COMPRESSED_FILE $ENCRYPT_PASSWORD
        if (-not $FINAL_FILE.EndsWith(".enc")) {
            Write-Log "✗ 加密失败"
            exit 1
        }
    }
}

# 清理旧备份
Write-Log ""
Write-Log "清理超过 $RETENTION_DAYS 天的旧备份..."
$DELETED = 0
$cutoffDate = (Get-Date).AddDays(-$RETENTION_DAYS)

if ($ENCRYPT) {
    Get-ChildItem $BACKUP_DIR -Filter "spug_dev_auto_*.sql.gz.enc" | Where-Object {
        $_.LastWriteTime -lt $cutoffDate
    } | ForEach-Object {
        Remove-Item $_.FullName -Force
        $DELETED++
    }
} else {
    Get-ChildItem $BACKUP_DIR -Filter "spug_dev_auto_*.sql.gz" | Where-Object {
        $_.LastWriteTime -lt $cutoffDate
    } | ForEach-Object {
        Remove-Item $_.FullName -Force
        $DELETED++
    }
}

Write-Log "✓ 已删除 $DELETED 个旧备份文件"

# 统计当前备份
Write-Log ""
Write-Log "当前备份文件:"
$backupFiles = Get-ChildItem $BACKUP_DIR -Filter "spug_dev_auto_*"
$backupCount = $backupFiles.Count
$totalSize = ($backupFiles | Measure-Object -Property Length -Sum).Sum
$totalSizeKB = [math]::Round($totalSize / 1KB, 2)

Write-Log "  备份文件数: $backupCount"
Write-Log "  总大小: ${totalSizeKB} KB"

Write-Log ""
Write-Log "========================================="
Write-Log "✓ 自动备份完成!"
Write-Log "========================================="

# 验证备份文件
$FINAL_BACKUP = Get-ChildItem $BACKUP_DIR -Filter "spug_dev_auto_*.sql.gz.enc" | 
    Where-Object { $_.LastWriteTime -gt (Get-Date).AddMinutes(-5) } | 
    Select-Object -First 1

if ($FINAL_BACKUP) {
    $size = $FINAL_BACKUP.Length
    if ($size -lt 1024) {
        Write-Log "⚠ 警告: 备份文件太小 (${size} bytes)，可能备份失败!"
    } else {
        Write-Log "✓ 备份文件验证通过: $size bytes"
    }
} else {
    Write-Log "⚠ 警告: 未找到今天的备份文件!"
}

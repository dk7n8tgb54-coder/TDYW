# Spug Windows开发环境备份恢复脚本
# 使用方法: .\restore.ps1 <backup_file>
# 示例: .\restore.ps1 spug_dev_backup_20240101_120000.sql.gz.enc

# ==================== 配置区域 ====================

# 数据库配置
$DB_NAME = "spug"
$DB_USER = "spug"
$DB_PASS = "spug.cc"
$DB_CONTAINER = "spug-db"

# 加密配置
$ENCRYPT_PASSWORD = $env:BACKUP_ENCRYPT_PASSWORD
if (-not $ENCRYPT_PASSWORD) {
    $ENCRYPT_PASSWORD = "your_secure_password_here"
}

# ==================== 函数定义 ====================

function Show-Usage {
    Write-Host "使用方法: .\restore.ps1 <backup_file>"
    Write-Host ""
    Write-Host "示例:"
    Write-Host "  .\restore.ps1 spug_dev_backup_20240101_120000.sql.gz.enc"
    Write-Host ""
    Write-Host "环境变量:"
    Write-Host "  BACKUP_ENCRYPT_PASSWORD  - 备份加密密码"
    exit 1
}

function Test-Environment {
    param([string]$BackupFile)
    
    if ($BackupFile -match "dev") {
        return "dev"
    } elseif ($BackupFile -match "prod") {
        return "prod"
    } else {
        return "unknown"
    }
}

function Invoke-OpenSSLDecrypt {
    param([string]$InputFile, [string]$Password)
    
    if ($InputFile -notmatch "\.enc$") {
        Write-Host "备份文件未加密"
        return $InputFile
    }
    
    Write-Host "正在解密备份文件..."
    $openssl = Get-Command openssl -ErrorAction SilentlyContinue
    if (-not $openssl) {
        Write-Host "✗ OpenSSL未找到" -ForegroundColor Red
        exit 1
    }
    
    $OutputFile = $InputFile -replace '\.enc$', ''
    try {
        & openssl enc -aes-256-cbc -d -in $InputFile -out $OutputFile -k $Password 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ 解密成功" -ForegroundColor Green
            return $OutputFile
        } else {
            Write-Host "✗ 解密失败! 请检查密码" -ForegroundColor Red
            exit 1
        }
    } catch {
        Write-Host "✗ 解密出错: $_" -ForegroundColor Red
        exit 1
    }
}

function Invoke-GzipDecompress {
    param([string]$InputFile)
    
    if ($InputFile -notmatch "\.gz$") {
        Write-Host "备份文件未压缩"
        return $InputFile
    }
    
    Write-Host "正在解压备份文件..."
    $7zip = Get-Command 7z -ErrorAction SilentlyContinue
    $OutputFile = $InputFile -replace '\.gz$', ''
    
    try {
        if ($7zip) {
            & 7z x $InputFile -y -o$(Split-Path $OutputFile) | Out-Null
        } else {
            $inputStream = [System.IO.File]::OpenRead($InputFile)
            $gzipStream = New-Object System.IO.Compression.GZipStream($inputStream, [System.IO.Compression.CompressionMode]::Decompress)
            $outputStream = [System.IO.File]::Create($OutputFile)
            $gzipStream.CopyTo($outputStream)
            $gzipStream.Close()
            $inputStream.Close()
            $outputStream.Close()
        }
        
        Write-Host "✓ 解压成功" -ForegroundColor Green
        return $OutputFile
    } catch {
        Write-Host "✗ 解压失败: $_" -ForegroundColor Red
        exit 1
    }
}

# ==================== 主流程 ====================

# 检查参数
if ($args.Count -lt 1) {
    Show-Usage
}

$BACKUP_FILE = $args[0]

# 检查备份文件是否存在
if (-not (Test-Path $BACKUP_FILE)) {
    Write-Host "✗ 备份文件不存在: $BACKUP_FILE" -ForegroundColor Red
    exit 1
}

Write-Host "========================================="
Write-Host "Spug 数据库备份恢复"
Write-Host "========================================="
Write-Host "备份文件: $BACKUP_FILE"
$fileSize = [math]::Round((Get-Item $BACKUP_FILE).Length / 1KB, 2)
Write-Host "备份大小: ${fileSize} KB"

# 解密
$DECRYPTED_FILE = Invoke-OpenSSLDecrypt $BACKUP_FILE $ENCRYPT_PASSWORD

# 解压
$DECOMPRESSED_FILE = Invoke-GzipDecompress $DECRYPTED_FILE

# 恢复数据库
Write-Host ""
Write-Host "========================================="
Write-Host "恢复配置:"
Write-Host "  容器: $DB_CONTAINER"
Write-Host "  数据库: $DB_NAME"
Write-Host "========================================="

# 检查容器是否运行
try {
    $dockerPs = docker ps --filter "name=$DB_CONTAINER" --format "{{.Names}}" 2>&1
    if (-not $dockerPs -or $dockerPs -notmatch $DB_CONTAINER) {
        Write-Host "✗ 数据库容器 $DB_CONTAINER 未运行!" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "✗ Docker命令执行失败: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "开始恢复数据库..."
Write-Host "⚠ 警告: 此操作将覆盖当前数据库!" -ForegroundColor Yellow
Write-Host ""
$confirm = Read-Host "确认恢复? (yes/no)"

if ($confirm -ne "yes") {
    Write-Host "取消恢复"
    exit 0
}

# 恢复数据库
try {
    docker exec -i $DB_CONTAINER mysql -u $DB_USER -p$DB_PASS $DB_NAME < $DECOMPRESSED_FILE
    
    Write-Host "✓ 数据库恢复成功!" -ForegroundColor Green
} catch {
    Write-Host "✗ 数据库恢复失败!" -ForegroundColor Red
    Write-Host "错误: $_"
    exit 1
}

# 清理临时文件
Write-Host ""
Write-Host "清理临时文件..."
Remove-Item $DECOMPRESSED_FILE -Force -ErrorAction SilentlyContinue
if ($DECRYPTED_FILE -ne $BACKUP_FILE) {
    Remove-Item $DECRYPTED_FILE -Force -ErrorAction SilentlyContinue
}
Write-Host "✓ 清理完成"

Write-Host ""
Write-Host "========================================="
Write-Host "✓ 数据库恢复完成!" -ForegroundColor Green
Write-Host "========================================="

# Spug Windows开发环境手动备份脚本
# 使用方法: .\manual_backup.ps1

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

# 备份文件名（包含时间戳）
$TIMESTAMP = Get-Date -Format "yyyyMMdd_HHmmss"
$BACKUP_FILE = Join-Path $BACKUP_DIR "spug_dev_backup_${TIMESTAMP}.sql"

# 加密配置
$ENCRYPT = $true
$ENCRYPT_METHOD = "openssl"
$ENCRYPT_PASSWORD = "your_secure_password_here"

# ==================== 函数定义 ====================

function Invoke-OpenSSLEncrypt {
    param([string]$InputFile, [string]$Password)
    
    Write-Host "正在使用OpenSSL加密备份文件..."
    $OutputFile = "${InputFile}.enc"
    
    # 检查OpenSSL是否可用
    $openssl = Get-Command openssl -ErrorAction SilentlyContinue
    if (-not $openssl) {
        Write-Host "✗ OpenSSL未找到，跳过加密" -ForegroundColor Yellow
        return $InputFile
    }
    
    try {
        & openssl enc -aes-256-cbc -salt -in $InputFile -out $OutputFile -k $Password 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Remove-Item $InputFile -Force
            Write-Host "✓ 加密成功: $OutputFile" -ForegroundColor Green
            return $OutputFile
        } else {
            Write-Host "✗ 加密失败!" -ForegroundColor Red
            return $InputFile
        }
    } catch {
        Write-Host "✗ 加密出错: $_" -ForegroundColor Red
        return $InputFile
    }
}

function Invoke-GzipCompress {
    param([string]$InputFile)
    
    Write-Host "正在压缩备份文件..."
    $OutputFile = "${InputFile}.gz"
    
    try {
        # 使用7-Zip压缩（如果可用）
        $7zip = Get-Command 7z -ErrorAction SilentlyContinue
        if ($7zip) {
            & 7z a -tgzip $OutputFile $InputFile -y | Out-Null
        } else {
            # 使用PowerShell原生压缩
            $content = Get-Content $InputFile -Raw -Encoding UTF8
            $bytes = [System.IO.File]::ReadAllBytes($InputFile)
            $outputStream = [System.IO.File]::Create($OutputFile)
            $gzipStream = New-Object System.IO.Compression.GZipStream($outputStream, [System.IO.Compression.CompressionLevel]::Optimal)
            $gzipStream.Write($bytes, 0, $bytes.Length)
            $gzipStream.Close()
            $outputStream.Close()
        }
        
        Remove-Item $InputFile -Force
        $size = [math]::Round((Get-Item $OutputFile).Length / 1KB, 2)
        Write-Host "✓ 压缩成功: $OutputFile (${size} KB)" -ForegroundColor Green
        return $OutputFile
    } catch {
        Write-Host "✗ 压缩失败: $_" -ForegroundColor Red
        return $InputFile
    }
}

# ==================== 备份流程 ====================

Write-Host "========================================="
Write-Host "Spug Windows开发环境数据库手动备份"
Write-Host "备份时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "========================================="

# 检查Docker是否运行
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

Write-Host "✓ 数据库容器运行正常" -ForegroundColor Green

# 执行数据库备份
Write-Host ""
Write-Host "开始备份数据库: $DB_NAME"

try {
    docker exec $DB_CONTAINER mysqldump -h localhost -P 3306 -u $DB_USER -p$DB_PASS `
        --single-transaction `
        --routines `
        --triggers `
        --events `
        --databases $DB_NAME --result-file $BACKUP_FILE
    
    if (Test-Path $BACKUP_FILE) {
        $size = [math]::Round((Get-Item $BACKUP_FILE).Length / 1KB, 2)
        Write-Host "✓ 数据库备份成功 (${size} KB)" -ForegroundColor Green
    } else {
        Write-Host "✗ 数据库备份失败!" -ForegroundColor Red
        exit 1
    }
} catch {
    Write-Host "✗ 备份出错: $_" -ForegroundColor Red
    exit 1
}

# 压缩备份文件
$COMPRESSED_FILE = Invoke-GzipCompress $BACKUP_FILE

# 加密备份文件
if ($ENCRYPT) {
    if ($ENCRYPT_METHOD -eq "openssl") {
        $FINAL_FILE = Invoke-OpenSSLEncrypt $COMPRESSED_FILE $ENCRYPT_PASSWORD
    }
}

# 显示备份文件列表
Write-Host ""
Write-Host "备份完成!"
Write-Host "备份文件列表:"
Get-ChildItem $BACKUP_DIR -Filter "spug_dev_backup_*" | Sort-Object LastWriteTime -Descending | Select-Object -First 5 | ForEach-Object {
    $size = [math]::Round($_.Length / 1KB, 2)
    Write-Host "  $($_.Name) (${size} KB)"
}

Write-Host ""
Write-Host "========================================="
Write-Host "✓ 手动备份完成!" -ForegroundColor Green
Write-Host "========================================="

# 显示恢复提示
if ($ENCRYPT) {
    Write-Host ""
    Write-Host "恢复备份命令:"
    Write-Host "openssl enc -aes-256-cbc -d -in $FINAL_FILE -k `"$ENCRYPT_PASSWORD`" | gunzip | docker exec -i $DB_CONTAINER mysql -u$DB_USER -p$DB_PASS $DB_NAME"
}

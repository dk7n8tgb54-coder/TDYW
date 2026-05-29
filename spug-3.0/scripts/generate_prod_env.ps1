# 生成安全的 .env.prod 配置
Write-Host "=== 生成生产环境配置 ===" -ForegroundColor Cyan
Write-Host ""

# 生成随机密码
$mysqlPassword = -join ((48..57) + (65..90) + (97..122) + [char[]]'!@#$%^&*()' | Get-Random -Count 32)
$rootPassword = -join ((48..57) + (65..90) + (97..122) + [char[]]'!@#$%^&*()' | Get-Random -Count 32)

# 生成 Django SECRET_KEY
# 使用 Python 生成更安全的密钥
try {
    $secretKey = python -c "import secrets; print(secrets.token_urlsafe(50))" 2>$null
    if (-not $secretKey) {
        # 如果 Python 不可用，使用 PowerShell 生成
        $secretKey = -join ((48..57) + (65..90) + (97..122) + [char[]]'!@#$%^&*-_=' | Get-Random -Count 50)
    }
} catch {
    $secretKey = -join ((48..57) + (65..90) + (97..122) + [char[]]'!@#$%^&*-_=' | Get-Random -Count 50)
}

# 询问是否设置 ALLOWED_HOSTS
Write-Host "请输入允许访问的主机（IP或域名），多个用逗号分隔：" -ForegroundColor Yellow
Write-Host "示例: 192.168.1.100,spug.company.com" -ForegroundColor Gray
Write-Host "如果不输入，默认为 * (允许所有)" -ForegroundColor Gray
$allowedHosts = Read-Host "ALLOWED_HOSTS"
if ([string]::IsNullOrWhiteSpace($allowedHosts)) {
    $allowedHosts = "*"
}

Write-Host ""
Write-Host "生成的配置：" -ForegroundColor Cyan
Write-Host "MYSQL_PASSWORD: $mysqlPassword" -ForegroundColor Yellow
Write-Host "MYSQL_ROOT_PASSWORD: $rootPassword" -ForegroundColor Yellow
Write-Host "DJANGO_SECRET_KEY: $secretKey" -ForegroundColor Yellow
Write-Host "ALLOWED_HOSTS: $allowedHosts" -ForegroundColor Yellow
Write-Host ""

$confirm = Read-Host "确认写入到 .env.prod 吗？(yes/no)"
if ($confirm -ne 'yes') {
    Write-Host "已取消。" -ForegroundColor Red
    exit 0
}

# 写入 .env.prod
@"
# Spug Docker 生产环境配置
# ⚠️ 注意：.env.prod文件包含敏感信息，请不要提交到版本控制系统
# 将 .env.prod 添加到 .gitignore

# 数据库配置
MYSQL_DATABASE=spug
MYSQL_USER=spug
MYSQL_PASSWORD=$mysqlPassword
MYSQL_ROOT_PASSWORD=$rootPassword

# Django配置
DJANGO_SECRET_KEY=$secretKey

# 允许的主机
ALLOWED_HOSTS=$allowedHosts

# 生产环境部署建议：
# 1. 定期备份数据库和文档文件
# 2. 配置 HTTPS（SSL证书）
# 3. 监控容器日志和资源使用
# 4. 定期更新镜像和依赖
"@ | Out-File -FilePath ".env.prod" -Encoding UTF8

Write-Host ""
Write-Host "✓ .env.prod 已生成" -ForegroundColor Green
Write-Host ""
Write-Host "重要提示：请妥善保存密码，建议将密码存储到密码管理器中" -ForegroundColor Yellow
Write-Host "文件位置: $(Resolve-Path .env.prod)" -ForegroundColor Gray

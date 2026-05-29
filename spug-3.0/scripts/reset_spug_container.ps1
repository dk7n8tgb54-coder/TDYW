# Spug容器重置脚本

Write-Host "=== 重置Spug容器 ===" -ForegroundColor Green

# 1. 停止服务
Write-Host "`n[1/4] 停止服务..." -ForegroundColor Yellow
docker-compose stop

# 2. 删除容器
Write-Host "`n[2/4] 删除容器..." -ForegroundColor Yellow
docker-compose rm -f

# 3. 删除旧的数据（可选，如果不需要保留数据则取消注释）
# Write-Host "`n[2.5] 清理旧数据..." -ForegroundColor Yellow
# docker volume rm spug_mysql_data

# 4. 重新启动
Write-Host "`n[3/4] 启动服务..." -ForegroundColor Yellow
docker-compose up -d

# 5. 等待启动
Write-Host "`n[4/4] 等待服务启动..." -ForegroundColor Yellow
Start-Sleep -Seconds 20

# 6. 检查状态
Write-Host "`n=== 检查服务状态 ===" -ForegroundColor Green
docker ps | Select-String "spug"

# 7. 查看日志
Write-Host "`n=== Spug服务日志 ===" -ForegroundColor Green
docker logs spug --tail 20

Write-Host "`n=== 完成 ===" -ForegroundColor Green
Write-Host "如果服务正常运行，现在可以访问 http://localhost" -ForegroundColor Cyan

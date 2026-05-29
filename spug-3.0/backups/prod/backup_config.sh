#!/bin/bash

# ============================================================================
# Spug 生产环境备份配置文件
# 注意: 请确保此文件权限为 600，避免敏感信息泄露
# ============================================================================

# 数据库配置
DB_CONTAINER="spug-db-prod"
DB_NAME="spug"
DB_USER="spug"
# 数据库密码通过环境变量 MYSQL_PASSWORD 传递

# 备份配置
RETENTION_DAYS=30  # 保留备份天数
ENCRYPT=true       # 是否加密备份
ENCRYPT_METHOD="openssl"  # 加密方法
# 加密密码通过环境变量 BACKUP_ENCRYPT_PASSWORD 传递

# 备份内容配置
BACKUP_CONFIG_FILES=true  # 是否备份配置文件
BACKUP_APP_DATA=true      # 是否备份应用数据

# 配置文件备份路径
CONFIG_PATHS=(
    "e:/TDYW/spug-3.0/spug_api/spug/settings.py"
    "e:/TDYW/spug-3.0/.env"
    "e:/TDYW/spug-3.0/config/prod/nginx.conf"
)

# 应用数据备份路径
APP_DATA_PATHS=(
    "e:/TDYW/spug-3.0/data/storage"
    "e:/TDYW/spug-3.0/spug_web/public/resource"
)

# 异地备份配置
REMOTE_BACKUP_ENABLED=false
REMOTE_HOST="192.168.1.200"
REMOTE_USER="backup"
REMOTE_DIR="/data/spug_backups"
# SSH 私钥路径通过环境变量 SSH_PRIVATE_KEY 传递

# 云存储配置
CLOUD_BACKUP_ENABLED=false
CLOUD_PROVIDER="s3"  # 支持 s3, oss, cos 等
S3_ENDPOINT="https://s3.amazonaws.com"
S3_BUCKET="spug-backups"
# S3 访问密钥通过环境变量 S3_ACCESS_KEY 和 S3_SECRET_KEY 传递
S3_REGION="us-east-1"

# 日志配置
LOG_LEVEL="info"  # 日志级别: debug, info, warn, error
LOG_ROTATE=true   # 是否启用日志轮转
LOG_MAX_SIZE=10   # 日志文件最大大小 (MB)
LOG_MAX_BACKUPS=5 # 保留日志文件数量

# 告警通知配置
ALERT_ENABLED=false       # 是否启用告警
ALERT_LEVEL="error"       # 告警级别: info, warn, error
ALERT_EMAIL_ENABLED=false # 是否启用邮件告警
ALERT_EMAIL_TO="admin@example.com" # 收件人邮箱
ALERT_EMAIL_FROM="backup@example.com" # 发件人邮箱
ALERT_EMAIL_SMTP="smtp.example.com" # SMTP服务器
ALERT_EMAIL_PORT=587      # SMTP端口
ALERT_EMAIL_USER="backup" # SMTP用户名
# ALERT_EMAIL_PASS 通过环境变量传递

ALERT_DINGTALK_ENABLED=false # 是否启用钉钉告警
ALERT_DINGTALK_WEBHOOK="https://oapi.dingtalk.com/robot/send?access_token=your_token" # 钉钉webhook

ALERT_WECHAT_ENABLED=false # 是否启用企业微信告警
ALERT_WECHAT_WEBHOOK="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=your_key" # 企业微信webhook

# 状态报告配置
REPORT_ENABLED=false       # 是否启用状态报告
REPORT_EMAIL_ENABLED=false # 是否通过邮件发送报告
REPORT_EMAIL_TO="admin@example.com" # 报告收件人

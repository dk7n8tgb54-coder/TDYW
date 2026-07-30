# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""
统一告警入口

三路输出：DB Alert 表（持久化）+ Redis List（快速读取）+ SMTP 邮件
限流去重：同一 alert_key 在冷却期内不重复发送
"""
import logging
import smtplib
from email.mime.text import MIMEText

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# 按来源分级限流（秒）
# 瞬态事件（任务失败、API 异常）5 分钟，持续状态（磁盘满、连接数高）30 分钟
_ALERT_COOLDOWN = {
    'celery': 300,
    'middleware': 300,
    'disk': 1800,
    'db': 1800,
}
_DEFAULT_COOLDOWN = 300


def send_alert(title, message, level='warning', source='system', alert_key=None):
    """
    统一告警入口

    :param title: 告警标题（简短）
    :param message: 告警详情（可多行）
    :param level: 'error' | 'warning' | 'info'
    :param source: 'celery' | 'middleware' | 'disk' | 'db' | 'system'
    :param alert_key: 去重键，相同 key 在冷却期内不重复发送
    """
    # 限流去重
    if alert_key:
        cache_key = f'alert:sent:{alert_key}'
        cooldown = _ALERT_COOLDOWN.get(source, _DEFAULT_COOLDOWN)
        if cache.get(cache_key):
            logger.debug(f'[ALERT] 跳过重复告警: {alert_key}')
            return
        cache.set(cache_key, 1, cooldown)

    # 1. 写入数据库（持久化）
    alert = _persist_alert(title, message, level, source, alert_key)

    # 2. 写入 Redis List（前端快速读取最近告警）
    _push_to_cache(alert)

    # 3. 发送邮件
    _send_email(title, message, level)

    # 4. 始终写日志（兜底）
    log_method = logger.error if level == 'error' else logger.warning
    log_method(f'[ALERT][{level.upper()}] {title}: {message}')


def _persist_alert(title, message, level, source, alert_key):
    """写入数据库持久化"""
    try:
        from apps.alert.models import Alert
        return Alert.objects.create(
            title=title[:200],
            message=message,
            level=level,
            source=source,
            alert_key=alert_key or '',
        )
    except Exception as e:
        logger.error(f'[ALERT] 持久化告警失败: {e}')
        return None


def _push_to_cache(alert):
    """写入 Redis List，前端读取最近告警"""
    import json
    if not alert:
        return
    data = json.dumps({
        'id': alert.id,
        'title': alert.title,
        'message': alert.message,
        'level': alert.level,
        'source': alert.source,
        'created_at': alert.created_at.isoformat() if alert.created_at else None,
    })
    cache.lpush('alerts:recent', data)
    cache.ltrim('alerts:recent', 0, 49)  # 只保留最近 50 条


def _send_email(title, message, level):
    """通过 SMTP 发送告警邮件"""
    smtp_config = getattr(settings, 'ALERT_SMTP', None)
    if not smtp_config or not smtp_config.get('host'):
        return  # 未配置 SMTP 则跳过

    try:
        subject = f'[{level.upper()}] {title}'
        msg = MIMEText(message, 'plain', 'utf-8')
        msg['Subject'] = subject
        msg['From'] = smtp_config['from']
        msg['To'] = ', '.join(smtp_config['to'])

        with smtplib.SMTP(
            smtp_config['host'],
            smtp_config.get('port', 25),
            timeout=10
        ) as server:
            if smtp_config.get('username'):
                server.login(smtp_config['username'], smtp_config['password'])
            server.send_message(msg)
    except Exception as e:
        logger.error(f'[ALERT] 邮件发送失败: {e}')

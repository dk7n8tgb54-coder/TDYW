#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Celery 健康检查模块
用于监控 Celery Broker 和 Worker 状态
"""
import logging
from spug.celery import app as celery_app

logger = logging.getLogger(__name__)


def check_celery_health():
    """
    检查Celery Broker连接与Worker存活
    【修正4】ping为None(Broker不可达/无Worker)时返回error而非warning
    """
    try:
        inspector = celery_app.control.inspect(timeout=5)
        ping = inspector.ping()
        
        # 【修正】严格判断：
        # - ping为None: Broker不可达或无任何Worker响应 → error
        # - ping为空字典: 有Broker但无Worker注册 → error  
        # - ping有内容: Worker正常响应 → ok
        if ping is None:
            logger.error('[HealthCheck] Celery Broker不可达或inspector调用失败')
            return {
                'status': 'error',
                'error': 'Celery Broker不可达',
                'workers': 0
            }
        
        if not ping:  # 空字典
            logger.error('[HealthCheck] Celery Broker可达但无存活Worker')
            return {
                'status': 'error',
                'error': '无存活Celery Worker',
                'workers': 0
            }
        
        # 统计Worker数量
        worker_count = len(ping)
        logger.info(f'[HealthCheck] Celery健康检查通过: {worker_count}个Worker存活')
        return {
            'status': 'ok',
            'workers': worker_count,
            'details': list(ping.keys())
        }
        
    except Exception as e:
        logger.error(f'[HealthCheck] Celery健康检查异常: {e}')
        return {
            'status': 'error',
            'error': f'检查异常: {str(e)}',
            'workers': 0
        }


def get_celery_stats():
    """
    获取Celery详细统计信息
    """
    try:
        inspector = celery_app.control.inspect(timeout=5)
        
        stats = {
            'ping': None,
            'active': None,
            'scheduled': None,
            'reserved': None,
            'active_queues': None,
        }
        
        try:
            stats['ping'] = inspector.ping()
        except Exception as e:
            logger.warning(f'[HealthCheck] ping检查失败: {e}')
        
        try:
            stats['active'] = inspector.active()
        except Exception as e:
            logger.warning(f'[HealthCheck] active检查失败: {e}')
        
        try:
            stats['scheduled'] = inspector.scheduled()
        except Exception as e:
            logger.warning(f'[HealthCheck] scheduled检查失败: {e}')
        
        try:
            stats['reserved'] = inspector.reserved()
        except Exception as e:
            logger.warning(f'[HealthCheck] reserved检查失败: {e}')
        
        try:
            stats['active_queues'] = inspector.active_queues()
        except Exception as e:
            logger.warning(f'[HealthCheck] active_queues检查失败: {e}')
        
        return stats
        
    except Exception as e:
        logger.error(f'[HealthCheck] 获取Celery统计信息失败: {e}')
        return None


def check_queue_depth(queue_name='celery'):
    """
    检查指定队列的深度
    
    Args:
        queue_name: 队列名称，默认为'celery'
        
    Returns:
        dict: 包含队列深度的信息
    """
    try:
        from kombu import Connection
        
        with Connection(celery_app.conf.broker_url) as conn:
            channel = conn.channel()
            # 注意：这里只是检查连接是否可用，实际队列深度需要更复杂的实现
            return {
                'status': 'ok',
                'queue': queue_name,
                'broker_connected': True
            }
    except Exception as e:
        logger.error(f'[HealthCheck] 检查队列深度失败: {e}')
        return {
            'status': 'error',
            'queue': queue_name,
            'error': str(e)
        }

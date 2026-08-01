# -*- coding: utf-8 -*-
"""
趋势监控工具：基于 Redis Sorted Set 存储历史指标，用线性回归预测趋势。

设计原则：
- 零额外基础设施：复用已有 Redis（django-redis 支持 zadd/zrangebyscore）
- 轻量计算：简单最小二乘法，<1ms / 次
- 自动过期：每次写入时清理 7 天前的旧数据

使用方式：
    from libs.trend import record_metric, get_trend, predict_time_to_threshold

    record_metric('disk:documents', used_bytes)
    trend = get_trend('disk:documents', 24)  # 最近 24 小时
    hours = predict_time_to_threshold(used, total, trend)
"""
import time
import logging

logger = logging.getLogger(__name__)

# 历史数据保留时长（秒）
METRIC_TTL = 7 * 86400  # 7 天


def _get_redis():
    """获取原生 Redis 连接（django-redis 提供的 get_redis_connection）"""
    from django_redis import get_redis_connection
    return get_redis_connection()


def record_metric(name, value):
    """记录指标到 Redis Sorted Set

    Args:
        name: 指标名（如 'disk:documents', 'db:connections'）
        value: 数值（int 或 float）
    """
    key = f'metric:{name}'
    now = time.time()
    try:
        r = _get_redis()
        # ZADD: member 用 '{timestamp}:{value}' 保证唯一，score 是 timestamp
        r.zadd(key, {f'{now}:{value}': now})
        # 清理过期数据
        r.zremrangebyscore(key, 0, now - METRIC_TTL)
    except Exception as e:
        logger.warning(f'[TREND] 记录指标 {name} 失败: {e}')


def get_trend(name, window_hours=24):
    """获取最近 N 小时的趋势数据

    Args:
        name: 指标名
        window_hours: 时间窗口（小时）

    Returns:
        list of (timestamp, value) 元组，按时间升序
    """
    key = f'metric:{name}'
    since = time.time() - window_hours * 3600
    try:
        r = _get_redis()
        rows = r.zrangebyscore(key, since, time.time(), withscores=True)
        # rows: [(member, score), ...] - member 是 bytes，score 是 float
        result = []
        for member, score in rows:
            val = _extract_value(member)
            if val is not None:
                result.append((score, val))
        return result
    except Exception as e:
        logger.warning(f'[TREND] 获取趋势 {name} 失败: {e}')
        return []


def _extract_value(member):
    """从 ZSet member '{timestamp}:{value}' 中提取数值"""
    if isinstance(member, bytes):
        member = member.decode('utf-8')
    try:
        parts = member.rsplit(':', 1)
        return float(parts[1])
    except (IndexError, ValueError, AttributeError):
        return None


def linear_slope(points):
    """简单最小二乘法线性回归，返回斜率（单位：value/秒）

    Args:
        points: list of (timestamp, value) 元组

    Returns:
        float: 斜率（正值=增长，负值=下降，0=无变化）
        None: 数据点不足（<3 个）
    """
    n = len(points)
    if n < 3:
        return None

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]

    avg_x = sum(xs) / n
    avg_y = sum(ys) / n

    num = sum((x - avg_x) * (y - avg_y) for x, y in zip(xs, ys))
    den = sum((x - avg_x) ** 2 for x in xs)

    if den == 0:
        return 0.0  # 所有 x 相同，无变化趋势
    return num / den


def predict_time_to_threshold(current, threshold, slope):
    """预测多久达到阈值

    Args:
        current: 当前值
        threshold: 目标阈值
        slope: 线性回归斜率（value/秒）

    Returns:
        float: 预计 N 小时后达到阈值
        None: 无法预测（斜率为 0/负/None，或已超阈值）
    """
    if slope is None or slope <= 0:
        return None

    remaining = threshold - current
    if remaining <= 0:
        return 0.0  # 已超阈值

    seconds = remaining / slope
    return seconds / 3600  # 转换为小时

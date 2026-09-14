#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Celery 队列路由与告警等级验证脚本（部署验收 / 回归用例）

用途：
    验证"定时任务/路由任务是否全部落在有消费者的队列"以及
    "告警等级能否写入 alerts 表"。修复后重跑应 exit 0。

用法（脚本需在容器内执行，容器内才有 Django 环境与 redis）：
    docker cp scripts/verify_celery_queues_and_alerts.py tdyw:/tmp/
    docker exec -e PYTHONIOENCODING=utf-8 tdyw python /tmp/verify_celery_queues_and_alerts.py

用例：
    [CASE 1] 枚举所有 worker 实际监听的队列（celery inspect active_queues）
    [CASE 2] 生效路由解析：用 celery 路由器解析 CELERY_BEAT_SCHEDULE 与
             CELERY_TASK_ROUTES 中每个任务的最终投递队列（真实代码路径），
             全部必须落在 CASE 1 的有消费者队列上。
    [CASE 3] 死队列探针（观察项）：向历史问题队列投递幂等探针观察是否被消费。
             注意：修复方式是"把任务改路由到有消费者的队列"而非"新增 worker"，
             因此这些队列保持无消费者是预期状态，本用例仅作拓扑观察。
    [CASE 4] alerts 表 alert_level_valid CHECK 约束：对 error/warning/info/critical
             四档做事务内插入后强制回滚（零残留）。error/warning/info 必须可插入。

退出码：0 = 全部生效路由可达 + 告警等级正常；2 = 检测到问题。
"""
import os
import sys
import time

sys.path.insert(0, '/data/spug/spug_api')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')

import django

django.setup()

import redis
from django.conf import settings
from django.db import IntegrityError, transaction

LEGACY_QUEUES = ['home.announcement', 'default', 'contract_agreement']
PROBE_TASK = 'apps.home.tasks.sync_announcement_status'  # 已注册、幂等、无副作用
POLL_INTERVAL = 5
POLL_TIMES = 4


def get_redis():
    return redis.Redis(
        host='127.0.0.1', port=6379, db=2,
        password=os.environ.get('REDIS_PASSWORD', ''),
    )


def case1_worker_queues(results):
    print('=' * 64)
    print('[CASE 1] worker 实际监听队列（app.control.inspect active_queues）')
    from spug.celery import app
    reply = app.control.inspect(timeout=5).active_queues() or {}
    names = sorted({q['name'] for queues in reply.values() for q in queues})
    if not names:
        raise RuntimeError('没有任何 worker 回复 active_queues，请确认 worker 已启动')
    print('  worker 绑定队列: %s' % names)
    results['bound_queues'] = names


def case2_effective_routes(results):
    print('=' * 64)
    print('[CASE 2] 生效路由解析（celery 路由器真实代码路径）')
    from spug.celery import app
    bound = set(results['bound_queues'])

    def effective_queue(task, options):
        route = app.amqp.router.route(dict(options or {}), task)
        q = route.get('queue')
        return getattr(q, 'name', q) or 'celery'

    results['routes'] = {}
    bad = []
    for name, entry in settings.CELERY_BEAT_SCHEDULE.items():
        q = effective_queue(entry['task'], entry.get('options'))
        ok = q in bound
        results['routes'][name] = q
        if not ok:
            bad.append(name)
        print('  beat  %-46s -> %-20s %s' % (name, q, 'OK' if ok else '<<< 死队列!'))
    for task, cfg in settings.CELERY_TASK_ROUTES.items():
        q = effective_queue(task, cfg)
        ok = q in bound
        results['routes'][task] = q
        if not ok:
            bad.append(task)
        print('  route %-46s -> %-20s %s' % (task, q, 'OK' if ok else '<<< 死队列!'))
    results['route_bad'] = bad


def case3_dead_queue_probe(r, results):
    print('=' * 64)
    print('[CASE 3] 死队列探针（观察项，探针任务=%s）' % PROBE_TASK)
    from spug.celery import app as celery_app

    results['probe'] = {}
    for q in LEGACY_QUEUES:
        llen0 = r.llen(q)
        if llen0 != 0:
            print('  - %-22s 队列已有 %d 条积压（非本次注入），仅观察不注入' % (q, llen0))
            results['probe'][q] = 'HAS_BACKLOG_%d' % llen0
            continue
        res = celery_app.send_task(PROBE_TASK, queue=q)
        consumed = False
        for _ in range(POLL_TIMES):
            time.sleep(POLL_INTERVAL)
            if r.llen(q) == 0:
                consumed = True
                break
        if consumed:
            print('  - %-22s ALIVE  探针 %s 已被 worker 消费' % (q, res.id[:8]))
            results['probe'][q] = 'ALIVE'
        else:
            print('  - %-22s 无消费者（修复后任务已不再路由至此，属预期；死信若出现说明有路由回退）'
                  % q)
            results['probe'][q] = 'NO_CONSUMER'
            if r.llen(q) == 1:
                r.delete(q)
                print('       （测试探针已清理，队列恢复为空）')


def _try_insert_level(level):
    """事务内插入后强制回滚。返回 (能否插入, 错误摘要)。"""

    class _Rollback(Exception):
        pass

    try:
        with transaction.atomic():
            from apps.alert.models import Alert
            Alert.objects.create(
                title='VERIFY-用例回滚', message='case4', level=level, source='verify_script',
            )
            raise _Rollback
        return True, ''
    except _Rollback:
        return True, ''
    except IntegrityError as exc:
        return False, str(exc)[:90]
    except Exception as exc:  # noqa: BLE001 - 验证脚本需要看到任何异常
        return False, '%s: %s' % (type(exc).__name__, str(exc)[:90])


def case4_alert_levels(results):
    print('=' * 64)
    print('[CASE 4] alerts.level CHECK 约束（事务内插入后回滚，零残留）')
    level_results = {}
    for lv in ['error', 'warning', 'info', 'critical']:
        ok, err = _try_insert_level(lv)
        level_results[lv] = ok
        print('  - %-8s %s %s' % (lv, '可插入' if ok else '被拒', err))
    from apps.alert.models import Alert
    residue = Alert._base_manager.filter(title='VERIFY-用例回滚').count()
    print('  残留检查: %d 行' % residue)
    results['alert_levels'] = level_results
    results['residue'] = residue


def main():
    results = {}
    r = get_redis()
    case1_worker_queues(results)
    case2_effective_routes(results)
    case3_dead_queue_probe(r, results)
    case4_alert_levels(results)

    print('=' * 64)
    print('[结论]')
    bugs = []
    if results['route_bad']:
        for name in results['route_bad']:
            bugs.append('任务 %s 的生效路由指向无消费者队列' % name)
    levels = results['alert_levels']
    if not (levels.get('error') and levels.get('warning') and levels.get('info')):
        bugs.append('alerts 表常规告警等级（error/warning/info）存在无法落库的情况')
    if bugs:
        for i, b in enumerate(bugs, 1):
            print('  BUG %d: %s' % (i, b))
        print('  exit=2（检测到问题）')
        sys.exit(2)
    print('  全部生效路由可达（%d 个任务/路由），error/warning/info 均可落库' % len(results['routes']))
    print('  exit=0')
    sys.exit(0)


if __name__ == '__main__':
    main()

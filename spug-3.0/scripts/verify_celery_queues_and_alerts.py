#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Celery 队列路由与告警等级验证脚本（部署验收 / 回归用例）

用途：
    验证 0914 验收中发现的队列路由 / 告警等级问题是否仍然存在。
    修复后重跑本脚本，应全部转为 ALIVE / 可插入（exit code 0）。

用法（脚本需在 tdyw 容器内执行，容器内才有 Django 环境与 redis）：
    docker cp scripts/verify_celery_queues_and_alerts.py tdyw:/tmp/
    docker exec -e PYTHONIOENCODING=utf-8 tdyw python /tmp/verify_celery_queues_and_alerts.py

用例：
    [CASE 1] 枚举所有 worker 实际监听的队列（celery inspect active_queues）
    [CASE 2] 队列投递探针：home.announcement / default / contract_agreement。
             使用已注册且幂等无副作用的任务（公告过期同步）作为探针，
             观察 20s 内是否被消费：ALIVE=有消费者；DEAD=无消费者（死信）。
             队列原本为空且探针未被消费时，测试后清理恢复原状。
    [CASE 3] alerts 表 alert_level_valid CHECK 约束：对 error/warning/info/critical
             四档做事务内插入后强制回滚（零残留），记录各档位能否落库。

退出码：0 = 未检测到问题（全部 ALIVE 且 critical 可落库）；2 = 检测到问题。
"""
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, '/data/spug/spug_api')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'spug.settings')
os.chdir('/data/spug/spug_api')

import django

django.setup()

import redis
from django.db import IntegrityError, transaction

SUSPECT_QUEUES = ['home.announcement', 'default', 'contract_agreement']
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
    print('[CASE 1] worker 实际监听队列（celery inspect active_queues）')
    proc = subprocess.run(
        ['celery', '-A', 'spug', 'inspect', 'active_queues', '--timeout=3'],
        capture_output=True, text=True, timeout=60,
    )
    names = sorted(set(re.findall(r"'name': '([a-z._]+)'", proc.stdout)))
    print('  worker 绑定队列: %s' % names)
    results['bound_queues'] = names
    for q in SUSPECT_QUEUES:
        print('  - %-22s %s' % (q, '有消费者' if q in names else '无消费者(可疑)'))


def case2_queue_probe(r, results):
    print('=' * 64)
    print('[CASE 2] 队列投递探针（探针任务=%s）' % PROBE_TASK)
    from spug.celery import app as celery_app

    results['probe'] = {}
    for q in SUSPECT_QUEUES:
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
            print('  - %-22s DEAD   探针 %s 等 %ds 无人消费（死信）'
                  % (q, res.id[:8], POLL_INTERVAL * POLL_TIMES))
            results['probe'][q] = 'DEAD'
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
                title='VERIFY-用例回滚', message='case3', level=level, source='verify_script',
            )
            raise _Rollback
        return True, ''
    except _Rollback:
        return True, ''
    except IntegrityError as exc:
        return False, str(exc)[:90]
    except Exception as exc:  # noqa: BLE001 - 验证脚本需要看到任何异常
        return False, '%s: %s' % (type(exc).__name__, str(exc)[:90])


def case3_alert_levels(results):
    print('=' * 64)
    print('[CASE 3] alerts.level CHECK 约束（事务内插入后回滚，零残留）')
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
    case2_queue_probe(r, results)
    case3_alert_levels(results)

    print('=' * 64)
    print('[结论]')
    bugs = []
    for q in SUSPECT_QUEUES:
        state = results['probe'].get(q, '?')
        if state.startswith('DEAD') or state.startswith('HAS_BACKLOG'):
            bugs.append('队列 %s 无消费者（任务投递即积压）' % q)
    if results['alert_levels'].get('critical') is False:
        bugs.append("send_alert(level='critical') 被.alerts CHECK 约束拒绝，critical 告警无法落库")
    if bugs:
        for i, b in enumerate(bugs, 1):
            print('  BUG %d: %s' % (i, b))
        print('  exit=2（检测到问题）')
        sys.exit(2)
    print('  全部队列 ALIVE，critical 可落库，未检测到问题')
    print('  exit=0')
    sys.exit(0)


if __name__ == '__main__':
    main()

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License
"""Celery Beat 首次调度时区兼容（django-celery-beat 2.9 + USE_TZ=False 部署口径）。

问题根因
--------
django-celery-beat 2.9 的 ``ModelEntry.__init__`` 在 ``PeriodicTask.last_run_at``
为空（新建任务、任务被停用后重新启用）时，直接用 ``model.date_changed`` 初始化
``last_run_at``：

    if not model.last_run_at:
        model.last_run_at = model.date_changed or self._default_now()

``date_changed`` 是 ``auto_now`` 字段，本项目 ``USE_TZ=False`` 下由 Django 写入
Asia/Shanghai 本地 naive 时间；而 ``ModelEntry._default_now()`` 在
``DJANGO_CELERY_BEAT_TZ_AWARE=False`` 时返回 ``datetime.utcnow()``（UTC naive），
``is_due()`` 中 ``maybe_make_aware()`` 又把所有 naive 时间一律按 UTC 解释。
于是本地 naive 的 ``date_changed`` 被当成 UTC 后，比真实时刻超前 8 小时
（上海墙钟 = UTC + 8h），新任务要等约 8 小时才第一次到期。
interval 类任务（如 flush-run-metrics，300 秒）首跑延迟 8 小时，平台健康页面
在此期间拿不到数据；crontab 类任务同样推迟到"未来 last_run_at 之后的下一次命中"。
开发环境看不到问题，只是因为旧任务早已执行过（last_run_at 已有值）。

修复方式
--------
不替换整个调度器架构、不修改第三方 site-packages，仅通过 django-celery-beat
预留的扩展点：``DatabaseScheduler.Entry`` 是类属性，调度器内部全部通过
``self.Entry(...)`` / ``self.Entry.from_entry(...)`` 构造条目，子类替换即可生效。
``TZCompatModelEntry`` 只在 ``last_run_at`` 为空且 ``DJANGO_CELERY_BEAT_TZ_AWARE
=False``（即 naive 一律按 UTC 解释的模式）时，把 ``date_changed`` 按
``settings.TIME_ZONE``（Asia/Shanghai）本地时间解释、转换为 UTC naive，再交给
父类走原有赋值路径（包括 ``start_time`` 的 30 年回拨分支）。转换后的值与
``_default_now()`` 的口径完全一致，时刻语义（date_changed 所代表的真实瞬间）
保持不变，只是表达方式从本地 naive 换成了 UTC naive。

为什么不影响其他时间
--------------------
- 已有 ``last_run_at`` 的任务：条件不命中，父类原样使用数据库里的值（UTC naive），
  一个字节都不会被改动；
- ``__next__`` / ``save()`` 写回的 ``last_run_at`` 仍由 django-celery-beat 自身的
  ``_default_now()``（UTC naive）产生，本模块不参与任何运行时写回；
- 全局 USE_TZ / TIME_ZONE / CELERY_TIMEZONE / CELERY_ENABLE_UTC 均不变，
  其他业务模型的时间字段与本模块无关。

first run 之后 ``last_run_at`` 落库为 UTC naive，兼容分支自然不再触发；
该修复对 last_run_at 为空的存量任务同样生效（调度器每次全量重建条目时转换），
也可用 ``repair_periodic_task_last_run`` 管理命令显式落库（幂等、可审计）。
"""
from datetime import timezone as dt_timezone

from django.conf import settings
from django.utils import timezone
from django_celery_beat.schedulers import DatabaseScheduler, ModelEntry


def local_naive_to_utc_naive(value):
    """把数据库存储的 TIME_ZONE 本地 naive datetime 转换为 UTC naive。

    - naive 输入按 ``settings.TIME_ZONE`` 解释（与 Django 在 USE_TZ=False 下
      写入 DateTimeField 的口径一致）；
    - aware 输入先归一化到 TIME_ZONE 墙钟再转换，保证同一时刻语义；
    - 输出丢弃 tzinfo，供 ``maybe_make_aware()``（naive 按 UTC 解释）消费。
    转换只改变时间的表达方式，不改变其代表的真实瞬间。
    """
    if value is None:
        return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value)
    else:
        value = timezone.localtime(value)
    return value.astimezone(dt_timezone.utc).replace(tzinfo=None)


class TZCompatModelEntry(ModelEntry):
    """首次调度初始化时把 date_changed 从本地 naive 转为 UTC naive。

    仅在 last_run_at 为空时介入；DJANGO_CELERY_BEAT_TZ_AWARE=True 的 aware
    模式下 maybe_make_aware 不会把 naive 误判为 UTC，无需兼容，保持原样。
    """

    def __init__(self, model, app=None):
        if (
            not model.last_run_at
            and model.date_changed is not None
            and not getattr(settings, 'DJANGO_CELERY_BEAT_TZ_AWARE', True)
        ):
            model.last_run_at = local_naive_to_utc_naive(model.date_changed)
        super().__init__(model, app)


class TZCompatDatabaseScheduler(DatabaseScheduler):
    """仅把 Entry 换成时区兼容实现，其余调度逻辑与官方 DatabaseScheduler 一致。"""

    Entry = TZCompatModelEntry

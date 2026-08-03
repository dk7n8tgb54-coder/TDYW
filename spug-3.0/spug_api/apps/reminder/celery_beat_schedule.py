# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
"""提醒事项模块 Celery Beat 定时任务配置

当前提醒事项采用懒创建模式（pending 接口实时检查 + 创建），
无需 Celery 定时任务。此文件保留以备未来需要定时推送场景。
"""
REMINDER_BEAT_SCHEDULE = {}

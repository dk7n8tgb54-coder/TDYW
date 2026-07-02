# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
升级状态变更日志模型

记录升级表单过程中的关键里程碑节点（升级启动/备份完成/灰度发布完成/回退/升级完成等），
用于构建升级经历的时间线。每个动作记录代表"该阶段已完成/该里程碑已达成"。
蓝色右三角（current）由系统根据最后一个有效完成节点自动推算，不需要用户手动记录。
"""
from django.db import models
from libs import ModelMixin
import logging

logger = logging.getLogger(__name__)


# 动作类型常量（12 种，按升级生命周期阶段排列）
# 语义：记录该动作 = 该里程碑已达成（非"开始做"）
ACTION_START = 'start'                # 升级启动
ACTION_BACKUP = 'backup'              # 备份完成
ACTION_GRAY_RELEASE = 'gray_release'  # 灰度发布完成
ACTION_FULL_RELEASE = 'full_release'  # 全量发布完成
ACTION_TEST = 'test'                  # 升级测试完成（历史兼容，新记录不再使用）
ACTION_TEST_PASS = 'test_pass'        # 升级测试通过
ACTION_TEST_FAIL = 'test_fail'        # 升级测试失败
ACTION_ROLLBACK = 'rollback'          # 回退
ACTION_PAUSE = 'pause'                # 暂停
ACTION_RESUME = 'resume'              # 继续
ACTION_OBSERVE = 'observe'            # 观察完成
ACTION_COMPLETE = 'complete'          # 升级完成

ACTION_CHOICES = [
    (ACTION_START, '升级启动'),
    (ACTION_BACKUP, '备份完成'),
    (ACTION_GRAY_RELEASE, '灰度发布完成'),
    (ACTION_FULL_RELEASE, '全量发布完成'),
    (ACTION_TEST, '升级测试完成'),
    (ACTION_TEST_PASS, '升级测试通过'),
    (ACTION_TEST_FAIL, '升级测试失败'),
    (ACTION_ROLLBACK, '回退'),
    (ACTION_PAUSE, '暂停'),
    (ACTION_RESUME, '继续'),
    (ACTION_OBSERVE, '观察完成'),
    (ACTION_COMPLETE, '升级完成'),
]

# 动作 → 图标颜色（前端时间线展示用）
ACTION_COLOR_MAP = {
    ACTION_START: 'blue',
    ACTION_BACKUP: 'default',
    ACTION_GRAY_RELEASE: 'cyan',
    ACTION_FULL_RELEASE: 'geekblue',
    ACTION_TEST: 'orange',
    ACTION_TEST_PASS: 'green',
    ACTION_TEST_FAIL: 'red',
    ACTION_ROLLBACK: 'red',
    ACTION_PAUSE: 'gray',
    ACTION_RESUME: 'blue',
    ACTION_OBSERVE: 'purple',
    ACTION_COMPLETE: 'green',
}

# 会联动主表 status 的动作
# 回退 → 主表 status 变为"已回退"
# 完成 → 主表 status 变为"已完成"
ACTION_TO_MAIN_STATUS = {
    ACTION_ROLLBACK: '已回退',
    ACTION_COMPLETE: '已完成',
}


class UpgradeStatusLog(models.Model, ModelMixin):
    """升级状态变更日志 - 记录升级过程中的关键动作节点"""
    tenant_id = models.CharField(max_length=50, default='', db_index=True, help_text='租户标识')
    upgrade_id = models.IntegerField(verbose_name='关联升级表单ID')

    action = models.CharField(
        max_length=20, choices=ACTION_CHOICES,
        verbose_name='动作类型'
    )
    from_status = models.CharField(max_length=20, default='', blank=True, verbose_name='变更前主表状态')
    to_status = models.CharField(max_length=20, default='', blank=True, verbose_name='变更后主表状态')

    operator_id = models.IntegerField(default=0, verbose_name='操作人ID')
    operator_name = models.CharField(max_length=100, default='', blank=True, verbose_name='操作人姓名')
    remark = models.TextField(default='', blank=True, verbose_name='备注')

    # 回退目标动作（仅 action=rollback 时使用，记录回退到哪个主线节点）
    target_action = models.CharField(
        max_length=20, default='', blank=True, verbose_name='回退目标动作'
    )
    # 同一 upgrade_id 内递增的稳定序号（用于排序，不依赖 created_at 字符串比较）
    event_seq = models.IntegerField(default=0, verbose_name='事件序号')
    # 是否为补录/跳步（允许跳过前置节点直接记录后置节点，需配合 remark 说明原因）
    is_override = models.BooleanField(default=False, verbose_name='是否补录/跳步')

    created_at = models.CharField(max_length=20, verbose_name='操作时间')

    class Meta:
        db_table = 'tdyw_upgrade_status_logs'
        verbose_name = '升级状态日志'
        verbose_name_plural = '升级状态日志'
        ordering = ('-event_seq', '-id')  # 按事件序号倒序，最新在前
        indexes = [
            models.Index(fields=['upgrade_id']),
            models.Index(fields=['tenant_id', 'upgrade_id']),
            models.Index(fields=['upgrade_id', 'event_seq'], name='tdyw_upgrad_upgrade_seq_idx'),
            # 状态时间线：tenant_id + upgrade_id + event_seq + id（多租户前缀覆盖排序与下一序号聚合）
            models.Index(fields=['tenant_id', 'upgrade_id', 'event_seq', 'id'], name='upg_log_tenant_seq_idx'),
        ]

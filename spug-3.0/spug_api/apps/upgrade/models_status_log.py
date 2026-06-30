# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
升级状态变更日志模型

记录升级表单过程中的关键动作节点（开始升级/灰度发布/测试/回退/完成等），
用于构建升级经历的时间线。每个动作是独立原子记录，系统不强制动作先后顺序，
用户按实际发生顺序逐条添加，靠时间顺序 + 备注还原完整过程。
"""
from django.db import models
from libs import ModelMixin
import logging

logger = logging.getLogger(__name__)


# 动作类型常量（12 种，按升级生命周期阶段排列）
ACTION_START = 'start'                # 开始升级
ACTION_BACKUP = 'backup'              # 备份
ACTION_GRAY_RELEASE = 'gray_release'  # 灰度发布（备用系统/部分环境试运行）
ACTION_FULL_RELEASE = 'full_release'  # 全量发布（推主系统）
ACTION_TEST = 'test'                  # 升级测试（可多次）
ACTION_TEST_PASS = 'test_pass'        # 测试通过
ACTION_TEST_FAIL = 'test_fail'        # 测试失败
ACTION_ROLLBACK = 'rollback'          # 回退
ACTION_PAUSE = 'pause'                # 暂停
ACTION_RESUME = 'resume'              # 继续
ACTION_OBSERVE = 'observe'            # 上线观察期
ACTION_COMPLETE = 'complete'          # 完成

ACTION_CHOICES = [
    (ACTION_START, '开始升级'),
    (ACTION_BACKUP, '备份'),
    (ACTION_GRAY_RELEASE, '灰度发布'),
    (ACTION_FULL_RELEASE, '全量发布'),
    (ACTION_TEST, '升级测试'),
    (ACTION_TEST_PASS, '测试通过'),
    (ACTION_TEST_FAIL, '测试失败'),
    (ACTION_ROLLBACK, '回退'),
    (ACTION_PAUSE, '暂停'),
    (ACTION_RESUME, '继续'),
    (ACTION_OBSERVE, '上线观察期'),
    (ACTION_COMPLETE, '完成'),
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

    created_at = models.CharField(max_length=20, verbose_name='操作时间')

    class Meta:
        db_table = 'tdyw_upgrade_status_logs'
        verbose_name = '升级状态日志'
        verbose_name_plural = '升级状态日志'
        ordering = ('-created_at', '-id')  # 时间倒序，最新在前
        indexes = [
            models.Index(fields=['upgrade_id']),
            models.Index(fields=['tenant_id', 'upgrade_id']),
        ]

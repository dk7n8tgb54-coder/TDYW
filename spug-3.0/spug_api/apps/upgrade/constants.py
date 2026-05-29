# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""
系统升级模块常量定义
"""


class UpgradeStatus:
    """升级状态枚举"""
    IN_PROGRESS = '处理中'
    COMPLETED = '已完成'

    @classmethod
    def values(cls):
        return [cls.IN_PROGRESS, cls.COMPLETED]

    @classmethod
    def choices(cls):
        return [(v, v) for v in cls.values()]


class UpgradeType:
    """升级类型枚举"""
    FEATURE = '功能升级'
    BUGFIX = 'Bug修复'
    SECURITY = '安全补丁'
    PERFORMANCE = '性能优化'

    @classmethod
    def values(cls):
        return [cls.FEATURE, cls.BUGFIX, cls.SECURITY, cls.PERFORMANCE]

    @classmethod
    def choices(cls):
        return [(v, v) for v in cls.values()]


# 状态颜色映射（前端展示用）
STATUS_COLOR_MAP = {
    UpgradeStatus.IN_PROGRESS: 'processing',
    UpgradeStatus.COMPLETED: 'success',
}

# 附件配置
ATTACHMENT_MAX_SIZE_MB = 10
ATTACHMENT_ALLOWED_TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
ATTACHMENT_UPLOAD_DIR = 'upgrade/attachments'

# 合法状态流转路径
VALID_STATUS_TRANSITIONS = {
    UpgradeStatus.IN_PROGRESS: [UpgradeStatus.COMPLETED],
    UpgradeStatus.COMPLETED: [],
}

# 升级单号前缀
UPGRADE_NO_PREFIX = 'UPG'

# 预设系统列表（下拉选择用，历史数据也会动态合并）
PRESET_SYSTEMS = [
    '运维管理平台',
    '数据库系统',
    '网络设备',
    '安全设备',
    '中间件',
    '监控系统',
    '备份系统',
    '邮件系统',
    'OA系统',
    '其他',
]

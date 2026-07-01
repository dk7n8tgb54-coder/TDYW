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
    ROLLED_BACK = '已回退'

    @classmethod
    def values(cls):
        return [cls.IN_PROGRESS, cls.COMPLETED, cls.ROLLED_BACK]

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
    UpgradeStatus.ROLLED_BACK: 'error',
}

# 附件配置
# 升级场景：升级包/补丁/资料文档，体积可能较大，类型以压缩包/镜像/文档为主
ATTACHMENT_MAX_SIZE_MB = 500
ATTACHMENT_ALLOWED_EXTENSIONS = [
    # 压缩包
    '.zip', '.rar', '.7z', '.tar', '.gz', '.bz2',
    # 安装包/镜像
    '.exe', '.msi', '.deb', '.rpm', '.iso', '.img',
    # 脚本/代码
    '.sh', '.py', '.sql', '.json', '.yaml', '.yml', '.conf',
    # 文档
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt', '.md',
    # 图片
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp',
]
ATTACHMENT_UPLOAD_DIR = 'upgrade/attachments'

# 合法状态流转路径（支持回退后再推进的场景）
# - 处理中 → 已完成 / 已回退
# - 已回退 → 处理中（重新测试/继续）/ 已完成
# - 已完成 → 处理中（发现问题重新处理）/ 已回退
VALID_STATUS_TRANSITIONS = {
    UpgradeStatus.IN_PROGRESS: [UpgradeStatus.COMPLETED, UpgradeStatus.ROLLED_BACK],
    UpgradeStatus.ROLLED_BACK: [UpgradeStatus.IN_PROGRESS, UpgradeStatus.COMPLETED],
    UpgradeStatus.COMPLETED: [UpgradeStatus.IN_PROGRESS, UpgradeStatus.ROLLED_BACK],
}

# 升级单号前缀
UPGRADE_NO_PREFIX = 'UPG'

# 升级执行阶段（有步骤的阶段，用于步骤分组）
# 不含"测试通过/测试失败/回退/暂停/继续/完成"——这些是结果里程碑，无步骤
UPGRADE_PHASES = [
    {'value': 'start', 'label': '开始升级', 'order': 1},
    {'value': 'backup', 'label': '备份', 'order': 2},
    {'value': 'gray_release', 'label': '灰度发布', 'order': 3},
    {'value': 'test', 'label': '升级测试', 'order': 4},
    {'value': 'full_release', 'label': '全量发布', 'order': 5},
    {'value': 'observe', 'label': '上线观察期', 'order': 6},
]

# 结果里程碑（无步骤，只记时间线）
# 与执行阶段共同构成标准流程参考条的完整 8+6 节点
RESULT_MILESTONES = [
    {'value': 'test_pass', 'label': '测试通过'},
    {'value': 'test_fail', 'label': '测试失败'},
    {'value': 'rollback', 'label': '回退'},
    {'value': 'pause', 'label': '暂停'},
    {'value': 'resume', 'label': '继续'},
    {'value': 'complete', 'label': '完成'},
]

# 标准流程完整顺序（执行阶段 + 结果里程碑，用于时间线参考条展示）
# 顺序：开始→备份→灰度→测试→(测试通过/失败分叉)→全量→观察→完成
STANDARD_FLOW_ORDER = [
    'start', 'backup', 'gray_release', 'test',
    'test_pass', 'full_release', 'observe', 'complete',
]

# phase → label 快查（含执行阶段和结果里程碑）
PHASE_LABEL_MAP = {p['value']: p['label'] for p in UPGRADE_PHASES}
PHASE_LABEL_MAP.update({p['value']: p['label'] for p in RESULT_MILESTONES})

# 执行阶段有序列表（用于步骤排序）
PHASE_ORDER = [p['value'] for p in UPGRADE_PHASES]

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

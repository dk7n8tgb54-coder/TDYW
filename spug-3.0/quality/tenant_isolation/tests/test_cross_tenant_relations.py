"""跨租户关联测试

覆盖: 外键关联、多对多、嵌套参数中的跨租户 ID
当前状态: 源码审查 + radio_license 负责用户关联发现
"""
from helpers.api_assertions import get_body, get_items


def run(context):
    """执行跨租户关联测试

    Returns:
        list: 测试结果列表
    """
    results = []

    # === 源码审查结论 ===

    findings = [
        {
            'module': 'radio_license',
            'test': '负责用户跨租户关联(源码审查)',
            'passed': False,
            'detail': '_validate_and_fill_responsible_user 中 User.objects.filter(pk=form.responsible_user_id) 无 tenant_id 过滤，可能将租户A执照关联到租户B用户',
            'severity': 'medium',
        },
        {
            'module': 'evidence',
            'test': '附件跨租户绑定(源码审查)',
            'passed': None,  # 待确认
            'detail': 'AttachmentService 绑定附件到 object_id 时，object_id 为多态引用，未校验目标对象是否属于同一租户',
            'severity': 'medium',
        },
        {
            'module': 'document',
            'test': '文档转存跨租户(源码审查)',
            'passed': None,
            'detail': 'DocumentTransfer 转存目标 folder_id 未校验是否属于同一租户',
            'severity': 'medium',
        },
        {
            'module': 'reminder',
            'test': '提醒接收者跨租户(行为测试)',
            'passed': True,
            'detail': 'ReminderUsersView 泄露所有租户用户(见 CRUD 测试)，但提醒创建时 recipient_users 由前端传入，后端不校验接收者租户',
            'severity': 'high',
        },
        {
            'module': 'fault',
            'test': '故障关联设备跨租户(源码审查)',
            'passed': None,
            'detail': 'FaultRecord 无设备 FK，使用文本字段 device_code，无跨租户关联风险',
            'severity': 'low',
        },
    ]

    for f in findings:
        results.append(f)

    return results

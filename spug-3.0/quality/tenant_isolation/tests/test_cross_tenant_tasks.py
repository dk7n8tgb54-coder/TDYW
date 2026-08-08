"""跨租户 Celery/定时任务隔离测试

覆盖: 合同到期, 执照到期, 公告过期, 提醒, 告警, 文件清理, 审计日志归档
当前状态: 源码审查结论，未执行行为测试
"""


TASK_ISOLATION_FINDINGS = [
    {
        'component': 'radio_license/check_license_expiry',
        'task': '执照到期检查',
        'tenant_context': '参数 user_id',
        'risk': '低',
        'detail': '任务接收 user_id 并按用户租户查询 RadioLicense，apply_tenant_filter 有效',
    },
    {
        'component': 'contract_agreement/check_contract_expiry',
        'task': '合同到期检查',
        'tenant_context': '参数 user_id',
        'risk': '低',
        'detail': '任务接收 user_id 并按用户租户查询 ContractAgreement',
    },
    {
        'component': 'reminder/check_weekly_report_reminders',
        'task': '提醒检查',
        'tenant_context': '无 (遍历所有 enabled 提醒)',
        'risk': '中',
        'detail': '任务遍历所有 enabled=True 的提醒，不按租户过滤。但接收者列表(recipient_users)按用户 ID 隔离',
    },
    {
        'component': 'home/notice_expiry_sync',
        'task': '公告过期同步',
        'tenant_context': '无 (批量处理)',
        'risk': '中',
        'detail': 'Notice.objects.filter 批量处理无 tenant 过滤。但 Notice 已有 TI-002 漏洞(无 apply_tenant_filter)，此任务同样受影响',
    },
    {
        'component': 'document/retry_clean_pending_files',
        'task': '文件清理重试',
        'tenant_context': '无 (按文件 ID 清理)',
        'risk': '低',
        'detail': '按文件 ID 清理 is_pending_clean 记录，不涉及租户过滤。物理文件删除是全局操作',
    },
    {
        'component': 'document/merge_chunks',
        'task': '分片合并',
        'tenant_context': '参数 transfer_id',
        'risk': '低',
        'detail': '按 transfer_id 操作 DocumentTransfer 记录，transfer_id 有 tenant_id 但任务未重新校验',
    },
    {
        'component': 'logs/archive_and_clean',
        'task': '审计日志归档/清理',
        'tenant_context': '无 (按时间清理)',
        'risk': '低',
        'detail': '按时间清理审计日志，不按租户区分。全局清理任务设计合理',
    },
    {
        'component': 'alert/check_disk_and_db',
        'task': '磁盘/数据库监控',
        'tenant_context': '无 (全局监控)',
        'risk': '低',
        'detail': '全局告警不按租户区分。AlertRule/AlertRecord 全局共享',
    },
]


def run(context):
    """执行 Celery 任务跨租户测试

    Returns:
        list: 测试结果列表
    """
    results = []

    for f in TASK_ISOLATION_FINDINGS:
        results.append({
            'module': f['component'],
            'test': f'任务隔离: {f["task"]}',
            'passed': None,  # 待行为测试
            'detail': f'{f["detail"]} (tenant_context: {f["tenant_context"]})',
            'severity': f['risk'].lower(),
        })

    return results

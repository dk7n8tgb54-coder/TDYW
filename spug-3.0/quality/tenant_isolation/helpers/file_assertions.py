"""文件断言辅助 - 附件和文件隔离验证

当前状态：源码审查结论，未执行行为测试。
以下函数为未来文件隔离测试预留的接口。
"""


def assert_file_not_accessible(client, token, file_id, endpoint='/document/file/'):
    """断言其他租户的文件不可访问

    TODO: 当文件模块测试环境就绪后实现
    """
    pass


def assert_attachment_not_bindable(client, token, attachment_id, target_object_id):
    """断言其他租户的附件不可绑定到当前租户对象

    TODO: 当附件模块测试环境就绪后实现
    """
    pass


# === 源码审查结论 ===

FILE_ISOLATION_FINDINGS = [
    {
        'module': 'document',
        'finding': 'Private/Public 双模型架构',
        'status': 'source_reviewed',
        'detail': 'DocumentFolderPrivate/DocumentFilePrivate 和 DocumentFolderPublic/DocumentFilePublic 均有 tenant_id，使用 TenantModelManager。apply_tenant_filter 在视图中被调用。',
        'risk': 'MEDIUM',
        'tested': False,
    },
    {
        'module': 'evidence',
        'finding': '多态附件 EvidenceAttachment 有 tenant_id',
        'status': 'source_reviewed',
        'detail': 'EvidenceAttachment 继承 TenantModelMixin，AttachmentService.list/upload 内部使用 apply_tenant_filter。但 object_id 多态绑定是否校验跨租户未验证。',
        'risk': 'MEDIUM',
        'tested': False,
    },
    {
        'module': 'regulation',
        'finding': '独立 storage.py + RegulationAttachment 无 tenant_id',
        'status': 'source_reviewed',
        'detail': 'RegulationAttachment 不继承 TenantModelMixin，无 tenant_id 字段。所有租户共享同一套规章附件。',
        'risk': 'MEDIUM',
        'tested': False,
    },
    {
        'module': 'document',
        'finding': 'DocumentSystemFolder 全局共享',
        'status': 'source_reviewed',
        'detail': '党建系统文件夹无 tenant_id，全局共享。system_scope_validators 实现 fail-closed 隔离。',
        'risk': 'MEDIUM',
        'tested': False,
    },
    {
        'module': 'kkFileView',
        'finding': '预览回源地址隔离',
        'status': 'source_reviewed',
        'detail': 'KKFILEVIEW_API_URL (浏览器) / KKFILEVIEW_SERVER_URL (容器回源)。preview_token 两套独立实现待收口。',
        'risk': 'LOW',
        'tested': False,
    },
]

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
from django.db import transaction
from django.urls import path, re_path

from . import views, views_authorization, views_draft, views_editor, \
    views_files, views_retention

urlpatterns = [
    # 类别字典
    path('categories/', views.CategoryView.as_view()),
    re_path(r'^categories/(?P<pk>\d+)/$', views.CategoryDetailView.as_view()),

    # 文件生命周期保留策略（只读预检 + 可控幂等执行；config 权限，
    # 未配置保留期限时执行整体拒绝，自动清理不启用）
    path('cleanup/preview/', views_retention.CleanupPreviewView.as_view()),
    path('cleanup/execute/', views_retention.CleanupExecuteView.as_view()),

    # 手册
    path('manuals/', views.ManualListView.as_view()),
    path('manuals/create/', views.ManualCreateView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/$', views.ManualDetailView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/password/$', views.ManualPasswordView.as_view()),
    # 逐本账号授权与所有者管理（2026-10-31 授权模型改造，替代旧
    # roles/ 角色关联配置端点）
    re_path(r'^manuals/(?P<pk>\d+)/authorizations/$',
            views_authorization.ManualAuthorizationsView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/owner-candidates/$',
            views_authorization.OwnerCandidatesView.as_view()),
    # 授权界面账号候选（所有者/制度管理员；全部启用账号最小清单）
    re_path(r'^manuals/(?P<pk>\d+)/account-options/$',
            views_authorization.AccountOptionsView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/owner/$',
            views_authorization.ManualOwnerView.as_view()),

    # 制度文件（多文件；每个请求先校验文件确属当前制度）
    re_path(r'^manuals/(?P<pk>\d+)/files/$', views_files.ManualFileListView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/files/create/$',
            views_files.ManualFileCreateView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/files/(?P<fid>\d+)/rename/$',
            views_files.ManualFileRenameView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/files/(?P<fid>\d+)/move/$',
            views_files.ManualFileMoveView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/files/(?P<fid>\d+)/remove/$',
            views_files.ManualFileRemoveView.as_view()),
    # 文件分工（2026-10-29，替代旧章节分工）：指定/改派/清空文件负责人
    re_path(r'^manuals/(?P<pk>\d+)/files/(?P<fid>\d+)/assignment/$',
            views_files.ManualFileAssignmentView.as_view()),
    # 负责人候选（分工弹窗/新增文件专用最小清单：仅 id+name；页面权限与
    # 分工写路径一致，不开放账号管理清单）
    re_path(r'^manuals/(?P<pk>\d+)/assignment-owners/$',
            views_files.AssignmentOwnerOptionsView.as_view()),
    # 提交编制：记录提交时草稿修订号与时间（交接信息，不新增发布阻断）
    re_path(r'^manuals/(?P<pk>\d+)/files/(?P<fid>\d+)/submit/$',
            views_files.ManualFileSubmitView.as_view()),
    # 开始修订（已发布文件的真实状态动作：开启新一轮修订；工作副本缺失/
    # 损坏/基线不一致时携带 confirm_repair 从生效快照修复）
    re_path(r'^manuals/(?P<pk>\d+)/files/(?P<fid>\d+)/revision/start/$',
            views_files.FileRevisionStartView.as_view()),
    # 批量文件分工（勾选多份文件统一指定/清空负责人+分工说明；
    # 逐文件校验归属，事务内全成功或全失败）
    re_path(r'^manuals/(?P<pk>\d+)/files/batch-assignment/$',
            views_files.ManualFileBatchAssignmentView.as_view()),
    # 按文件回看发布历史（文件变更记录页签；权限=发布域 can_view_published）
    re_path(r'^manuals/(?P<pk>\d+)/files/(?P<fid>\d+)/version-history/$',
            views_draft.FileVersionHistoryView.as_view()),
    # 初始来源聚合清单（"初始来源"页签数据源：一次请求返回全部文件行）
    re_path(r'^manuals/(?P<pk>\d+)/originals-overview/$',
            views_files.OriginalsOverviewView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/files/(?P<fid>\d+)/originals/$',
            views_files.FileOriginalListView.as_view()),
    # 为已有文件更换来源（受控操作：目标文件明确，不改当前草稿）
    re_path(r'^manuals/(?P<pk>\d+)/files/(?P<fid>\d+)/originals/upload/$',
            views_files.FileOriginalUploadView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/files/(?P<fid>\d+)/originals/(?P<oid>\d+)/download/$',
            views_files.FileOriginalDownloadView.as_view()),

    # 文件草稿 / 文件级编辑会话 / 编辑服务契约
    re_path(r'^manuals/(?P<pk>\d+)/files/(?P<fid>\d+)/draft/$',
            views_draft.FileDraftDetailView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/files/(?P<fid>\d+)/draft/create/$',
            views_draft.FileDraftCreateView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/files/(?P<fid>\d+)/draft/session/$',
            views_draft.FileDraftSessionView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/files/(?P<fid>\d+)/draft/save/$',
            views_draft.FileDraftSaveView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/files/(?P<fid>\d+)/draft/download/$',
            views_draft.FileDraftDownloadView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/files/(?P<fid>\d+)/draft/preview-url/$',
            views_draft.FileDraftPreviewUrlView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/files/(?P<fid>\d+)/draft/editor-config/$',
            views_draft.FileEditorConfigView.as_view()),
    # 保存并结束编辑的落盘确认起点：请求 DS Command Service forcesave；
    # 视图内有对 DS 的出站 HTTP 调用，排除 ATOMIC_REQUESTS 事务
    re_path(r'^manuals/(?P<pk>\d+)/files/(?P<fid>\d+)/draft/forcesave/$',
            views_editor._non_atomic_forcesave),

    # 原稿（制度级列表/上传在过渡期委托唯一启用文件；下载按原稿定位）
    re_path(r'^manuals/(?P<pk>\d+)/originals/$', views.OriginalListView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/originals/upload/$', views.OriginalUploadView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/originals/(?P<oid>\d+)/download/$',
            views.OriginalDownloadView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/originals/(?P<oid>\d+)/preview-url/$',
            views_draft.OriginalPreviewUrlView.as_view()),

    # 过渡期旧单文件草稿路由（委托唯一启用文件，多文件制度明确拒绝）
    re_path(r'^manuals/(?P<pk>\d+)/draft/$', views_draft.DraftDetailView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/draft/create/$', views_draft.DraftCreateView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/draft/session/$', views_draft.DraftSessionView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/draft/save/$', views_draft.DraftSaveView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/draft/download/$',
            views_draft.DraftDownloadView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/draft/preview-url/$',
            views_draft.DraftPreviewUrlView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/draft/editor-config/$',
            views_draft.EditorConfigView.as_view()),
    # 整套回退（以版本快照清单重建待发布草稿集合）
    re_path(r'^manuals/(?P<pk>\d+)/draft/from-version/$',
            views_draft.DraftFromVersionView.as_view()),
    # 草稿状态总览（编制/发布角色只读；哈希比对 草稿 vs 生效版本 + 摘要）
    re_path(r'^manuals/(?P<pk>\d+)/draft-status/$',
            views_draft.DraftStatusView.as_view()),

    # 发布与版本（发布=整套快照，任一步失败旧生效版保持完整）
    # 发布先做版本快照物理复制（长阻塞外部调用），排除 ATOMIC_REQUESTS 事务
    re_path(r'^manuals/(?P<pk>\d+)/publish/$',
            transaction.non_atomic_requests(views_draft.PublishView.as_view())),
    re_path(r'^manuals/(?P<pk>\d+)/publish-preview/$',
            views_draft.PublishPreviewView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/versions/$', views_draft.VersionListView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/versions/(?P<vid>\d+)/files/$',
            views_draft.VersionFilesListView.as_view()),
    # 版本长期保留标记（保留策略保护，不成为清理候选）
    re_path(r'^manuals/(?P<pk>\d+)/versions/(?P<vid>\d+)/protect/$',
            views_retention.VersionProtectView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/versions/(?P<vid>\d+)/files/(?P<sfid>\d+)/download/$',
            views_draft.VersionFileDownloadView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/versions/(?P<vid>\d+)/files/(?P<sfid>\d+)/preview-url/$',
            views_draft.VersionFilePreviewUrlView.as_view()),
    # 旧单文件版本下载/预览：委托唯一快照，多文件版本明确拒绝
    re_path(r'^manuals/(?P<pk>\d+)/versions/(?P<vid>\d+)/download/$',
            views_draft.VersionDownloadView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/versions/(?P<vid>\d+)/preview-url/$',
            views_draft.VersionPreviewUrlView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/deprecate/$', views_draft.DeprecateView.as_view()),

    # 章节分工（遗留只读：GET 供人工核对；写入口返回明确业务错误）
    re_path(r'^manuals/(?P<pk>\d+)/chapters/$', views.ChapterListView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/chapters/create/$', views.ChapterListView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/chapters/(?P<cid>\d+)/$', views.ChapterDetailView.as_view()),
    re_path(r'^manuals/(?P<pk>\d+)/chapters/(?P<cid>\d+)/progress/$',
            views.ChapterProgressView.as_view()),

    # 操作记录
    re_path(r'^manuals/(?P<pk>\d+)/operation-logs/$', views.OperationLogListView.as_view()),

    # ONLYOFFICE 文档服务通道（AUTHENTICATION_EXCLUDES 豁免认证，
    # 视图内以 editor_token / 回调 JWT 自认证；URL 与 document.key 中的
    # 文件 ID 交叉核对，注册在通用 preview-file 路由之前）
    re_path(r'^manuals/(?P<pk>\d+)/files/(?P<fid>\d+)/attachments/oo-editor-file/$',
            views_draft.OoEditorFileView.as_view()),
    # 回调先从 DS 下载文件（长阻塞外部调用），排除 ATOMIC_REQUESTS 事务
    re_path(r'^manuals/(?P<pk>\d+)/files/(?P<fid>\d+)/attachments/oo-editor-callback/$',
            transaction.non_atomic_requests(
                views_draft.OoEditorCallbackView.as_view())),
    # preview-file 文件流：kkFileView 回源与浏览器原生预览共用
    re_path(r'^manuals/(?P<pk>\d+)/attachments/(?P<key>[a-z]+-\d+)/preview-file/$',
            views_draft.ManualFilePreviewFileView.as_view()),
]

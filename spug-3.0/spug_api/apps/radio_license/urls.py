# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.db import transaction
from django.urls import re_path

from apps.radio_license.views import *
from apps.radio_license.approval_views import *  # 批复相关视图（从 views.py 拆分）


def _na(view):
    """动作视图装配：关闭请求级原子事务。

    执照并发新增/编辑时审计序列行锁与业务行锁可能死锁（MariaDB 1213），
    需要 views._run_atomic_with_deadlock_retry 的显式事务 + 死锁重试，
    重试必须发生在请求级事务之外（同 equipment_lifecycle/urls.py 先例）。
    """
    return transaction.non_atomic_requests(view)


urlpatterns = [
    # ===== 台站频率批复（固定路径在前，数字主键在后）=====
    # 无个人主动提醒：popup/ack/责任人候选接口已于 2026-09 第一轮改造移除；
    # 菜单红点为全局只读统计（2026-09 第二轮恢复）
    re_path(r'^approvals/badge/$', StationFrequencyApprovalBadgeView.as_view()),
    re_path(r'^approvals/$', StationFrequencyApprovalView.as_view()),

    re_path(r'^approvals/attachments/(?P<pk>\d+)/download/$', ApprovalAttachmentDownloadView.as_view()),
    re_path(r'^approvals/attachments/(?P<pk>\d+)/preview-url/$', ApprovalAttachmentPreviewUrlView.as_view()),
    re_path(r'^approvals/attachments/(?P<pk>\d+)/preview-file/$', ApprovalAttachmentPreviewFileView.as_view()),
    re_path(r'^approvals/attachments/$', ApprovalAttachmentDeleteView.as_view()),

    re_path(r'^approvals/(?P<pk>\d+)/attachments/$', ApprovalAttachmentListView.as_view()),
    re_path(r'^approvals/(?P<pk>\d+)/$', StationFrequencyApprovalDetailView.as_view()),

    # ===== 无线电台执照 =====
    re_path(r'^$', _na(RadioLicenseView.as_view())),
    re_path(r'(?P<pk>\d+)/$', RadioLicenseDetailView.as_view()),
    re_path(r'(?P<pk>\d+)/attachments/$', AttachmentListView.as_view()),
    re_path(r'attachments/(?P<pk>\d+)/download/$', AttachmentDownloadView.as_view()),
    re_path(r'attachments/(?P<pk>\d+)/preview-url/$', AttachmentPreviewUrlView.as_view()),
    re_path(r'attachments/(?P<pk>\d+)/preview-file/$', AttachmentPreviewFileView.as_view()),
    re_path(r'attachments/$', AttachmentDeleteView.as_view()),
    re_path(r'reminders/popup/$', ReminderPopupView.as_view()),
    re_path(r'reminders/ack/$', ReminderAckView.as_view()),
    re_path(r'badge/$', RadioLicenseBadgeView.as_view()),
    re_path(r'responsible-users/$', ResponsibleUserListView.as_view()),
    re_path(r'evidence/package/$', RadioLicenseEvidencePackageView.as_view()),
]

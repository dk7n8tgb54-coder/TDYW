# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Released under the AGPL-3.0 License.
from django.urls import re_path

from apps.coop_task.views import *

urlpatterns = [
    re_path(r'^departments/$', DepartmentListView.as_view()),
    re_path(r'^badge/$', BadgeView.as_view()),
    re_path(r'^items/(?P<pk>\d+)/templates/$', ItemTemplateView.as_view()),

    # ===== 发起方：任务 =====
    re_path(r'^tasks/$', TaskView.as_view()),
    re_path(r'^tasks/(?P<pk>\d+)/$', TaskDetailView.as_view()),
    re_path(r'^tasks/(?P<pk>\d+)/void/$', TaskVoidView.as_view()),
    re_path(r'^tasks/(?P<pk>\d+)/urge/$', TaskUrgeView.as_view()),

    # ===== 交付方：收件箱 =====
    re_path(r'^inbox/$', InboxView.as_view()),
    re_path(r'^inbox/(?P<pk>\d+)/$', InboxDetailView.as_view()),

    # ===== 交付明细动作 =====
    re_path(r'^deliveries/(?P<pk>\d+)/submit/$', DeliverySubmitView.as_view()),
    re_path(r'^deliveries/(?P<pk>\d+)/accept/$', DeliveryAcceptView.as_view()),
    re_path(r'^deliveries/(?P<pk>\d+)/reject/$', DeliveryRejectView.as_view()),
    re_path(r'^deliveries/(?P<pk>\d+)/attachments/$', DeliveryAttachmentView.as_view()),

    # ===== 附件（固定路径在前）=====
    re_path(r'^attachments/(?P<pk>\d+)/download/$', AttachmentDownloadView.as_view()),
    re_path(r'^attachments/(?P<pk>\d+)/preview-url/$', AttachmentPreviewUrlView.as_view()),
    re_path(r'^attachments/(?P<pk>\d+)/preview-file/$', AttachmentPreviewFileView.as_view()),
    re_path(r'^attachments/$', AttachmentDeleteView.as_view()),
]

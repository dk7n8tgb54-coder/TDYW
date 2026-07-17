# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""账号签名 - URL 路由

管理接口挂在账号管理域下（/api/account/user/<user_id>/signature/...），
便于从账号列表直接操作；普通用户与预览接口挂在 /api/signature/ 下。
"""
from django.urls import re_path

from .views import (
    SignatureManageView,
    SignatureStatusView,
    SignatureHistoryView,
    MySignatureView,
    SignaturePreviewView,
)


# 管理接口（由 apps.account.urls include）
admin_urlpatterns = [
    re_path(r'^user/(?P<user_id>\d+)/signature/$', SignatureManageView.as_view()),
    re_path(r'^user/(?P<user_id>\d+)/signature/status/$', SignatureStatusView.as_view()),
    re_path(r'^user/(?P<user_id>\d+)/signature/history/$', SignatureHistoryView.as_view()),
]

# 普通用户与预览接口（由 spug.urls include）
urlpatterns = [
    re_path(r'^mine/$', MySignatureView.as_view()),
    re_path(r'^preview/(?P<attachment_id>\d+)/$', SignaturePreviewView.as_view()),
]

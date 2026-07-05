# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.urls import re_path

from apps.account.views import *
from apps.account.history import *

urlpatterns = [
    re_path(r'^login/$', login),
    re_path(r'^logout/$', logout),
    re_path(r'^user/$', UserView.as_view()),
    re_path(r'^user/tenant_choices/$', UserView.get_tenant_choices),
    re_path(r'^user/restore/$', UserView.restore_user),
    re_path(r'^role/$', RoleView.as_view()),
    re_path(r'^role/assignable/$', AssignableRoleView.as_view()),
    re_path(r'^tenant/$', TenantView.as_view()),
    re_path(r'^self/$', SelfView.as_view()),
    re_path(r'^login/history/$', HistoryView.as_view())
]

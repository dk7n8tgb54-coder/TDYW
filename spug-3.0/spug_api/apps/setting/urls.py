# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.urls import re_path
from apps.setting.views import *
from apps.setting.user import UserSettingView

urlpatterns = [
    re_path(r'^$', SettingView.as_view()),
    re_path(r'^user/$', UserSettingView.as_view()),
    re_path(r'^email_test/$', email_test),
    re_path(r'^mfa/$', MFAView.as_view()),
    re_path(r'^about/$', get_about),
]

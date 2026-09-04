# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
from django.urls import re_path

from apps.equipment_lifecycle.views import (
    DeviceView, DeviceLocationChangeView, DeviceLocationHistoryView,
    SystemView, SystemDetailView, RelationView, RelationExitView,
)

urlpatterns = [
    # 第 1 步：设备档案只读查看
    re_path(r'devices/$', DeviceView.as_view()),
    # 第 3 步：设备位置变更（独立接口，与普通编辑区分）+ 位置历史查询
    re_path(r'devices/location-change/$', DeviceLocationChangeView.as_view()),
    re_path(r'devices/location-history/$', DeviceLocationHistoryView.as_view()),
    # 第 2 步：系统主数据 + 系统—设备关系
    re_path(r'systems/$', SystemView.as_view()),
    re_path(r'systems/detail/$', SystemDetailView.as_view()),
    re_path(r'system-relations/$', RelationView.as_view()),
    re_path(r'system-relations/exit/$', RelationExitView.as_view()),
]

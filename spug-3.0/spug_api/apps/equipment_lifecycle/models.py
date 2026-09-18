# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""设备全生命周期应用外壳。

步骤一（旧结构清理）已删除原设备档案、位置历史、系统主数据和系统—设备关系
模型及其表（tdyw_el_device、tdyw_el_device_location、tdyw_el_system、
tdyw_el_system_device_relation），见 migrations/0005。
本文件保留作为应用外壳，供后续按《设备全生命周期管理总体方案》重建新模型。
"""

# Copyright: (c) OpenSpug Organization. https://github.com/openspug/spug
# Copyright: (c) <spug.dev@gmail.com>
# Released under the AGPL-3.0 License.
"""值班日志（duty）模块已下线（2026-10-11）。

DutyRecord 模型及全部业务代码已移除，表结构由本 app 的删除迁移落库；
"部门值班日志"（apps.department_duty_log）为独立模块，不受影响。
app 暂保留在 INSTALLED_APPS 中以保证历史迁移链可用（后续发布再摘除 app 壳）。
"""

/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
export default [{
  key: 'dashboard',
  label: 'Dashboard',
  pages: [{
    key: 'dashboard',
    label: 'Dashboard',
    perms: [
      {key: 'view', label: '查看Dashboard'}
    ]
  }]
}, {
  key: 'document',
  label: '资料库',
  pages: [{
    key: 'document',
    label: '资料管理',
    perms: [
      {key: 'view', label: '查看资料'},
      {key: 'upload', label: '上传文件'},
      {key: 'download', label: '下载文件'},
      {key: 'delete', label: '删除文件'},
      {key: 'create_folder', label: '新建文件夹'},
      {key: 'copy', label: '复制文件'},
      {key: 'move', label: '移动文件'},
      {key: 'rename', label: '重命名文件'},
    ]
  }, {
    key: 'recycle-bin',
    label: '回收站',
    perms: [
      {key: 'view', label: '查看回收站'},
      {key: 'restore', label: '恢复文件'},
      {key: 'permanent_delete', label: '彻底删除'},
    ]
  }]
}, {
  key: 'runlog',
  label: '运行日志',
  pages: [{
    key: 'runlog',
    label: '运行日志',
    perms: [
      {key: 'view', label: '查看运行日志'},
      {key: 'add', label: '新建运行日志'},
      {key: 'edit', label: '编辑运行日志'},
      {key: 'del', label: '删除运行日志'},
      {key: 'update_view', label: '查看动态'},
      {key: 'update_add', label: '添加动态'},
      {key: 'update_edit', label: '编辑动态'},
      {key: 'update_del', label: '删除动态'},
    ]
  }]
}, {
  key: 'device',
  label: '设备管理',
  pages: [{
    key: 'device_resume',
    label: '设备履历',
    perms: [
      {key: 'view', label: '查看设备档案'},
      {key: 'add', label: '新增设备档案'},
      {key: 'edit', label: '编辑设备档案'},
      {key: 'delete', label: '删除设备档案'},
      {key: 'history_view', label: '查看时间线事件'},
      {key: 'history_add', label: '新增时间线事件'},
      {key: 'history_edit', label: '编辑时间线事件'},
      {key: 'history_delete', label: '删除时间线事件'},
    ]
  }, {
    key: 'device_history',
    label: '查看履历',
    perms: [
      {key: 'view', label: '查看履历'},
    ]
  }]
}, {
  key: 'interference',
  label: '干扰管理',
  pages: [{
    key: 'interference',
    label: '干扰记录',
    perms: [
      {key: 'view', label: '查看干扰记录'},
      {key: 'add', label: '新建干扰记录'},
      {key: 'edit', label: '编辑干扰记录'},
      {key: 'del', label: '删除干扰记录'},
    ]
  }, {
    key: 'statistics',
    label: '干扰统计',
    perms: [
      {key: 'view', label: '查看干扰统计'},
    ]
  }]
  }, {
    key: 'upgrade',
    label: '系统升级管理',
    pages: [{
      key: 'upgrade',
      label: '升级表单',
      perms: [
        {key: 'view', label: '查看升级表单'},
        {key: 'add', label: '新建升级表单'},
        {key: 'edit', label: '编辑升级表单'},
        {key: 'del', label: '删除升级表单'},
        {key: 'update_add', label: '添加动态记录'},
        {key: 'update_edit', label: '编辑动态记录'},
        {key: 'update_del', label: '删除动态记录'},
        {key: 'step_del', label: '删除步骤'},
        {key: 'step_reset', label: '重置步骤'},
      ]
    }, {
    key: 'statistics',
    label: '统计报表',
    perms: [
      {key: 'view', label: '查看统计报表'},
    ]
  }]
}, {
  key: 'duty',
  label: '值班日志',
  pages: [{
    key: 'duty',
    label: '值班日志',
    perms: [
      {key: 'view', label: '查看值班日志'},
      {key: 'add', label: '新建值班日志'},
      {key: 'edit', label: '编辑值班日志'},
      {key: 'del', label: '删除值班日志'},
    ]
  }]
}, {
  key: 'schedule',
  label: '排班管理',
  pages: [{
    key: 'schedule',
    label: '排班日历',
    perms: [
      {key: 'view', label: '查看排班'},
      {key: 'add', label: '新建排班'},
      {key: 'edit', label: '编辑排班'},
      {key: 'del', label: '删除排班'},
      {key: 'auto_schedule', label: '自动排班'},
    ]
  }, {
    key: 'staff',
    label: '值班人员管理',
    perms: [
      {key: 'view', label: '查看值班人员'},
      {key: 'add', label: '新建值班人员'},
      {key: 'edit', label: '编辑值班人员'},
      {key: 'del', label: '删除值班人员'},
    ]
  }, {
    key: 'shift',
    label: '班次管理',
    perms: [
      {key: 'view', label: '查看班次'},
      {key: 'add', label: '新建班次'},
      {key: 'edit', label: '编辑班次'},
      {key: 'del', label: '删除班次'},
    ]
  }, {
    key: 'swap',
    label: '换班管理',
    perms: [
      {key: 'view', label: '查看换班记录'},
      {key: 'add', label: '申请换班'},
      {key: 'edit', label: '编辑换班'},
      {key: 'del', label: '删除换班'},
      {key: 'cancel', label: '撤销换班'},
    ]
  }, {
    key: 'substitute',
    label: '替班管理',
    perms: [
      {key: 'view', label: '查看替班记录'},
      {key: 'add', label: '申请替班'},
      {key: 'edit', label: '编辑替班'},
      {key: 'del', label: '删除替班'},
      {key: 'cancel', label: '撤销替班'},
    ]
  }]
}, {
  key: 'checksheet',
  label: '部门值班日检查单',
  pages: [{
    key: 'checksheet',
    label: '部门值班日检查单',
    perms: [
      {key: 'view', label: '查看部门值班日检查单'},
      {key: 'edit', label: '编辑部门值班日检查单'},
      {key: 'template_view', label: '查看检查表模板'},
      {key: 'template_add', label: '新增检查表模板'},
      {key: 'template_edit', label: '编辑检查表模板'},
      {key: 'template_del', label: '删除检查表模板'},
    ]
  }]
}, {
  key: 'system',
  label: '系统设置',
  pages: [{
    key: 'account',
    label: '用户管理',
    perms: [
      {key: 'view', label: '查看用户'},
      {key: 'add', label: '新建用户'},
      {key: 'edit', label: '编辑用户'},
      {key: 'del', label: '删除用户'},
    ]
  }, {
    key: 'audit',
    label: '操作审计',
    perms: [
      {key: 'view', label: '查看操作审计'},
    ]
  }]
}, {
  key: 'fault',
  label: '故障管理',
  pages: [{
    key: 'faultrecord',
    label: '故障处置记录',
    perms: [
      {key: 'view', label: '查看故障处置记录'},
      {key: 'add', label: '新建故障处置记录'},
      {key: 'edit', label: '编辑故障处置记录'},
      {key: 'del', label: '删除故障处置记录'},
    ]
  }, {
    key: 'faultpart',
    label: '故障件管理',
    perms: [
      {key: 'view', label: '查看故障件'},
      {key: 'add', label: '新建故障件'},
      {key: 'edit', label: '编辑故障件'},
      {key: 'del', label: '删除故障件'},
    ]
  }]
}]


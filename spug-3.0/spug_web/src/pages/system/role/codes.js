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
    label: '文档管理',
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
    key: 'industry_rule',
    label: '行业规章',
    perms: [
      {key: 'view', label: '查看行业规章'},
      {key: 'upload', label: '上传规章文件'},
      {key: 'download', label: '下载规章文件'},
      {key: 'delete', label: '删除规章文件'},
      {key: 'create_folder', label: '新建规章目录'},
      {key: 'copy', label: '复制规章文件'},
      {key: 'move', label: '移动规章文件'},
      {key: 'rename', label: '重命名规章文件'},
    ]
  }]
}, {
  key: 'runlog',
  label: '跨日事项跟踪',
  pages: [{
    key: 'runlog',
    label: '跨日事项跟踪',
    perms: [
      {key: 'view', label: '查看跨日事项跟踪'},
      {key: 'add', label: '新建跨日事项'},
      {key: 'edit', label: '编辑跨日事项'},
      {key: 'del', label: '删除跨日事项'},
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
  }, {
    key: 'tenant',
    label: '租户管理',
    perms: [
      {key: 'view', label: '查看租户'},
      {key: 'add', label: '新建租户'},
      {key: 'edit', label: '编辑租户'},
      {key: 'del', label: '删除租户'},
    ]
  }]
}, {
  key: 'radio_license',
  label: '无线电台执照',
  pages: [{
    key: 'license',
    label: '执照管理',
    perms: [
      {key: 'view', label: '查看执照'},
      {key: 'add', label: '新增执照'},
      {key: 'edit', label: '编辑执照'},
      {key: 'del', label: '删除执照'},
      {key: 'export', label: '导出清单'},
    ]
  }, {
    key: 'attachment',
    label: '附件管理',
    perms: [
      {key: 'upload', label: '上传附件'},
      {key: 'download', label: '下载附件'},
      {key: 'delete', label: '删除附件'},
    ]
  }]
}, {
  key: 'contract_agreement',
  label: '合同协议',
  pages: [{
    key: 'agreement',
    label: '合同管理',
    perms: [
      {key: 'view', label: '查看合同协议'},
      {key: 'add', label: '新增合同协议'},
      {key: 'edit', label: '编辑合同协议'},
      {key: 'del', label: '删除合同协议'},
    ]
  }, {
    key: 'attachment',
    label: '附件管理',
    perms: [
      {key: 'upload', label: '上传附件'},
      {key: 'download', label: '下载附件'},
      {key: 'delete', label: '删除附件'},
    ]
  }, {
    key: 'reminder',
    label: '到期提醒',
    perms: [
      {key: 'handle', label: '确认处理提醒'},
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


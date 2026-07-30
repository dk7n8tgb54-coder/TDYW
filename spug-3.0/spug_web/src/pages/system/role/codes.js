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
    key: 'party_building_document',
    label: '党建工作',
    perms: [
      {key: 'view', label: '查看党建工作'},
      {key: 'upload', label: '上传党建工作文件'},
      {key: 'download', label: '下载党建工作文件'},
      {key: 'delete', label: '删除党建工作文件'},
      {key: 'create_folder', label: '新建党建工作目录'},
      {key: 'copy', label: '复制党建工作文件'},
      {key: 'move', label: '移动党建工作文件'},
      {key: 'rename', label: '重命名党建工作文件'},
    ]
  }, {
    key: 'regulation',
    label: '规章管理',
    perms: [
      {key: 'view',            label: '查看规章'},
      {key: 'add',             label: '新建规章'},
      {key: 'edit',            label: '编辑规章'},
      {key: 'delete',          label: '删除规章'},
      {key: 'upload',          label: '上传附件'},
      {key: 'download',        label: '下载规章文件'},
      {key: 'category_manage', label: '管理分类树'},
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
  key: 'department_duty_log',
  label: '部门值班日志',
  pages: [{
    key: 'department_duty_log',
    label: '部门值班日志',
    perms: [
      {key: 'view', label: '查看部门值班日志'},
      {key: 'add', label: '新建本人值班草稿'},
      {key: 'edit', label: '编辑本人值班草稿'},
      {key: 'del', label: '删除本人值班草稿'},
      {key: 'sign', label: '签署本人值班草稿'},
      {key: 'return', label: '退回已签部门值班日志'},
      {key: 'export', label: '导出部门值班日志 PDF'},
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
    key: 'alert',
    label: '系统告警',
    perms: [
      {key: 'view', label: '查看系统告警'},
      {key: 'resolve', label: '处理系统告警'},
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
    key: 'approval',
    label: '批复管理',
    perms: [
      {key: 'view', label: '查看批复'},
      {key: 'add', label: '新增批复'},
      {key: 'edit', label: '编辑批复'},
      {key: 'del', label: '删除批复'},
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
}, {
  key: 'home',
  label: '首页与公告',
  pages: [{
    key: 'announcement',
    label: '公告管理',
    perms: [
      {key: 'view', label: '查看公告'},
      {key: 'add', label: '新建公告'},
      {key: 'edit', label: '编辑公告'},
      {key: 'delete', label: '删除公告'},
      {key: 'publish', label: '发布公告'},
      {key: 'withdraw', label: '撤回公告'},
    ]
  }]
}]


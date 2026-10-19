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
  // runlog（事件管理）与 duty（值班日志）权限组已随两模块 2026-10-11 整体下线删除，
  // 权限码退役；存量角色 JSON 中的 runlog./duty. 权限码惰性失效（无任何后端校验
  // 引用），无需清洗，角色保存时会自然剪除；"部门值班日志"为独立模块继续保留。
  key: 'equipment_lifecycle',
  label: '设备管理',
  pages: [{
    key: 'system',
    label: '系统主数据',
    perms: [
      {key: 'view', label: '查看系统'},
      {key: 'add', label: '新增系统'},
      {key: 'edit', label: '编辑系统'},
      {key: 'del', label: '删除系统'},
      {key: 'deactivate', label: '停用/启用系统'},
      {key: 'export', label: '导出系统列表'},
    ]
  }, {
    // 运行处置记录（2026-10-11 合并改造）：原 fault（故障处置）与
    // runtime_record（运行记录）权限组合并换发为本组权限码，system_event
    //（系统履历）权限随履历退役删除；存量角色 JSON 由迁移 0013 清洗换发。
    key: 'operation_record',
    label: '运行处置记录',
    perms: [
      {key: 'view', label: '查看记录'},
      {key: 'add', label: '新增记录（一般记录/异常事件）'},
      {key: 'add_fault', label: '登记设备故障（含台账异常转故障）'},
      {key: 'edit', label: '编辑记录/更正进展/原因分析/记录附件'},
      {key: 'progress', label: '追加进展'},
      {key: 'complete', label: '完成跟进（异常事件）'},
      {key: 'identify_fault', label: '认定设备故障（异常事件原记录认定）'},
      {key: 'recover', label: '确认恢复并结案（须同时勾选"结案"）'},
      {key: 'close', label: '结案（"确认恢复并结案"须同时勾选本项）'},
      {key: 'cancel', label: '撤销故障登记（受控撤销，非物理删除）'},
      {key: 'del', label: '删除记录（仅一般记录）'},
      {key: 'export', label: '导出记录列表'},
    ]
  }, {
    // 系统配置（2026-10）：只在系统详情"配置"页签内使用，不设独立菜单
    key: 'config',
    label: '系统配置',
    perms: [
      {key: 'view', label: '查看当前配置/变更历史/详情'},
      {key: 'add', label: '记录配置变更（创建草稿）'},
      {key: 'edit', label: '编辑/取消草稿变更'},
      {key: 'apply', label: '应用变更（配置生效）'},
      {key: 'verify', label: '验证变更'},
      {key: 'rollback', label: '回退变更（生成反向变更）'},
      {key: 'template', label: '参数定义维护（新增/编辑/停用）'},
      {key: 'attachment', label: '变更附件上传/删除'},
    ]
  }, {
    key: 'ledger_template',
    label: '台账模板',
    perms: [
      {key: 'view', label: '查看台账模板'},
      {key: 'add', label: '新增台账模板'},
      {key: 'edit', label: '编辑台账模板/项目'},
      {key: 'del', label: '停用/删除台账模板'},
    ]
  }, {
    key: 'ledger',
    label: '维护台账',
    perms: [
      {key: 'view', label: '查看台账'},
      {key: 'add', label: '新增台账'},
      {key: 'edit', label: '编辑草稿/批量确认/更正'},
      {key: 'submit', label: '完成填写台账'},
      {key: 'del', label: '作废/删除台账'},
      {key: 'export', label: '导出台账'},
      {key: 'handle_exception', label: '异常处置（周/月/季维护台账异常转故障；旧巡检台账已删除）'},
    ]
    // review（复核/退回台账）权限码已随复核流程下线退役（2026-10-16 流程简化：
    // 新流程只用 草稿/已完成/已作废 三状态），存量角色 JSON 中的该权限码惰性失效，
    // 无需清洗；inspection/work_order/system_event 权限组退役记录见下。
    // inspection（值班巡检）与 inspection_template（巡检模板）权限组已随
    // "日巡视"活跃功能整体下线删除（2026-10-11），巡检专属权限码退役；
    // 存量角色 JSON 中的巡检权限码惰性失效，无需清洗。
    // work_order（工单管理）权限组已随故障维修工单功能整体删除（2026-09-30），
    // 存量角色 JSON 中的工单权限码由迁移 0043 清洗。
    // system_event（系统履历）权限组已随系统履历整体退役删除（2026-10-11，
    // 存量角色 JSON 中的履历权限码由迁移 0013 清洗删除）。
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
    key: 'investigation',
    label: '规律调查',
    perms: [
      {key: 'view', label: '查看规律调查'},
      {key: 'add', label: '新建规律调查'},
      {key: 'edit', label: '编辑规律调查'},
      {key: 'del', label: '删除规律调查'},
    ]
  }, {
    key: 'measurement',
    label: '频谱测量',
    perms: [
      {key: 'view', label: '查看频谱测量'},
      {key: 'add', label: '录入频谱测量'},
      {key: 'edit', label: '编辑频谱测量'},
      {key: 'del', label: '删除频谱测量'},
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
    label: '操作日志',
    perms: [
      {key: 'view', label: '查看操作日志'},
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
  }, {
    key: 'release_note',
    label: '更新日志',
    perms: [
      {key: 'view', label: '查看更新日志'},
      {key: 'add', label: '新建更新日志'},
      {key: 'edit', label: '编辑更新日志'},
      {key: 'del', label: '删除更新日志'},
      {key: 'publish', label: '发布/撤回更新日志'},
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
  key: 'coop',
  label: '协作任务',
  pages: [{
    key: 'task',
    label: '协作任务',
    perms: [
      {key: 'view', label: '查看协作任务'},
      {key: 'add', label: '新建协作任务'},
      {key: 'edit', label: '编辑协作任务'},
      {key: 'delete', label: '删除/作废协作任务'},
      {key: 'submit', label: '交付材料（上传/提交）'},
      {key: 'accept', label: '验收/退回材料'},
    ]
  }]
}, {
  key: 'home',
  label: '首页与公告',
  pages: [{
    key: 'announcement',
    label: '发布公告',
    perms: [
      {key: 'view', label: '查看公告'},
      {key: 'add', label: '新建公告'},
      {key: 'edit', label: '编辑公告'},
      {key: 'delete', label: '删除公告'},
      {key: 'publish', label: '发布公告'},
      {key: 'withdraw', label: '撤回公告'},
    ]
  }, {
    key: 'reminder',
    label: '提醒事项',
    perms: [
      {key: 'view', label: '查看提醒规则'},
      {key: 'add', label: '新建提醒规则'},
      {key: 'edit', label: '编辑提醒规则'},
      {key: 'delete', label: '删除提醒规则'},
    ]
  }]
}, {
  key: 'data_analysis',
  label: '数据分析',
  pages: [{
    key: 'overview',
    label: '总览分析',
    perms: [
      {key: 'view', label: '查看总览分析'},
    ]
  }, {
    key: 'fault',
    label: '故障分析',
    perms: [
      {key: 'view', label: '查看故障分析'},
    ]
  }, {
    key: 'interference',
    label: '干扰分析',
    perms: [
      {key: 'view', label: '查看干扰分析'},
    ]
  }, {
    key: 'device',
    label: '设备分析',
    perms: [
      {key: 'view', label: '查看设备分析'},
    ]
  }, {
    key: 'upgrade',
    label: '升级分析',
    perms: [
      {key: 'view', label: '查看升级分析'},
    ]
  }]
}, {
  key: 'lab',
  label: '实验室',
  pages: [{
    key: 'native_ledger',
    label: '原生维护台账',
    perms: [
      {key: 'view', label: '查看原生维护台账'},
    ]
  }]
}]

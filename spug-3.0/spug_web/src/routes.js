/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import {
  DesktopOutlined,
  SettingOutlined,
  FolderOpenOutlined,
  FileTextOutlined,
  BugOutlined,
  ExceptionOutlined,
  CloudUploadOutlined,
  ClockCircleOutlined,
  ApartmentOutlined,
  CheckSquareOutlined,
  SafetyCertificateOutlined
} from '@ant-design/icons';

import HomeIndex from './pages/home';
import RunLogIndex from './pages/runlog';
import DeviceResume from './pages/device';
import DeviceHistory from './pages/device/History';
import ExecFaultRecord from './pages/exec/fault/record';
import ExecFaultPart from './pages/exec/fault/part';
import SystemAccount from './pages/system/account';
import SystemRole from './pages/system/role';
import SystemSetting from './pages/system/setting';
import SystemLogin from './pages/system/login';
import SystemAudit from './pages/system/audit';
import SystemTenant from './pages/system/tenant';
import WelcomeIndex from './pages/welcome/index';
import WelcomeInfo from './pages/welcome/info';
import DocumentIndex from './pages/document';
import Interference from './pages/interference';
import InterferenceStatistics from './pages/interference/Statistics';
import ExecUpgradeRecord from './pages/upgrade';
import ExecUpgradeStatistics from './pages/upgrade/Statistics';
import ExecUpgradePlan from './pages/upgrade/plan/PlanManager';
import UpgradeWorkbench from './pages/upgrade/Workbench';
import ExecDutyRecord from './pages/duty';
import CheckSheetIndex from './pages/checksheet';
import RadioLicenseIndex from './pages/radioLicense';

export default [
  {icon: <DesktopOutlined/>, title: '工作台', path: '/home', component: HomeIndex},
  {icon: <CheckSquareOutlined/>, title: '部门值班日检查单', auth: 'checksheet.checksheet.view', path: '/checksheet', component: CheckSheetIndex},
  {icon: <SafetyCertificateOutlined/>, title: '无线电台执照', auth: 'radio_license.license.view', path: '/radio-license', component: RadioLicenseIndex},
  {icon: <FolderOpenOutlined/>, title: '资料库', auth: 'document.document.view', child: [
    {title: '资料管理', auth: 'document.document.view', path: '/document', component: DocumentIndex},
  ]},
  {icon: <FileTextOutlined/>, title: '运行日志', auth: 'runlog.runlog.view', path: '/runlog', component: RunLogIndex},
  {icon: <ApartmentOutlined/>, title: '设备管理', auth: 'device.device_resume.view|device.device_history.view', child: [
    {title: '设备履历', auth: 'device.device_resume.view', path: '/device/device_resume', component: DeviceResume},
    {title: '查看履历', auth: 'device.device_history.view', path: '/device/device_history', component: DeviceHistory},
  ]},
  {icon: <ExceptionOutlined/>, title: '干扰管理', auth: 'interference.interference.view', child: [
    {title: '干扰记录', auth: 'interference.interference.view', path: '/interference', component: Interference},
    {title: '干扰统计', auth: 'interference.statistics.view', path: '/interference/statistics', component: InterferenceStatistics},
  ]},
  {icon: <CloudUploadOutlined/>, title: '系统升级管理', auth: 'upgrade.upgrade.view', child: [
    {title: '升级表单', auth: 'upgrade.upgrade.view', path: '/upgrade', component: ExecUpgradeRecord},
    {title: '统计报表', auth: 'upgrade.statistics.view', path: '/upgrade/statistics', component: ExecUpgradeStatistics},
    {title: '升级方案', auth: 'upgrade.upgrade.view', path: '/upgrade/plans', component: ExecUpgradePlan},
  ]},
  {icon: <ClockCircleOutlined/>, title: '值班日志', auth: 'duty.duty.view', path: '/duty', component: ExecDutyRecord},
  {icon: <BugOutlined/>, title: '故障管理', auth: 'fault.faultrecord.view|fault.faultpart.view', child: [
    {title: '故障处置记录', auth: 'fault.faultrecord.view', path: '/exec/fault/record', component: ExecFaultRecord},
    {title: '故障件管理', auth: 'fault.faultpart.view', path: '/exec/fault/part', component: ExecFaultPart},
  ]},
  {
    icon: <SettingOutlined/>, title: '系统管理', auth: "system.account.view|system.role.view|system.setting.view|system.audit.view|system.tenant.view", child: [
      {title: '登录日志', auth: 'system.login.view', path: '/system/login', component: SystemLogin},
      {title: '操作审计', auth: 'system.audit.view', path: '/system/audit', component: SystemAudit},
      {title: '账户管理', auth: 'system.account.view', path: '/system/account', component: SystemAccount},
      {title: '角色管理', auth: 'system.role.view', path: '/system/role', component: SystemRole},
      {title: '系统设置', auth: 'system.setting.view', path: '/system/setting', component: SystemSetting},
      {title: '租户管理', auth: 'system.tenant.view', path: '/system/tenant', component: SystemTenant},
    ]
  },
  {path: '/welcome/index', component: WelcomeIndex},
  {path: '/welcome/info', component: WelcomeInfo},
  // 升级工作台全屏页面（新建走列表页弹窗，此处仅保留编辑/查看入口）
  {path: '/upgrade/workbench/:id', component: UpgradeWorkbench},
]

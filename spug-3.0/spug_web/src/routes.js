/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import {
  DesktopOutlined,
  BarChartOutlined,
  SettingOutlined,
  ToolOutlined,
  FolderOpenOutlined,
  FileTextOutlined,
  ExceptionOutlined,
  ClockCircleOutlined,
  ApartmentOutlined,
  SafetyCertificateOutlined,
  NotificationOutlined,
  ScheduleOutlined,
  TeamOutlined,
} from '@ant-design/icons';

import HomeIndex from './pages/home';
import DataAnalysisIndex from './pages/dataAnalysis';
import RunLogIndex from './pages/runlog';
import RunLogStatistics from './pages/runlog/Statistics';
import DeviceResume from './pages/device';
import DeviceHistory from './pages/device/History';
import SystemAccount from './pages/system/account';
import SystemRole from './pages/system/role';
import SystemSetting from './pages/system/setting';
import SystemLogin from './pages/system/login';
import SystemAudit from './pages/system/audit';
import SystemMonitor from './pages/system/monitor';
import SystemDataQuality from './pages/system/dataQuality';
import SystemTenant from './pages/system/tenant';
import WelcomeIndex from './pages/welcome/index';
import WelcomeInfo from './pages/welcome/info';
import DocumentIndex from './pages/document';
import PartyBuildingDocumentsIndex from './pages/document/PartyBuildingDocumentsIndex';
import InterferenceEvents from './pages/interference/events';
import InterferenceInvestigations from './pages/interference/investigations';
import ExecUpgradeRecord from './pages/upgrade';
import ExecUpgradeStatistics from './pages/upgrade/Statistics';
import ExecUpgradePlan from './pages/upgrade/plan/PlanManager';
import UpgradeWorkbench from './pages/upgrade/Workbench';
import ExecDutyRecord from './pages/duty';
import DepartmentDutyLogIndex from './pages/departmentDutyLog';
import RadioLicenseIndex from './pages/radioLicense';
import StationFrequencyApproval from './pages/stationFrequencyApproval';
import ContractAgreementIndex from './pages/contractAgreement';
import CoopTaskIndex from './pages/coopTask';
import RegulationIndex from './pages/regulation';
import EquipmentSystemIndex from './pages/equipmentLifecycle';
import EquipmentFaultIndex from './pages/equipmentLifecycle/FaultIndex';
import EquipmentWorkOrderIndex from './pages/equipmentLifecycle/workOrder';
import EquipmentSystemEventIndex from './pages/equipmentLifecycle/systemEvent';
import EquipmentSystemStatusIndex from './pages/equipmentLifecycle/systemStatus';
import {
  WeekMonthLedgerIndex, SeasonalLedgerIndex,
  TemplateIndex as LedgerTemplateIndex,
} from './pages/equipmentLifecycle/ledger/entries';
import InspectionCenter from './pages/equipmentLifecycle/inspectionCenter';
import InspectionCenterRedirect from './pages/equipmentLifecycle/inspectionCenter/LegacyRedirect';
import AnnouncementList from './pages/home/AnnouncementList';
import AnnouncementAdmin from './pages/system/announcement';
import ReminderAdmin from './pages/reminder';
import ReleaseNotesAdmin from './pages/system/releaseNotes';

export default [
  {icon: <DesktopOutlined/>, title: '工作台', auth: 'dashboard.dashboard.view', path: '/home', component: HomeIndex},
  {icon: <BarChartOutlined/>, title: '数据分析', auth: 'data_analysis.overview.view|data_analysis.interference.view|data_analysis.device.view|data_analysis.upgrade.view', path: '/data-analysis', component: DataAnalysisIndex},
  {icon: <ScheduleOutlined/>, title: '部门值班日志', auth: 'department_duty_log.department_duty_log.view', path: '/department-duty-log', component: DepartmentDutyLogIndex},
  {icon: <SafetyCertificateOutlined/>, title: '无线电执照管理', auth: 'radio_license.license.view|radio_license.approval.view', child: [
    {title: '无线电台执照', auth: 'radio_license.license.view', path: '/radio-license', component: RadioLicenseIndex},
    {title: '台站频率批复', auth: 'radio_license.approval.view', path: '/station-frequency-approval', component: StationFrequencyApproval},
  ]},
  {icon: <FileTextOutlined/>, title: '合同协议', auth: 'contract_agreement.agreement.view', path: '/contract-agreement', component: ContractAgreementIndex},
  {icon: <TeamOutlined/>, title: '协作任务', auth: 'coop.task.view|coop.task.submit', path: '/coop-task', component: CoopTaskIndex},
  {icon: <FolderOpenOutlined/>, title: '资料库', auth: 'document.document.view|document.party_building_document.view|document.regulation.view', child: [
    {title: '公共文档', auth: 'document.document.view', path: '/document', component: DocumentIndex},
    {title: '党建工作', auth: 'document.party_building_document.view', path: '/document/party-building-documents', component: PartyBuildingDocumentsIndex},
    {title: '规章管理', auth: 'document.regulation.view', path: '/regulation', component: RegulationIndex},
  ]},
  {icon: <FileTextOutlined/>, title: '事件管理', auth: 'runlog.runlog.view', child: [
    {title: '事件列表', auth: 'runlog.runlog.view', path: '/runlog', component: RunLogIndex},
    {title: '统计概览', auth: 'runlog.runlog.view', path: '/runlog/statistics', component: RunLogStatistics},
  ]},
  {icon: <ApartmentOutlined/>, title: '设备全生命周期管理', auth: 'equipment_lifecycle.system.view|equipment_lifecycle.fault.view|equipment_lifecycle.ledger.view|equipment_lifecycle.ledger_template.view|equipment_lifecycle.inspection.view|equipment_lifecycle.inspection_template.view|equipment_lifecycle.work_order.view|equipment_lifecycle.system_event.view|upgrade.upgrade.view|upgrade.statistics.view', child: [
    {title: '系统档案', auth: 'equipment_lifecycle.system.view', path: '/el/systems', component: EquipmentSystemIndex},
    {title: '当前运行状态', auth: 'equipment_lifecycle.system.view', path: '/el/system-status', component: EquipmentSystemStatusIndex},
    {title: '运行处置', auth: 'equipment_lifecycle.fault.view|equipment_lifecycle.work_order.view', child: [
      {title: '故障管理', auth: 'equipment_lifecycle.fault.view', path: '/el/faults', component: EquipmentFaultIndex},
      {title: '工单管理', auth: 'equipment_lifecycle.work_order.view', path: '/el/work-orders', component: EquipmentWorkOrderIndex},
    ]},
    {title: '巡检与维护', auth: 'equipment_lifecycle.inspection.view|equipment_lifecycle.inspection_template.view|equipment_lifecycle.ledger.view|equipment_lifecycle.ledger_template.view', child: [
      {title: '巡检中心', auth: 'equipment_lifecycle.inspection.view|equipment_lifecycle.inspection_template.view', path: '/el/inspection-center', component: InspectionCenter},
      // 旧巡检独立路径兼容入口（菜单不再展示）：跳转到巡检中心对应页签，
      // 保留 detail 等查询参数，来源巡检单跳转（故障/工单/系统履历）不受影响
      {path: '/el/inspection-today', auth: 'equipment_lifecycle.inspection.view', component: props => <InspectionCenterRedirect tab="today" {...props}/>},
      {path: '/el/inspection-sheets', auth: 'equipment_lifecycle.inspection.view', component: props => <InspectionCenterRedirect tab="history" {...props}/>},
      {path: '/el/inspection-templates', auth: 'equipment_lifecycle.inspection_template.view', component: props => <InspectionCenterRedirect tab="templates" {...props}/>},
      {title: '周月维护台账', auth: 'equipment_lifecycle.ledger.view', path: '/el/week-month-ledgers', component: WeekMonthLedgerIndex},
      {title: '季维护台账', auth: 'equipment_lifecycle.ledger.view', path: '/el/seasonal-ledgers', component: SeasonalLedgerIndex},
      {title: '台账模板', auth: 'equipment_lifecycle.ledger_template.view', path: '/el/ledger-templates', component: LedgerTemplateIndex},
    ]},
    // 系统升级管理并入设备全生命周期管理（2026-09），升级记录/方案挂接系统档案
    {title: '系统升级管理', auth: 'upgrade.upgrade.view|upgrade.statistics.view', child: [
      {title: '升级表单', auth: 'upgrade.upgrade.view', path: '/upgrade', component: ExecUpgradeRecord},
      {title: '升级方案', auth: 'upgrade.upgrade.view', path: '/upgrade/plans', component: ExecUpgradePlan},
      {title: '统计报表', auth: 'upgrade.statistics.view', path: '/upgrade/statistics', component: ExecUpgradeStatistics},
    ]},
    {title: '履历与状态', auth: 'equipment_lifecycle.system_event.view', child: [
      {title: '系统履历', auth: 'equipment_lifecycle.system_event.view', path: '/el/system-events', component: EquipmentSystemEventIndex},
    ]},
  ]},
  {icon: <ApartmentOutlined/>, title: '设备管理', auth: 'device.device_resume.view|device.device_history.view', child: [
    {title: '设备履历', auth: 'device.device_resume.view|device.device_history.view', child: [
      {title: '设备台账', auth: 'device.device_resume.view', path: '/device/device_resume', component: DeviceResume},
      {title: '查看履历', auth: 'device.device_history.view', path: '/device/device_history', component: DeviceHistory},
    ]},
  ]},
  {icon: <ExceptionOutlined/>, title: '干扰管理', auth: 'interference.interference.view|interference.investigation.view', child: [
    {title: '干扰记录', auth: 'interference.interference.view', path: '/interference/events', component: InterferenceEvents},
    {title: '规律调查', auth: 'interference.investigation.view', path: '/interference/investigations', component: InterferenceInvestigations},
  ]},
  {icon: <ClockCircleOutlined/>, title: '值班日志', auth: 'duty.duty.view', path: '/duty', component: ExecDutyRecord},
  {icon: <NotificationOutlined/>, title: '公告与提醒', auth: 'home.announcement.view|home.reminder.view', child: [
    {title: '发布公告', auth: 'home.announcement.view', path: '/system/announcement', component: AnnouncementAdmin},
    {title: '提醒事项', auth: 'home.reminder.view', path: '/reminder', component: ReminderAdmin},
  ]},
  {
    icon: <ToolOutlined/>, title: '运维管理', auth: 'system.audit.view|system.alert.view', child: [
      {title: '操作日志', auth: 'system.audit.view', path: '/maintenance/audit', component: SystemAudit},
      {title: '系统监控', auth: 'system.alert.view', path: '/maintenance/alert', component: SystemMonitor},
      {path: '/maintenance/data-quality', component: SystemDataQuality},
    ]
  },
  {
    icon: <SettingOutlined/>, title: '系统管理', auth: 'system.account.view|system.role.view|system.setting.view|system.login.view|system.tenant.view|system.release_note.view', child: [
      {title: '登录日志', auth: 'system.login.view', path: '/system/login', component: SystemLogin},
      {title: '账户管理', auth: 'system.account.view', path: '/system/account', component: SystemAccount},
      {title: '租户管理', auth: 'system.tenant.view', path: '/system/tenant', component: SystemTenant},
      {title: '角色管理', auth: 'system.role.view', path: '/system/role', component: SystemRole},
      {title: '系统设置', auth: 'system.setting.view', path: '/system/setting', component: SystemSetting},
      {title: '更新日志', auth: 'system.release_note.view', path: '/system/release-notes', component: ReleaseNotesAdmin},
    ]
  },
  {path: '/welcome/index', component: WelcomeIndex},
  {path: '/welcome/info', component: WelcomeInfo},
  // 升级工作台全屏页面（新建走列表页弹窗，此处仅保留编辑/查看入口）
  {path: '/upgrade/workbench/:id', component: UpgradeWorkbench},
  // 公告查询页（用户端，从首页“更多”进入，不在菜单展示）
  {path: '/announcement', component: AnnouncementList},
]

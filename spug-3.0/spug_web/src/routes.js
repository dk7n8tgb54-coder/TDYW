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
  ApartmentOutlined,
  SafetyCertificateOutlined,
  NotificationOutlined,
  ScheduleOutlined,
  TeamOutlined,
} from '@ant-design/icons';

import HomeIndex from './pages/home';
import DataAnalysisIndex from './pages/dataAnalysis';
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
import UpgradeCenter, {UpgradeCenterRedirect} from './pages/upgrade/UpgradeCenter';
import UpgradeWorkbench from './pages/upgrade/Workbench';
import DepartmentDutyLogIndex from './pages/departmentDutyLog';
import RadioLicenseIndex from './pages/radioLicense';
import StationFrequencyApproval from './pages/stationFrequencyApproval';
import ContractAgreementIndex from './pages/contractAgreement';
import CoopTaskIndex from './pages/coopTask';
import RegulationIndex from './pages/regulation';
import EquipmentSystemIndex from './pages/equipmentLifecycle';
import EquipmentOperationRecordIndex from './pages/equipmentLifecycle/operationRecord';
import {
  WeekMonthLedgerIndex, SeasonalLedgerIndex,
} from './pages/equipmentLifecycle/ledger/entries';
import ExcelTemplatePage from './pages/equipmentLifecycle/ledger/excel/ExcelTemplatePage';
import ExcelLedgerRedirect from './pages/equipmentLifecycle/ledger/excel/ExcelLedgerRedirect';
import AnnouncementList from './pages/home/AnnouncementList';
import AnnouncementAdmin from './pages/system/announcement';
import ReminderAdmin from './pages/reminder';
import ReleaseNotesAdmin from './pages/system/releaseNotes';

export default [
  {icon: <DesktopOutlined/>, title: '工作台', auth: 'dashboard.dashboard.view', path: '/home', component: HomeIndex},
  {icon: <BarChartOutlined/>, title: '数据分析', auth: 'data_analysis.overview.view|data_analysis.interference.view|data_analysis.upgrade.view', path: '/data-analysis', component: DataAnalysisIndex},
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
  // "事件管理"（runlog）与"值班日志"（duty）菜单已随 2026-10-11 模块下线
  // 整体删除（前端页面/路由/权限码与后端 API、数据表同步移除），
  // "部门值班日志"（department_duty_log）为独立模块，继续保留。
  {icon: <ApartmentOutlined/>, title: '设备管理', auth: 'equipment_lifecycle.system.view|equipment_lifecycle.operation_record.view|equipment_lifecycle.ledger.view|equipment_lifecycle.ledger_template.view|upgrade.upgrade.view', child: [
    {title: '系统档案', auth: 'equipment_lifecycle.system.view', path: '/el/systems', component: EquipmentSystemIndex},
    // 运行处置记录（2026-10-11 合并改造；2026-10-14 由"运行与故障记录"更名）：
    // 原"运行处置"分组下的"故障处置""运行记录"两菜单合并为统一入口，
    // 承载一般记录/异常事件/设备故障三类记录；旧 /el/faults、
    // /el/runtime-records 路由删除，不保留旧页面链接兼容层
    {title: '运行处置记录', auth: 'equipment_lifecycle.operation_record.view', path: '/el/records', component: EquipmentOperationRecordIndex},
    // "巡视与维护"更名"维护台账"（2026-10-11）：日巡视活跃功能已整体下线
    // （前端页面/Store/路由与后端巡检 API 同步移除，权限码退役），
    // 本组只保留周月维护台账、季维护台账与 Excel 台账模板。
    {title: '维护台账', auth: 'equipment_lifecycle.ledger.view|equipment_lifecycle.ledger_template.view', child: [
      {title: '周月维护台账', auth: 'equipment_lifecycle.ledger.view', path: '/el/week-month-ledgers', component: WeekMonthLedgerIndex},
      {title: '季维护台账', auth: 'equipment_lifecycle.ledger.view', path: '/el/seasonal-ledgers', component: SeasonalLedgerIndex},
      // 旧可视化"台账模板"入口已随旧可视化模板路线整体删除（2026-10），
      // 正式新增台账统一在各台账列表页选择已发布的 Excel/WPS 模板版本创建
      // Excel 上传版维护台账模板管理（上传/绑定/批量绑定/PDF 参数/发布/停用/删除）
      {title: 'Excel台账模板', auth: 'equipment_lifecycle.ledger_template.view', path: '/el/excel-ledger-templates', component: ExcelTemplatePage},
      // Excel 维护台账独立入口已并入正式周月/季维护台账（2026-10）：菜单不再
      // 展示，旧路径保留隐藏兼容路由并原样携带查询参数（?detail=&source=excel
      // 由正式台账页打开 Excel 台账详情）
      {path: '/el/excel-ledgers', auth: 'equipment_lifecycle.ledger.view', component: props => <ExcelLedgerRedirect {...props}/>},
    ]},
    // 系统升级管理并入设备全生命周期管理（2026-09），升级记录/方案挂接系统档案；
    // 升级表单/升级方案融合为页签（2026-10，参照巡检中心），不再各占菜单项
    // "系统履历"菜单已随 2026-10-11 合并改造整体下线（模型/接口/权限退役，
    // 系统档案按系统直接查询统一记录等业务表）
    {title: '系统升级管理', auth: 'upgrade.upgrade.view', path: '/upgrade', component: UpgradeCenter},
  ]},
  {icon: <ExceptionOutlined/>, title: '干扰管理', auth: 'interference.interference.view|interference.investigation.view', child: [
    {title: '干扰记录', auth: 'interference.interference.view', path: '/interference/events', component: InterferenceEvents},
    {title: '规律调查', auth: 'interference.investigation.view', path: '/interference/investigations', component: InterferenceInvestigations},
  ]},
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
  // 旧升级方案独立路径兼容入口（菜单不再展示）：跳转到升级中心方案页签
  {path: '/upgrade/plans', auth: 'upgrade.upgrade.view', component: props => <UpgradeCenterRedirect tab="plans" {...props}/>},
  // 公告查询页（用户端，从首页“更多”进入，不在菜单展示）
  {path: '/announcement', component: AnnouncementList},
]

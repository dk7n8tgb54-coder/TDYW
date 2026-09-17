import radioLicenseBadge from '../layout/RadioLicenseBadgeStore';

export const licenseReminderConfig = {
  key: 'license',
  label: '执照',
  permission: 'radio_license.license.view',
  popupUrl: '/api/radio-license/reminders/popup/',
  ackUrl: '/api/radio-license/reminders/ack/',
  ackIdField: 'license_id',
  badgeStore: radioLicenseBadge,
  getRecordId: record => record.license_id,
  getTitle: record => record.station_name,
  getRoute: id => `/radio-license?id=${id}`,
  muteKeyPrefix: 'spug_license_reminder_muted',
  getCycleKey: record => `${record.license_id}:${record.valid_to}`,
  buildAckPayload: record => ({ license_id: record.license_id }),
  getReminderContent: (record, isExpired) => {
    if (isExpired) {
      return `执照"${record.station_name}"已过期 ${Math.abs(record.days_left)} 天，请及时处理。`;
    }
    return `执照"${record.station_name}"（${record.valid_from} ~ ${record.valid_to}）将于 ${record.days_left} 天后到期，请及时续期。`;
  },
};

// 台站频率批复已于 2026-09 第一轮改造取消主动到期提醒：
// approvalReminderConfig 与 ApprovalBadgeStore 已移除，后端 popup/ack/badge 接口下线。
// 提醒接收人配置留待下一轮；届时如需恢复弹窗，可参照 licenseReminderConfig 重建配置。

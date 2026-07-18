import radioLicenseBadge from '../layout/RadioLicenseBadgeStore';
import approvalBadge from '../layout/ApprovalBadgeStore';

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

// 批复后端接口上线后，将此配置传给 ExpirationReminderNotification。
// 配置先独立维护，避免把批复字段和执照字段耦合到通用组件中。
export const approvalReminderConfig = {
  key: 'approval',
  label: '批复',
  permission: 'radio_license.approval.view',
  popupUrl: '/api/radio-license/approvals/reminders/popup/',
  ackUrl: '/api/radio-license/approvals/reminders/ack/',
  ackIdField: 'approval_id',
  badgeStore: approvalBadge,
  getRecordId: record => record.approval_id,
  getTitle: record => record.name,
  getDocNo: record => record.doc_no,
  getRoute: id => `/station-frequency-approval?id=${id}`,
  muteKeyPrefix: 'spug_approval_reminder_muted',
  getCycleKey: record => `${record.approval_id}:${record.valid_to}`,
  buildAckPayload: record => ({ approval_id: record.approval_id }),
  getReminderContent: (record, isExpired) => {
    const title = `批复"${record.name}"${record.doc_no ? `（${record.doc_no}）` : ''}`;
    if (isExpired) {
      return `${title}已过期 ${Math.abs(record.days_left)} 天，请及时处理。`;
    }
    return `${title}（${record.valid_from} ~ ${record.valid_to}）将于 ${record.days_left} 天后到期，请及时续期。`;
  },
};

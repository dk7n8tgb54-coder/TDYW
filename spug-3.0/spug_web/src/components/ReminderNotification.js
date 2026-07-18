import React from 'react';
import ExpirationReminderNotification from './ExpirationReminderNotification';
import { licenseReminderConfig } from './expirationReminderConfigs';

// 保留旧导出，避免其他页面或插件直接引用 ReminderNotification 时失效。
export default function ReminderNotification() {
  return <ExpirationReminderNotification config={licenseReminderConfig} />;
}

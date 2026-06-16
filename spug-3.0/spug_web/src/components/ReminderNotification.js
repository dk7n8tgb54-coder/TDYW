/**
 * 全局执照到期提醒弹窗组件
 *
 * 挂载在 Layout 中，自动拉取当前用户未读提醒并在右下角弹窗通知。
 * - 同一提醒在同一登录会话内只弹一次（sessionStorage + token key 去重，重新登录后可再弹）
 * - 关闭弹窗不等于已读，已读状态由提醒处理接口控制
 * - 点击弹窗跳转到执照详情页
 * - 5 分钟轮询检查新提醒
 */
import React, { useEffect, useRef } from 'react';
import { notification, Tag } from 'antd';
import { WarningOutlined, ClockCircleOutlined } from '@ant-design/icons';
import { http, history } from 'libs';

const POLL_INTERVAL = 5 * 60 * 1000; // 5 分钟
const STORAGE_KEY_PREFIX = 'spug_reminder_notified';

// 基于 token 的去重 key，换 token（重新登录）后自动重置
function getStorageKey() {
  const token = sessionStorage.getItem('token') || '';
  return `${STORAGE_KEY_PREFIX}_${token.slice(-8)}`;
}

const REMIND_TYPE_MAP = {
  expiring_45: {color: 'blue', text: '45天提醒'},
  expiring_30: {color: 'cyan', text: '30天提醒'},
  expiring_15: {color: 'orange', text: '15天提醒'},
  expiring_7:  {color: 'volcano', text: '7天提醒'},
  expiring_1:  {color: 'red', text: '1天提醒'},
  expired:     {color: 'red', text: '已过期'},
};

function showReminderNotification(reminder) {
  const typeInfo = REMIND_TYPE_MAP[reminder.remind_type] || {color: 'default', text: reminder.remind_type};
  const isExpired = reminder.remind_type === 'expired';
  const icon = isExpired
    ? <WarningOutlined style={{color: '#ff4d4f'}} />
    : <ClockCircleOutlined style={{color: '#fa8c16'}} />;

  notification.warning({
    key: `reminder-${reminder.id}`,
    message: (
      <span>
        <Tag color={typeInfo.color} style={{marginRight: 6}}>{typeInfo.text}</Tag>
        {reminder.title || '执照到期提醒'}
      </span>
    ),
    description: (
      <div>
        <div>{reminder.content}</div>
        {reminder.days_left !== undefined && reminder.days_left !== null && (
          <div style={{marginTop: 4, fontSize: 12, color: isExpired ? '#ff4d4f' : '#8c8c8c'}}>
            {isExpired
              ? `已过期 ${Math.abs(reminder.days_left)} 天`
              : `剩余 ${reminder.days_left} 天`}
          </div>
        )}
      </div>
    ),
    icon,
    placement: 'bottomRight',
    duration: 0, // 不自动关闭，需用户手动关
    onClick: () => {
      notification.close(`reminder-${reminder.id}`);
      // 跳转到执照详情
      history.push(`/radio-license?id=${reminder.license_id}`);
    },
  });
}

export default function ReminderNotification() {
  const timerRef = useRef(null);

  function fetchAndNotify() {
    http.get('/api/radio-license/reminders/', {params: {is_read: 'false', page_size: 50}})
      .then(({records}) => {
        if (!records || !records.length) return;
        const key = getStorageKey();
        let notifiedIds;
        try {
          notifiedIds = new Set(JSON.parse(sessionStorage.getItem(key) || '[]'));
        } catch {
          notifiedIds = new Set();
        }
        const newIds = [...notifiedIds];
        records.forEach(r => {
          if (!notifiedIds.has(r.id)) {
            newIds.push(r.id);
            showReminderNotification(r);
          }
        });
        try {
          sessionStorage.setItem(key, JSON.stringify(newIds));
        } catch { /* ignore */ }
      })
      .catch(() => {});
  }

  useEffect(() => {
    // 首次加载延迟 2 秒，等页面渲染完
    const initTimer = setTimeout(fetchAndNotify, 2000);
    // 5 分钟轮询
    timerRef.current = setInterval(fetchAndNotify, POLL_INTERVAL);
    return () => {
      clearTimeout(initTimer);
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  return null; // 纯逻辑组件，不渲染 DOM
}

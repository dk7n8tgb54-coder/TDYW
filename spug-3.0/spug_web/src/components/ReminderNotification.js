/**
 * 全局执照到期提醒弹窗组件
 *
 * 挂载在 Layout 中，自动拉取当前用户"未处理"提醒并在右下角弹窗通知。
 *
 * 设计要点（2026-06-22 重构）：
 * - 拉取接口改用 is_handled=false（已读不等于已处理，只有 is_handled=True 才停止弹窗）
 * - 即将到期执照每天都会生成新的 expiring_daily 提醒，从而实现"每日提醒"
 * - 不再用 sessionStorage 按 reminder.id 做永久会话去重（会破坏每日提醒需求）
 * - 用组件内存 Set 控制本次生命周期内不重复弹同一条（5 分钟轮询不会重复弹）
 * - "今日不再提醒"按钮：localStorage 按日期 + license_id + 用户 token 维度抑制当天弹窗
 *   - 不调用 handle，不标记为已处理
 *   - 第二天日期变化后自动失效，可再次弹窗
 * - 普通关闭弹窗只是关闭，不等于"今日不再提醒"
 * - 点击弹窗主体仍跳转到 /radio-license?id={license_id}
 */
import React, { useEffect, useRef } from 'react';
import { notification, Tag, Button } from 'antd';
import { WarningOutlined, ClockCircleOutlined } from '@ant-design/icons';
import { http, history } from 'libs';

const POLL_INTERVAL = 5 * 60 * 1000; // 5 分钟
const MUTE_KEY_PREFIX = 'spug_reminder_muted';

// 用户维度标识（用户 ID，不随 token 变化，重新登录后仍能保持"今日不再提醒"）
function getUserId() {
  return sessionStorage.getItem('id') || '0';
}

// 今日免提醒的 localStorage key（含用户维度 + 日期维度）
function getMuteKey(today) {
  return `${MUTE_KEY_PREFIX}_${getUserId()}_${today}`;
}

// 获取今日（YYYY-MM-DD）已免提醒的 license_id 集合
function getTodayMutedLicenses() {
  const today = new Date().toISOString().slice(0, 10);
  try {
    return new Set(JSON.parse(localStorage.getItem(getMuteKey(today)) || '[]'));
  } catch {
    return new Set();
  }
}

// 标记某 license 今日免提醒
function muteLicenseToday(licenseId) {
  const today = new Date().toISOString().slice(0, 10);
  const set = getTodayMutedLicenses();
  set.add(licenseId);
  try {
    localStorage.setItem(getMuteKey(today), JSON.stringify([...set]));
  } catch { /* ignore quota errors */ }
}

// 清理过期的免提醒记录（仅保留今天的，避免 localStorage 膨胀）
function cleanupExpiredMute() {
  const today = new Date().toISOString().slice(0, 10);
  const prefix = `${MUTE_KEY_PREFIX}_${getUserId()}_`;
  const keysToRemove = [];
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i);
    if (key && key.startsWith(prefix) && !key.endsWith(`_${today}`)) {
      keysToRemove.push(key);
    }
  }
  keysToRemove.forEach(k => { try { localStorage.removeItem(k); } catch { /* ignore */ } });
}

const REMIND_TYPE_MAP = {
  // 新版
  expiring_daily: {color: 'orange', text: '即将到期'},
  expired:        {color: 'red',    text: '已过期'},
  // 兼容历史分级提醒数据
  expiring_45: {color: 'blue',    text: '即将到期'},
  expiring_30: {color: 'cyan',    text: '即将到期'},
  expiring_15: {color: 'orange',  text: '即将到期'},
  expiring_7:  {color: 'volcano', text: '即将到期'},
  expiring_1:  {color: 'red',     text: '即将到期'},
};

function showReminderNotification(reminder) {
  const typeInfo = REMIND_TYPE_MAP[reminder.remind_type] || {color: 'default', text: reminder.remind_type};
  const isExpired = reminder.remind_type === 'expired';
  const icon = isExpired
    ? <WarningOutlined style={{color: '#ff4d4f'}} />
    : <ClockCircleOutlined style={{color: '#fa8c16'}} />;
  const notifKey = `reminder-${reminder.id}`;

  notification.warning({
    key: notifKey,
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
        <div style={{marginTop: 8, textAlign: 'right'}}>
          <Button
            size="small"
            type="link"
            onClick={(e) => {
              // 阻止冒泡到 notification 的 onClick（避免误触发跳转）
              e.stopPropagation();
              if (reminder.license_id) {
                muteLicenseToday(reminder.license_id);
              }
              notification.close(notifKey);
            }}
          >
            今日不再提醒
          </Button>
        </div>
      </div>
    ),
    icon,
    placement: 'bottomRight',
    duration: 0, // 不自动关闭，需用户手动关
    onClick: () => {
      notification.close(notifKey);
      // 跳转到执照详情
      history.push(`/radio-license?id=${reminder.license_id}`);
    },
  });
}

export default function ReminderNotification() {
  const timerRef = useRef(null);
  // 本次组件生命周期内已弹过的 reminder.id 集合
  // 用于 5 分钟轮询时不重复弹同一条（不持久化，刷新页面后清空）
  const notifiedIdsRef = useRef(new Set());

  function fetchAndNotify() {
    http.get('/api/radio-license/reminders/', {params: {is_handled: 'false', page_size: 50}})
      .then(({records}) => {
        if (!records || !records.length) return;
        // 清理过期免提醒记录
        cleanupExpiredMute();
        // 今日已免提醒的 license_id 集合
        const mutedLicenses = getTodayMutedLicenses();
        // 本次生命周期已弹过的 reminder.id
        const notifiedIds = notifiedIdsRef.current;
        records.forEach(r => {
          // 跳过本次生命周期已弹过的（避免 5 分钟轮询重复弹）
          if (notifiedIds.has(r.id)) return;
          // 跳过今日已免提醒的 license
          if (r.license_id && mutedLicenses.has(r.license_id)) return;
          // 标记已弹过并展示
          notifiedIds.add(r.id);
          showReminderNotification(r);
        });
      })
      .catch(() => {});
  }

  useEffect(() => {
    // 进入时先清理过期免提醒记录
    cleanupExpiredMute();
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

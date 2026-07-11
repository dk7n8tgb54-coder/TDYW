/**
 * 全局执照到期提醒弹窗组件（执照中心模型）
 *
 * 重构说明（2026-06-23）：
 * - 改用 /api/radio-license/reminders/popup/ 接口，实时查询 expiring/expired 执照
 * - days_left 由后端实时计算（基于 license.valid_to），不再读快照
 * - "已处理"由 LicenseReminderAck 表管理，续期后自动失效
 * - 去重 key 从 reminder.id 改为 license_id（新接口无 reminder.id）
 * - content 由前端拼装（不依赖预生成数据）
 *
 * 保留逻辑：
 * - "今日不再提醒"：localStorage 按日期 + license_id + 用户维度抑制当天弹窗
 * - 5 分钟轮询，组件内存 Set 控制本次生命周期不重复弹同一 license
 * - 点击弹窗跳转 /radio-license?id={license_id}
 */
import React, { useEffect, useRef } from 'react';
import { notification, Tag, Button } from 'antd';
import { WarningOutlined, ClockCircleOutlined } from '@ant-design/icons';
import { http, history } from 'libs';
import radioLicenseBadge from '../layout/RadioLicenseBadgeStore';

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
  expiring_daily: {color: 'orange', text: '即将到期'},
  expired:        {color: 'red',    text: '已过期'},
};

function showReminderNotification(record) {
  const typeInfo = REMIND_TYPE_MAP[record.remind_type] || {color: 'default', text: record.remind_type};
  const isExpired = record.remind_type === 'expired';
  const icon = isExpired
    ? <WarningOutlined style={{color: '#ff4d4f'}} />
    : <ClockCircleOutlined style={{color: '#fa8c16'}} />;
  // 用 license_id 作为 notification key（新接口无 reminder.id）
  const notifKey = `license-${record.license_id}`;

  // content 由前端实时拼装（不依赖后端预生成）
  const content = isExpired
    ? `执照"${record.station_name}"已过期 ${Math.abs(record.days_left)} 天，请及时处理。`
    : `执照"${record.station_name}"（${record.valid_from} ~ ${record.valid_to}）将于 ${record.days_left} 天后到期，请及时续期。`;

  notification.warning({
    key: notifKey,
    message: (
      <span>
        <Tag color={typeInfo.color} style={{marginRight: 6}}>{typeInfo.text}</Tag>
        {record.station_name || '执照到期提醒'}
      </span>
    ),
    description: (
      <div>
        <div>{content}</div>
        {record.days_left !== undefined && record.days_left !== null && (
          <div style={{marginTop: 4, fontSize: 12, color: isExpired ? '#ff4d4f' : '#8c8c8c'}}>
            {isExpired
              ? `已过期 ${Math.abs(record.days_left)} 天`
              : `剩余 ${record.days_left} 天`}
          </div>
        )}
        <div style={{marginTop: 8, textAlign: 'right'}}>
          <Button
            size="small"
            type="link"
            onClick={(e) => {
              // 阻止冒泡到 notification 的 onClick（避免误触发跳转）
              e.stopPropagation();
              if (record.license_id) {
                muteLicenseToday(record.license_id);
              }
              notification.close(notifKey);
            }}
          >
            今日不再提醒
          </Button>
          <Button
            size="small"
            type="primary"
            onClick={(e) => {
              e.stopPropagation();
              http.post('/api/radio-license/reminders/ack/', {license_id: record.license_id})
                .then(() => radioLicenseBadge.fetch())
                .finally(() => notification.close(notifKey));
            }}
          >
            已处理
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
      history.push(`/radio-license?id=${record.license_id}`);
    },
  });
}

export default function ReminderNotification() {
  const timerRef = useRef(null);
  // 本次组件生命周期内已弹过的 license_id 集合
  // 用于 5 分钟轮询时不重复弹同一执照（不持久化，刷新页面后清空）
  const notifiedLicenseIdsRef = useRef(new Set());

  function fetchAndNotify() {
    // 改用弹窗专用接口：实时查询 expiring/expired 执照，排除已 ack 的
    http.get('/api/radio-license/reminders/popup/')
      .then(({records}) => {
        if (!records || !records.length) return;
        // 清理过期免提醒记录
        cleanupExpiredMute();
        // 今日已免提醒的 license_id 集合
        const mutedLicenses = getTodayMutedLicenses();
        // 本次生命周期已弹过的 license_id
        const notifiedLicenseIds = notifiedLicenseIdsRef.current;
        records.forEach(r => {
          // 跳过本次生命周期已弹过的（避免 5 分钟轮询重复弹）
          if (notifiedLicenseIds.has(r.license_id)) return;
          // 跳过今日已免提醒的 license
          if (r.license_id && mutedLicenses.has(r.license_id)) return;
          // 标记已弹过并展示
          notifiedLicenseIds.add(r.license_id);
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

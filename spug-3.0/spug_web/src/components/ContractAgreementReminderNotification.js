/**
 * 全局合同协议到期提醒。
 */
import React, { useEffect, useRef } from 'react';
import { notification, Tag, Button } from 'antd';
import { WarningOutlined, ClockCircleOutlined } from '@ant-design/icons';
import { http, history, hasPermission } from 'libs';
import contractAgreementBadge from '../layout/ContractAgreementBadgeStore';

const POLL_INTERVAL = 5 * 60 * 1000;
const MUTE_KEY_PREFIX = 'spug_contract_agreement_reminder_muted';

function getUserId() {
  return sessionStorage.getItem('id') || '0';
}

function getMuteKey(today) {
  return `${MUTE_KEY_PREFIX}_${getUserId()}_${today}`;
}

function getTodayMutedAgreements() {
  const today = new Date().toISOString().slice(0, 10);
  try {
    return new Set(JSON.parse(localStorage.getItem(getMuteKey(today)) || '[]'));
  } catch {
    return new Set();
  }
}

function muteAgreementToday(agreementId) {
  const today = new Date().toISOString().slice(0, 10);
  const set = getTodayMutedAgreements();
  set.add(agreementId);
  try {
    localStorage.setItem(getMuteKey(today), JSON.stringify([...set]));
  } catch {}
}

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
  keysToRemove.forEach(k => {
    try { localStorage.removeItem(k); } catch {}
  });
}

const REMIND_TYPE_MAP = {
  expiring_daily: {color: 'orange', text: '即将到期'},
  expired: {color: 'red', text: '已过期'},
};

function showReminderNotification(record) {
  const typeInfo = REMIND_TYPE_MAP[record.remind_type] || {color: 'default', text: record.remind_type};
  const isExpired = record.remind_type === 'expired';
  const icon = isExpired
    ? <WarningOutlined style={{color: '#ff4d4f'}}/>
    : <ClockCircleOutlined style={{color: '#fa8c16'}}/>;
  const notifKey = `contract-agreement-${record.agreement_id}`;
  const content = isExpired
    ? `合同"${record.contract_name}"已过期 ${Math.abs(record.days_left)} 天，请及时处理。`
    : `合同"${record.contract_name}"将于 ${record.days_left} 天后到期，请及时处理。`;

  notification.warning({
    key: notifKey,
    message: (
      <span>
        <Tag color={typeInfo.color} style={{marginRight: 6}}>{typeInfo.text}</Tag>
        {record.contract_name || '合同协议到期提醒'}
      </span>
    ),
    description: (
      <div>
        <div>{content}</div>
        <div style={{marginTop: 4, fontSize: 12, color: isExpired ? '#ff4d4f' : '#8c8c8c'}}>
          截止日期：{record.valid_end_date}
        </div>
        <div style={{marginTop: 8, textAlign: 'right'}}>
          <Button
            size="small"
            type="link"
            onClick={(e) => {
              e.stopPropagation();
              if (record.agreement_id) {
                muteAgreementToday(record.agreement_id);
              }
              notification.close(notifKey);
            }}>
            今日不再提醒
          </Button>
          <Button
            size="small"
            type="primary"
            onClick={(e) => {
              e.stopPropagation();
              http.post('/api/contract-agreement/reminders/ack/', {agreement_id: record.agreement_id})
                .then(() => contractAgreementBadge.fetch())
                .finally(() => notification.close(notifKey));
            }}>
            已处理
          </Button>
        </div>
      </div>
    ),
    icon,
    placement: 'bottomRight',
    duration: 0,
    onClick: () => {
      notification.close(notifKey);
      history.push(`/contract-agreement?id=${record.agreement_id}`);
    },
  });
}

export default function ContractAgreementReminderNotification() {
  const timerRef = useRef(null);
  const notifiedIdsRef = useRef(new Set());

  function fetchAndNotify() {
    if (!hasPermission('contract_agreement.agreement.view')) return;
    http.get('/api/contract-agreement/reminders/popup/')
      .then(({records}) => {
        if (!records || !records.length) return;
        cleanupExpiredMute();
        const muted = getTodayMutedAgreements();
        const notified = notifiedIdsRef.current;
        records.forEach(r => {
          if (notified.has(r.agreement_id)) return;
          if (r.agreement_id && muted.has(r.agreement_id)) return;
          notified.add(r.agreement_id);
          showReminderNotification(r);
        });
      })
      .catch(() => {});
  }

  useEffect(() => {
    if (!hasPermission('contract_agreement.agreement.view')) return undefined;
    cleanupExpiredMute();
    const initTimer = setTimeout(fetchAndNotify, 2500);
    timerRef.current = setInterval(fetchAndNotify, POLL_INTERVAL);
    return () => {
      clearTimeout(initTimer);
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  return null;
}

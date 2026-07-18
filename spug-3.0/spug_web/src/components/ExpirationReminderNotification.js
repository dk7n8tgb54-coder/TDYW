/**
 * 通用到期提醒通知组件。
 *
 * 业务模块只需要提供接口、字段适配、跳转和 Badge Store，提醒生命周期、
 * 有效期周期去重以及“今日不再提醒”逻辑由这里统一处理。
 */
import React, { useEffect, useRef } from 'react';
import { notification, Tag, Button } from 'antd';
import { WarningOutlined, ClockCircleOutlined } from '@ant-design/icons';
import { http, history, hasPermission } from 'libs';

const POLL_INTERVAL = 5 * 60 * 1000;

const REMIND_TYPE_MAP = {
  expiring_daily: { color: 'orange', text: '即将到期' },
  expired: { color: 'red', text: '已过期' },
};

function getUserId() {
  return sessionStorage.getItem('id') || '0';
}

function getLocalDateKey() {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${month}-${day}`;
}

function getCycleKey(record, config) {
  if (config.getCycleKey) return config.getCycleKey(record);
  const id = config.getRecordId(record);
  return `${id}:${record.valid_to || ''}`;
}

function getMuteStorageKey(config, dateKey) {
  return `${config.muteKeyPrefix}_${getUserId()}_${dateKey}`;
}

function getMutedCycles(config) {
  const dateKey = getLocalDateKey();
  try {
    return new Set(JSON.parse(localStorage.getItem(getMuteStorageKey(config, dateKey)) || '[]'));
  } catch (e) {
    return new Set();
  }
}

function muteCycle(config, cycleKey) {
  const dateKey = getLocalDateKey();
  const muted = getMutedCycles(config);
  muted.add(cycleKey);
  try {
    localStorage.setItem(
      getMuteStorageKey(config, dateKey),
      JSON.stringify([...muted]),
    );
  } catch (e) {
    // localStorage 不可用时不影响服务端 ack 和通知操作。
  }
}

function cleanupMutedCycles(config) {
  const today = getLocalDateKey();
  const prefix = `${config.muteKeyPrefix}_${getUserId()}_`;
  const keysToRemove = [];
  for (let i = 0; i < localStorage.length; i += 1) {
    const key = localStorage.key(i);
    if (key && key.startsWith(prefix) && !key.endsWith(`_${today}`)) {
      keysToRemove.push(key);
    }
  }
  keysToRemove.forEach(key => {
    try {
      localStorage.removeItem(key);
    } catch (e) {
      // 忽略单个缓存清理失败。
    }
  });
}

function normalizeRecords(response) {
  if (Array.isArray(response)) return response;
  if (response && Array.isArray(response.records)) return response.records;
  return [];
}

function getRemindType(record) {
  if (record.remind_type) return record.remind_type;
  return Number(record.days_left) < 0 ? 'expired' : 'expiring_daily';
}

function defaultReminderContent(record, config, isExpired) {
  const title = config.getTitle(record) || config.label || '记录';
  if (isExpired) {
    return `${config.label || ''}"${title}"已过期 ${Math.abs(record.days_left)} 天，请及时处理。`;
  }
  const docNo = config.getDocNo ? config.getDocNo(record) : '';
  const suffix = docNo ? `（${docNo}）` : '';
  return `${config.label || ''}"${title}"${suffix}将于 ${record.days_left} 天后到期，请及时续期。`;
}

function showReminderNotification(record, config) {
  const remindType = getRemindType(record);
  const typeInfo = REMIND_TYPE_MAP[remindType] || {
    color: 'default',
    text: remindType,
  };
  const isExpired = remindType === 'expired';
  const cycleKey = getCycleKey(record, config);
  const recordId = config.getRecordId(record);
  const title = config.getTitle(record) || config.label || '到期提醒';
  const notifKey = `expiration-${config.key}-${cycleKey}`;
  const content = config.getReminderContent
    ? config.getReminderContent(record, isExpired)
    : defaultReminderContent(record, config, isExpired);

  const close = () => notification.close(notifKey);

  notification.warning({
    key: notifKey,
    message: (
      <span>
        <Tag color={typeInfo.color} style={{ marginRight: 6 }}>{typeInfo.text}</Tag>
        {title}
      </span>
    ),
    description: (
      <div>
        <div>{content}</div>
        {record.days_left !== undefined && record.days_left !== null && (
          <div style={{ marginTop: 4, fontSize: 12, color: isExpired ? '#ff4d4f' : '#8c8c8c' }}>
            {isExpired
              ? `已过期 ${Math.abs(record.days_left)} 天`
              : `剩余 ${record.days_left} 天`}
          </div>
        )}
        <div style={{ marginTop: 8, textAlign: 'right' }}>
          <Button
            size="small"
            type="link"
            onClick={event => {
              event.stopPropagation();
              muteCycle(config, cycleKey);
              close();
            }}
          >
            今日不再提醒
          </Button>
          <Button
            size="small"
            type="primary"
            onClick={event => {
              event.stopPropagation();
              const payload = config.buildAckPayload
                ? config.buildAckPayload(record)
                : { [config.ackIdField || 'license_id']: recordId };
              http.post(config.ackUrl, payload)
                .then(() => {
                  if (config.badgeStore && config.badgeStore.fetch) {
                    config.badgeStore.fetch();
                  }
                  close();
                })
                .catch(() => null);
            }}
          >
            已处理
          </Button>
        </div>
      </div>
    ),
    icon: isExpired
      ? <WarningOutlined style={{ color: '#ff4d4f' }} />
      : <ClockCircleOutlined style={{ color: '#fa8c16' }} />,
    placement: 'bottomRight',
    duration: 0,
    onClick: () => {
      close();
      if (config.getRoute) history.push(config.getRoute(recordId));
    },
  });
}

export default function ExpirationReminderNotification({ config }) {
  const timerRef = useRef(null);
  const notifiedCyclesRef = useRef(new Set());

  useEffect(() => {
    if (!config || config.enabled === false || !hasPermission(config.permission)) return undefined;

    const fetchAndNotify = () => {
      http.get(config.popupUrl)
        .then(response => {
          const records = normalizeRecords(response);
          if (!records.length) return;

          cleanupMutedCycles(config);
          const mutedCycles = getMutedCycles(config);
          records.forEach(record => {
            const cycleKey = getCycleKey(record, config);
            if (notifiedCyclesRef.current.has(cycleKey)) return;
            if (mutedCycles.has(cycleKey)) return;
            notifiedCyclesRef.current.add(cycleKey);
            showReminderNotification(record, config);
          });
        })
        .catch(() => null);
    };

    cleanupMutedCycles(config);
    const initTimer = setTimeout(fetchAndNotify, 2000);
    timerRef.current = setInterval(fetchAndNotify, POLL_INTERVAL);
    return () => {
      clearTimeout(initTimer);
      if (timerRef.current) clearInterval(timerRef.current);
      timerRef.current = null;
    };
  }, [config]);

  return null;
}

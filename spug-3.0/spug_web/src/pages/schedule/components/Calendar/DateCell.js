/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 日期单元格组件
 * 
 * 显示单个日期的排班信息，包括：
 * - 节假日标记
 * - 按班次分组的排班标签
 * - 换班/替班状态标识
 */
import React from 'react';
import { Tooltip } from 'antd';
import moment from 'moment';
import { getHolidayName } from '../../holidays';

/**
 * 排班标签组件
 */
const ScheduleTag = ({ schedule, isOutOfMonth }) => (
  <Tooltip
    title={
      <div>
        <div>人员: {schedule.staff_name}</div>
        <div>班次: {schedule.shift_name}</div>
        {schedule.isSwap && <div style={{ color: '#52c41a' }}>已换班</div>}
        {schedule.isSubstitute && <div style={{ color: '#fa8c16' }}>已替班</div>}
        {schedule.notes && <div>备注: {schedule.notes}</div>}
      </div>
    }
  >
    <div
      style={{
        backgroundColor: schedule.isSwap 
          ? '#95de64' 
          : (schedule.isSubstitute ? '#ffd591' : (schedule.shift_color || '#1890ff')),
        color: '#fff',
        padding: '2px 8px',
        borderRadius: '3px',
        fontSize: '12px',
        lineHeight: '1.5',
        whiteSpace: 'nowrap',
        minWidth: '60px',
        textAlign: 'center',
        boxSizing: 'border-box',
        boxShadow: '0 1px 2px rgba(0,0,0,0.1)',
        display: 'inline-block',
        opacity: isOutOfMonth ? 0.45 : 1
      }}
    >
      {schedule.staff_name}
    </div>
  </Tooltip>
);

/**
 * 班次分组组件
 */
const ShiftGroup = ({ group, isOutOfMonth }) => (
  <div
    style={{
      display: 'flex',
      flexDirection: 'row',
      gap: '3px',
      alignItems: 'center',
      flexWrap: 'wrap'
    }}
  >
    {group.schedules.map((schedule, index) => (
      <ScheduleTag 
        key={index} 
        schedule={schedule} 
        isOutOfMonth={isOutOfMonth} 
      />
    ))}
  </div>
);

/**
 * 节假日显示组件
 */
const HolidayDisplay = ({ holidayName }) => {
  if (!holidayName) return null;
  
  return (
    <div style={{
      fontSize: '12px',
      color: '#ff4d4f',
      fontWeight: 500,
      marginBottom: '4px',
      display: 'flex',
      alignItems: 'center',
      gap: '4px'
    }}>
      <span role="img" aria-label="节日" title="节日">🎉</span> {holidayName}
    </div>
  );
};

/**
 * 日期单元格主组件
 * 
 * @param {Object} props
 * @param {moment} props.value - 日期值
 * @param {Array} props.schedules - 该日期的排班列表
 * @param {moment} props.internalDate - 当前显示月份
 * @param {Function} props.onClick - 点击回调
 */
function DateCell({ value, schedules, internalDate, onClick }) {
  const dateStr = moment(value).format('YYYY-MM-DD');
  const holidayName = getHolidayName(value);
  const isOutOfMonth = value.month() !== internalDate.month();

  // 按班次分组
  const shiftGroups = {};
  schedules.forEach(schedule => {
    const shiftId = schedule.shift_id || 0;
    if (!shiftGroups[shiftId]) {
      shiftGroups[shiftId] = {
        shift_name: schedule.shift_name,
        shift_color: schedule.shift_color,
        schedules: []
      };
    }
    shiftGroups[shiftId].schedules.push(schedule);
  });

  const handleClick = (e) => {
    try {
      e.stopPropagation();
      if (onClick) {
        onClick(dateStr, schedules);
      }
    } catch (err) {
      console.error('Error in date cell onClick:', err);
    }
  };

  return (
    <div
      style={{
        width: '100%',
        height: 'auto',
        minHeight: '80px',
        cursor: 'pointer',
        position: 'relative',
        padding: '4px',
        boxSizing: 'border-box',
        backgroundColor: holidayName ? '#fff1f0' : 'transparent'
      }}
      onClick={handleClick}
    >
      <HolidayDisplay holidayName={holidayName} />
      
      {schedules.length === 0 ? (
        <span style={{ fontSize: '12px', color: '#999' }}></span>
      ) : (
        <div style={{
          pointerEvents: 'none',
          display: 'flex',
          flexDirection: 'column',
          gap: '3px',
          width: '100%',
          height: 'auto',
          overflow: 'visible'
        }}>
          {Object.values(shiftGroups).map((group, groupIndex) => (
            <ShiftGroup 
              key={groupIndex} 
              group={group} 
              isOutOfMonth={isOutOfMonth} 
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default DateCell;

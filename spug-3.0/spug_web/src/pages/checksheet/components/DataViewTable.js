/* eslint-disable indent */
/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Card } from 'antd';
import { STATUS_MAP } from '../constants';

const tableHeaderStyle = {
  border: '1px solid #d9d9d9',
  padding: '8px',
  fontWeight: 'bold',
  backgroundColor: '#fafafa'
};

const stickyHeaderStyle = {
  ...tableHeaderStyle,
  position: 'sticky',
  left: 0,
  zIndex: 10
};

const cellStyle = {
  border: '1px solid #d9d9d9',
  padding: '8px'
};

const stickyCellStyle = {
  ...cellStyle,
  position: 'sticky',
  left: 0,
  backgroundColor: '#fff',
  zIndex: 5
};

export default function DataViewTable({ viewData, days, selectedYear, selectedMonth }) {
  const getDailySummaryValue = (day, field) => {
    for (const project of Object.keys(viewData)) {
      const dailySummaries = viewData[project]?.daily_summaries;
      if (dailySummaries && dailySummaries[day]) {
        const value = dailySummaries[day][field];
        if (value) return value;
      }
    }
    return field === 'operator' ? '（待签字）' : '';
  };

  const renderTableHeader = () => (
    <tr style={{ backgroundColor: '#fafafa' }}>
      <th style={{ ...stickyHeaderStyle, minWidth: '100px' }}>项目</th>
      <th style={{ ...stickyHeaderStyle, minWidth: '150px', left: '100px' }}>检查项目</th>
      {days.map(day => (
        <th key={day} style={{ ...tableHeaderStyle, minWidth: '40px', textAlign: 'center' }}>{day}日</th>
      ))}
    </tr>
  );

  const renderTableBody = () => {
    const projects = Object.entries(viewData);
    return projects.map(([project, projectData], projectIndex) => {
      const checkItemsLength = projectData.template?.check_items?.length || 0;
      // P2-5 优化：预构建查找表，将 O(items × days × records) 降为 O(records) 查表
      const recordLookup = {};
      for (const record of (projectData.records || [])) {
        recordLookup[`${record.item_index}-${record.day}`] = record;
      }
      return (
        <React.Fragment key={project}>
          {projectData.template?.check_items?.map((item, itemIndex) => {
            const isFirstRow = itemIndex === 0;
            return (
              <tr key={`${project}-${itemIndex}`}>
                {isFirstRow && (
                  <td style={{ ...stickyCellStyle, textAlign: 'center', fontWeight: 'bold', verticalAlign: 'middle' }} rowSpan={checkItemsLength}>
                    {project}
                  </td>
                )}
                <td style={{ ...cellStyle, maxWidth: '200px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {item}
                </td>
                {days.map(day => {
                  const record = recordLookup[`${itemIndex}-${day}`];
                  const status = record?.status || 'UNCHECKED';
                  const statusInfo = STATUS_MAP[status];
                  return (
                    <td
                      key={day}
                      style={{
                        ...cellStyle,
                        textAlign: 'center',
                        backgroundColor: statusInfo.bgColor,
                        color: statusInfo.color,
                        minWidth: '40px'
                      }}
                      title={record?.remark ? `${statusInfo.text}: ${record.remark}` : statusInfo.text}
                    >
                      <span style={{ fontWeight: 'bold' }}>{statusInfo.label}</span>
                      {record?.remark && <span role="img" aria-label="有备注" title={record.remark}>📝</span>}
                    </td>
                  );
                })}
              </tr>
            );
          })}
          {projectIndex < projects.length - 1 && (
            <tr>
              <td colSpan={days.length + 2} style={{ padding: '4px', backgroundColor: '#f0f0f0', borderBottom: '2px solid #d9d9d9' }}></td>
            </tr>
          )}
        </React.Fragment>
      );
    });
  };

  const renderSummaryRow = (title, field) => (
    <tr>
      <td colSpan={2} style={{ ...cellStyle, backgroundColor: '#fafafa', fontWeight: 'bold', textAlign: 'center', verticalAlign: 'top' }}>
        {title}
      </td>
      {days.map(day => (
        <td
          key={`${field}-${day}`}
          style={{ ...cellStyle, fontSize: '11px', verticalAlign: field === 'operator' ? 'middle' : 'top', textAlign: field === 'operator' ? 'center' : 'left' }}
          title={getDailySummaryValue(day, field)}
        >
          {getDailySummaryValue(day, field)}
        </td>
      ))}
    </tr>
  );

  return (
    <Card title={`${selectedYear}年${selectedMonth}月 全部项目检查表`} size="small">
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', border: '1px solid #d9d9d9', fontSize: '12px' }}>
          <thead>{renderTableHeader()}</thead>
          <tbody>{renderTableBody()}</tbody>
          <tbody>{renderSummaryRow('发现问题及整改情况', 'rectification')}</tbody>
          <tbody>{renderSummaryRow('值班人员签名', 'operator')}</tbody>
          <tbody>{renderSummaryRow('备注', 'remark')}</tbody>
        </table>
      </div>

      <div style={{ marginTop: 16, textAlign: 'center' }}>
        <div style={{ display: 'inline-block', backgroundColor: '#fafafa', padding: '16px', borderRadius: '4px', border: '1px solid #d9d9d9' }}>
          <div>
            <strong>图例说明：</strong>
            <span style={{ marginLeft: 20 }}>
              <span style={{ color: '#52c41a', fontWeight: 'bold' }}>√</span> 正常
            </span>
            <span style={{ marginLeft: 20 }}>
              <span style={{ color: '#ff4d4f', fontWeight: 'bold' }}>×</span> 异常（📝表示有备注）
            </span>
            <span style={{ marginLeft: 20 }}>
              <span style={{ color: '#d9d9d9', fontWeight: 'bold' }}>—</span> 未检查
            </span>
          </div>
        </div>
      </div>
    </Card>
  );
}

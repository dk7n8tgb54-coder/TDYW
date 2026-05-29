/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { Select, Button, Row, Col } from 'antd';

const { Option } = Select;

export default function QueryControls({
  years,
  months,
  selectedYear,
  selectedMonth,
  onYearChange,
  onMonthChange,
  onQuery,
  onExport
}) {
  return (
    <Row gutter={16} style={{ marginBottom: 16 }}>
      <Col span={2}>
        <Select style={{ width: '100%' }} value={selectedYear} onChange={onYearChange}>
          {years.map(year => <Option key={year} value={year}>{year}年</Option>)}
        </Select>
      </Col>
      <Col span={2}>
        <Select style={{ width: '100%' }} value={selectedMonth} onChange={onMonthChange}>
          {months.map(month => <Option key={month} value={month}>{month}月</Option>)}
        </Select>
      </Col>
      <Col span={2}>
        <Button type="primary" onClick={onQuery}>查询全部</Button>
      </Col>
      <Col span={2}>
        <Button onClick={onExport}>导出PDF</Button>
      </Col>
    </Row>
  );
}

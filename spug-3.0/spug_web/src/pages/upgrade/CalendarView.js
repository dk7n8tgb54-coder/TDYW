/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState, useEffect } from 'react';
import { observer } from 'mobx-react';
import { Calendar, Badge, Card, Modal, Tag, Select, DatePicker, Button, Tooltip, Row, Col } from 'antd';
import { LeftOutlined, RightOutlined, UnorderedListOutlined } from '@ant-design/icons';
import { http, hasPermission } from 'libs';
import moment from 'moment';
import store from './store';
import StatusTag from './components/StatusTag';

const { Option } = Select;

const STATUS_COLOR_MAP = {
  '处理中': 'processing',
  '已完成': 'success',
};

export default observer(function () {
  const [currentMonth, setCurrentMonth] = useState(moment());
  const [recordsByDate, setRecordsByDate] = useState({});
  const [loading, setLoading] = useState(false);
  const [detailVisible, setDetailVisible] = useState(false);
  const [selectedDate, setSelectedDate] = useState(null);
  const [selectedRecords, setSelectedRecords] = useState([]);

  function fetchCalendarData() {
    setLoading(true);
    const startDate = currentMonth.clone().startOf('month').format('YYYY-MM-DD');
    const endDate = currentMonth.clone().endOf('month').format('YYYY-MM-DD');

    const params = {
      page: 1,
      page_size: 999,
      start_date: startDate,
      end_date: endDate,
    };
    if (store.f_system) params.system = store.f_system;
    if (store.f_status) params.status = store.f_status;
    if (store.f_upgrade_type) params.upgrade_type = store.f_upgrade_type;

    http.get('/api/upgrade/records/', { params })
      .then(data => {
        // 按日期分组
        const grouped = {};
        (data.records || []).forEach(record => {
          const date = (record.upgrade_time || '').split(' ')[0];
          if (!date) return;
          if (!grouped[date]) grouped[date] = [];
          grouped[date].push(record);
        });
        setRecordsByDate(grouped);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    fetchCalendarData();
  }, [currentMonth, store.f_system, store.f_status, store.f_upgrade_type]);

  function dateCellRender(date) {
    const dateStr = date.format('YYYY-MM-DD');
    const records = recordsByDate[dateStr] || [];
    if (records.length === 0) return null;

    return (
      <div style={{ padding: '0 4px' }}>
        {records.slice(0, 3).map(record => (
          <div
            key={record.id}
            style={{
              fontSize: 12,
              marginBottom: 2,
              cursor: 'pointer',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              padding: '1px 4px',
              borderRadius: 2,
              backgroundColor: record.status === '已完成' ? '#f6ffed'
                : record.status === '处理中' ? '#e6f7ff'
                : '#fff7e6',
            }}
            onClick={(e) => {
              e.stopPropagation();
              setSelectedDate(dateStr);
              setSelectedRecords(records);
              setDetailVisible(true);
            }}
          >
            <Badge status={STATUS_COLOR_MAP[record.status] || 'default'} />
            {record.upgrade_no?.slice(-5)} {record.system}
          </div>
        ))}
        {records.length > 3 && (
          <div style={{ fontSize: 11, color: '#999', textAlign: 'center' }}>
            +{records.length - 3} 更多
          </div>
        )}
      </div>
    );
  }

  function monthCellRender(date) {
    const monthStr = date.format('YYYY-MM');
    let count = 0;
    Object.keys(recordsByDate).forEach(key => {
      if (key.startsWith(monthStr)) {
        count += recordsByDate[key].length;
      }
    });
    if (count === 0) return null;
    return (
      <div style={{ textAlign: 'center' }}>
        <Badge count={count} style={{ backgroundColor: '#1890ff' }} />
        <span style={{ marginLeft: 8 }}>次升级</span>
      </div>
    );
  }

  function handlePanelChange(date) {
    setCurrentMonth(date);
  }

  function handleSelect(date) {
    const dateStr = date.format('YYYY-MM-DD');
    const records = recordsByDate[dateStr] || [];
    if (records.length > 0) {
      setSelectedDate(dateStr);
      setSelectedRecords(records);
      setDetailVisible(true);
    }
  }

  return (
    <div>
      {/* 日历顶部工具栏 */}
      <Card size="small" style={{ marginBottom: 12 }}>
        <Row gutter={16} align="middle">
          <Col>
            <Button.Group>
              <Button
                icon={<LeftOutlined />}
                onClick={() => setCurrentMonth(currentMonth.clone().subtract(1, 'month'))}
              />
              <Button onClick={() => setCurrentMonth(moment())}>
                今天
              </Button>
              <Button
                icon={<RightOutlined />}
                onClick={() => setCurrentMonth(currentMonth.clone().add(1, 'month'))}
              />
            </Button.Group>
            <span style={{ marginLeft: 12, fontWeight: 'bold', fontSize: 16 }}>
              {currentMonth.format('YYYY年MM月')}
            </span>
          </Col>
          <Col flex="auto" />
          <Col>
            <Select
              allowClear
              placeholder="系统"
              style={{ width: 140, marginRight: 8 }}
              value={store.f_system}
              onChange={v => { store.f_system = v; }}
            >
              {store.filterOptions.systems.map(item => (
                <Option value={item} key={item}>{item}</Option>
              ))}
            </Select>
            <Select
              allowClear
              placeholder="状态"
              style={{ width: 120, marginRight: 8 }}
              value={store.f_status}
              onChange={v => { store.f_status = v; }}
            >
              <Option value="处理中">处理中</Option>
              <Option value="已完成">已完成</Option>
            </Select>
            <Button
              icon={<UnorderedListOutlined />}
              onClick={() => store.viewMode = 'list'}
              title="切换到列表视图"
            >
              列表视图
            </Button>
          </Col>
        </Row>
      </Card>

      {/* 日历主体 */}
      <Card bodyStyle={{ padding: 0 }}>
        <Calendar
          value={currentMonth}
          onPanelChange={handlePanelChange}
          onSelect={handleSelect}
          dateCellRender={dateCellRender}
          monthCellRender={monthCellRender}
        />
      </Card>

      {/* 日期详情弹窗 */}
      <Modal
        visible={detailVisible}
        title={`${selectedDate} 升级计划`}
        onCancel={() => setDetailVisible(false)}
        footer={[
          <Button key="close" onClick={() => setDetailVisible(false)}>关闭</Button>
        ]}
        width={700}
      >
        {selectedRecords.map(record => (
          <Card
            key={record.id}
            size="small"
            style={{ marginBottom: 8, cursor: 'pointer' }}
            onClick={() => {
              setDetailVisible(false);
              store.showDetail(record);
            }}
          >
            <Row gutter={16}>
              <Col span={8}>
                <div><strong>升级单号</strong></div>
                <div>{record.upgrade_no}</div>
              </Col>
              <Col span={4}>
                <div><strong>系统</strong></div>
                <div>{record.system}</div>
              </Col>
              <Col span={4}>
                <div><strong>版本</strong></div>
                <div>{record.version}</div>
              </Col>
              <Col span={4}>
                <div><strong>负责人</strong></div>
                <div>{record.owner}</div>
              </Col>
              <Col span={4}>
                <div><strong>状态</strong></div>
                <div><StatusTag status={record.status} /></div>
              </Col>
            </Row>
          </Card>
        ))}
        {selectedRecords.length === 0 && (
          <div style={{ textAlign: 'center', color: '#999', padding: 24 }}>该日期无升级计划</div>
        )}
      </Modal>
    </div>
  );
})

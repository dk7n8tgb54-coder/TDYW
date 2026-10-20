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
import history from 'libs/history';
import moment from 'moment';
import store from './store';
import StatusTag from './components/StatusTag';

const { Option } = Select;

const STATUS_COLOR_MAP = {
  '处理中': 'processing',
  '已完成': 'success',
};

// 按日期分组：日历单元格渲染的数据源（键为 YYYY-MM-DD）
function groupRecordsByDate(records) {
  const grouped = {};
  (records || []).forEach(record => {
    const date = (record.upgrade_time || '').split(' ')[0];
    if (!date) return;
    if (!grouped[date]) grouped[date] = [];
    grouped[date].push(record);
  });
  return grouped;
}

// 日历单元格渲染工厂：每格最多显示 3 条记录，其余折叠为计数；
// 点击记录打开当日详情弹窗
function makeDateCellRender(recordsByDate, onOpenDay) {
  return function dateCellRender(date) {
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
              onOpenDay(dateStr, records);
            }}
          >
            <Badge status={STATUS_COLOR_MAP[record.status] || 'default'} />
            {record.title} {record.system_name}
          </div>
        ))}
        {records.length > 3 && (
          <div style={{ fontSize: 11, color: '#999', textAlign: 'center' }}>
            +{records.length - 3} 更多
          </div>
        )}
      </div>
    );
  };
}

// 月视图单元格渲染工厂：年面板按月汇总次数
function makeMonthCellRender(recordsByDate) {
  return function monthCellRender(date) {
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
  };
}

// 日历顶部工具栏：月份导航 + 快捷筛选（与顶部筛选栏共用同一组 f_* 条件，
// 变更回到第 1 页保持列表口径一致）
const CalendarToolbar = observer(function CalendarToolbar({currentMonth, onChangeMonth}) {
  return (
    <Card size="small" style={{ marginBottom: 12 }}>
      <Row gutter={16} align="middle">
        <Col>
          <Button.Group>
            <Button
              icon={<LeftOutlined />}
              onClick={() => onChangeMonth(currentMonth.clone().subtract(1, 'month'))}
            />
            <Button onClick={() => onChangeMonth(moment())}>
              今天
            </Button>
            <Button
              icon={<RightOutlined />}
              onClick={() => onChangeMonth(currentMonth.clone().add(1, 'month'))}
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
            onChange={v => { store.f_system = v; store.page = 1; }}
          >
            {store.filterOptions.systems.map(item => (
              <Option value={item.id} key={item.id}>{item.name}</Option>
            ))}
          </Select>
          <Select
            allowClear
            placeholder="状态"
            style={{ width: 120, marginRight: 8 }}
            value={store.f_status}
            onChange={v => { store.f_status = v; store.page = 1; }}
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
  );
});

// 日期详情弹窗：展示当日升级计划，点击单条进入工作台
function CalendarDetailModal({visible, selectedDate, selectedRecords, onClose}) {
  return (
    <Modal
      visible={visible}
      title={`${selectedDate} 升级计划`}
      onCancel={onClose}
      footer={[
        <Button key="close" onClick={onClose}>关闭</Button>
      ]}
      width={700}
    >
      {selectedRecords.map(record => (
        <Card
          key={record.id}
          size="small"
          style={{ marginBottom: 8, cursor: 'pointer' }}
          onClick={() => {
            onClose();
            history.push(`/upgrade/workbench/${record.id}`);
          }}
        >
          <Row gutter={16}>
            <Col span={8}>
              <div><strong>标题</strong></div>
              <div>{record.title}</div>
            </Col>
            <Col span={4}>
              <div><strong>系统</strong></div>
              <div>{record.system_name || '-'}</div>
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
  );
}

export default observer(function () {
  const [currentMonth, setCurrentMonth] = useState(moment());
  const [recordsByDate, setRecordsByDate] = useState({});
  const [loading, setLoading] = useState(false);
  const [detailVisible, setDetailVisible] = useState(false);
  const [selectedDate, setSelectedDate] = useState(null);
  const [selectedRecords, setSelectedRecords] = useState([]);

  // 日历取数（2026-10-20 核查统一筛选交互）：日期窗口由当前浏览月份决定
  // （翻月即切换窗口），顶部"计划升级时间"筛选只作用于列表视图、不参与
  // 日历取数——日历本身就是按月浏览时间的视图，若再叠加用户所选范围，
  // 会出现"所选月份内单元格被静默过滤为空"的困惑；系统/状态/升级类型
  // 条件与列表共用同一组 f_*，真实作用于日历取数。
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
        setRecordsByDate(groupRecordsByDate(data.records));
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    fetchCalendarData();
    // filterCommitSeq：查询/重置按钮的提交序号——下拉条件变更经上方依赖
    // 已触发重取；条件值未变化（或仅重置为空值）时依赖不变，靠该序号保证
    // 按钮提交对当前日历视图真实生效
  }, [currentMonth, store.f_system, store.f_status, store.f_upgrade_type, store.filterCommitSeq]);

  // 打开某日的详情弹窗（单元格记录与日历选中共用）
  function openDay(dateStr, records) {
    setSelectedDate(dateStr);
    setSelectedRecords(records);
    setDetailVisible(true);
  }

  function handleSelect(date) {
    const dateStr = date.format('YYYY-MM-DD');
    const records = recordsByDate[dateStr] || [];
    if (records.length > 0) {
      openDay(dateStr, records);
    }
  }

  return (
    <div>
      <CalendarToolbar currentMonth={currentMonth} onChangeMonth={setCurrentMonth}/>

      {/* 日历主体 */}
      <Card bodyStyle={{ padding: 0 }}>
        <Calendar
          value={currentMonth}
          onPanelChange={setCurrentMonth}
          onSelect={handleSelect}
          dateCellRender={makeDateCellRender(recordsByDate, openDay)}
          monthCellRender={makeMonthCellRender(recordsByDate)}
        />
      </Card>

      {/* 日期详情弹窗 */}
      <CalendarDetailModal
        visible={detailVisible}
        selectedDate={selectedDate}
        selectedRecords={selectedRecords}
        onClose={() => setDetailVisible(false)}
      />
    </div>
  );
})

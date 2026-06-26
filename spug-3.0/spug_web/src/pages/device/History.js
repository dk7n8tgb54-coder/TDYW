/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useState } from 'react';
import { observer } from 'mobx-react';
import { Card, Select, Tabs, Timeline, Tag, Descriptions, Collapse, Empty, Button } from 'antd';
import { SearchOutlined, FilePdfOutlined } from '@ant-design/icons';
import store from './HistoryStore';
import { EVENT_TYPE_MAP, getDeviceStatusConfig } from './constants';

const { TabPane } = Tabs;
const { Panel } = Collapse;

/**
 * 设备履历查看页面
 * 职责：选择设备后查看设备完整信息和事件时间线
 */

/**
 * 事件时间线子组件
 */
const EventTimeline = observer(function EventTimeline() {
  const [expandedEventId, setExpandedEventId] = useState(null);

  if (store.events.length === 0) {
    return <Empty description="暂无履历事件" />;
  }

  return (
    <Timeline mode="left">
      {store.events.map((event) => {
        const eventTypeInfo = EVENT_TYPE_MAP[event.event_type] || { text: '未知', color: '#999999', hex: '#999999' };
        const isExpanded = expandedEventId === event.id;

        return (
          <Timeline.Item
            key={event.id}
            color={eventTypeInfo.color}
            dot={<div style={{ width: 12, height: 12, borderRadius: '50%', backgroundColor: eventTypeInfo.color }} />}
          >
            <Card
              size="small"
              style={{ marginBottom: 8 }}
              bodyStyle={{ padding: '12px 16px' }}
            >
              <div style={{ marginBottom: 12 }}>
                <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
                  <span style={{ fontWeight: 500, marginRight: 8 }}>{event.event_time}</span>
                  <Tag color={eventTypeInfo.color}>{eventTypeInfo.text}</Tag>
                </div>
                <div style={{ fontSize: 14, color: '#333' }}>{event.event_title}</div>
                <div style={{ fontSize: 12, color: '#666', marginTop: 4 }}>
                  关联人：{event.related_user_name || '-'}
                </div>
                <span
                  onClick={() => setExpandedEventId(isExpanded ? null : event.id)}
                  style={{ fontSize: 12, color: '#1890ff', cursor: 'pointer' }}
                >
                  {isExpanded ? '收起详情' : '展开详情'}
                </span>
              </div>

              {isExpanded && (
                <div style={{ marginTop: 12, padding: '12px', backgroundColor: '#f5f5f5', borderRadius: 4 }}>
                  <Descriptions size="small" column={2}>
                    <Descriptions.Item label="事件类型">{eventTypeInfo.text}</Descriptions.Item>
                    <Descriptions.Item label="事件时间">{event.event_time}</Descriptions.Item>
                    <Descriptions.Item label="事件标题">{event.event_title}</Descriptions.Item>
                    <Descriptions.Item label="关联人">{event.related_user_name || '-'}</Descriptions.Item>
                    {event.fault_part && (
                      <Descriptions.Item label="故障件">{event.fault_part}</Descriptions.Item>
                    )}
                    {event.fault_phenomenon_cause && (
                      <Descriptions.Item label="故障现象及原因" span={2}>
                        {event.fault_phenomenon_cause}
                      </Descriptions.Item>
                    )}
                    {event.maintenance_measures && (
                      <Descriptions.Item label="检修措施" span={2}>
                        {event.maintenance_measures}
                      </Descriptions.Item>
                    )}
                    {event.repair_time && (
                      <Descriptions.Item label="修复时间">{event.repair_time}</Descriptions.Item>
                    )}
                    {event.remark && (
                      <Descriptions.Item label="备注" span={2}>
                        {event.remark}
                      </Descriptions.Item>
                    )}
                  </Descriptions>
                </div>
              )}
            </Card>
          </Timeline.Item>
        );
      })}
    </Timeline>
  );
});

/**
 * 设备基本信息子组件
 */
const DeviceInfo = observer(function DeviceInfo() {
  if (!store.deviceInfo) {
    return null;
  }

  const { deviceInfo } = store;
  const statusInfo = getDeviceStatusConfig(deviceInfo.current_status);

  return (
    <Card
      title="设备基础信息"
      style={{ marginBottom: 16 }}
      loading={store.isFetchingInfo}
    >
      <Collapse defaultActiveKey={['basic']} bordered={false}>
        <Panel header="基础信息" key="basic">
          <Descriptions column={2} size="small">
            <Descriptions.Item label="设备资产编号">{deviceInfo.device_sn}</Descriptions.Item>
            <Descriptions.Item label="设备名称">{deviceInfo.device_name}</Descriptions.Item>
            <Descriptions.Item label="设备型号">{deviceInfo.device_model}</Descriptions.Item>
            <Descriptions.Item label="工作频率">{deviceInfo.frequency || '-'}</Descriptions.Item>
            <Descriptions.Item label="设备呼号">{deviceInfo.call_sign || '-'}</Descriptions.Item>
            <Descriptions.Item label="安装地点">{deviceInfo.install_location}</Descriptions.Item>
            <Descriptions.Item label="当前设备状况">
              <Tag color={statusInfo.color}>{statusInfo.text}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="设备负责人">{deviceInfo.responsible_user_name}</Descriptions.Item>
            <Descriptions.Item label="安装时间">{deviceInfo.install_time}</Descriptions.Item>
            <Descriptions.Item label="启用时间">{deviceInfo.enable_time}</Descriptions.Item>
          </Descriptions>
        </Panel>

        <Panel header="扩展信息" key="extended">
          <Descriptions column={2} size="small">
            <Descriptions.Item label="安装经纬度">{deviceInfo.geo_coordinate || '-'}</Descriptions.Item>
            <Descriptions.Item label="设备用途">{deviceInfo.device_purpose || '-'}</Descriptions.Item>
            <Descriptions.Item label="生产厂家">{deviceInfo.manufacturer}</Descriptions.Item>
            <Descriptions.Item label="安装单位">{deviceInfo.install_unit}</Descriptions.Item>
            <Descriptions.Item label="使用单位">{deviceInfo.use_unit}</Descriptions.Item>
            <Descriptions.Item label="备注">{deviceInfo.remark || '-'}</Descriptions.Item>
            <Descriptions.Item label="档案创建时间">{deviceInfo.created_at}</Descriptions.Item>
            <Descriptions.Item label="最后更新时间">{deviceInfo.updated_at}</Descriptions.Item>
          </Descriptions>
        </Panel>
      </Collapse>
    </Card>
  );
});

export default observer(function DeviceHistoryView() {
  React.useEffect(() => {
    store.fetchDevices();
  }, []);

  return (
    <div style={{ padding: 24 }}>
      <Card title="设备履历查看" style={{ marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <span style={{ marginRight: 8 }}>选择设备：</span>
            <Select
              style={{ width: 400 }}
              placeholder="请选择设备"
              showSearch
              allowClear
              value={store.selectedDeviceId}
              onChange={store.selectDevice}
              loading={store.isFetchingDevices}
              filterOption={(input, option) =>
                option.props.children.toLowerCase().indexOf(input.toLowerCase()) >= 0
              }
            >
              {store.devices.map(device => (
                <Select.Option key={device.id} value={device.id}>
                  {device.device_sn} - {device.device_name}
                </Select.Option>
              ))}
            </Select>
          </div>
          {store.selectedDeviceId && (
            <Button
              type="primary"
              icon={<FilePdfOutlined />}
              loading={store.isExporting}
              onClick={store.exportPDF}
            >
              导出履历 PDF
            </Button>
          )}
        </div>
      </Card>

      {!store.selectedDeviceId && (
        <Card style={{ textAlign: 'center', padding: 60 }}>
          <SearchOutlined style={{ fontSize: 48, color: '#d9d9d9', marginBottom: 16 }} />
          <div style={{ fontSize: 16, color: '#999' }}>请选择一个设备查看其履历</div>
        </Card>
      )}

      {store.selectedDeviceId && (
        <>
          <DeviceInfo />
          <Card
            title="设备全生命周期履历"
            loading={store.isFetchingEvents}
          >
            <Tabs activeKey={store.eventTypeFilter} onChange={store.setEventTypeFilter}>
              <TabPane tab="全部事件" key="all">
                <EventTimeline />
              </TabPane>
              <TabPane tab="重大故障维修" key="1">
                <EventTimeline />
              </TabPane>
              <TabPane tab="设备更新" key="2">
                <EventTimeline />
              </TabPane>
              <TabPane tab="设备检修" key="3">
                <EventTimeline />
              </TabPane>
            </Tabs>
          </Card>
        </>
      )}
    </div>
  );
});

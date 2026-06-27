/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Modal, Descriptions, Tag, Button, Tabs, Collapse } from 'antd';
import { AuthButton } from 'components';
import EventTimeline from './EventTimeline';
import EventForm from './EventForm';
import store from './store';
import { getDeviceStatusConfig, EVENT_TYPE_MAP } from './constants';

const { Panel } = Collapse;

/**
 * 设备详情弹窗组件
 * 职责：展示设备完整信息和事件时间线，支持新增事件
 */
export default observer(function () {
  const record = store.record || {};
  const statusConfig = getDeviceStatusConfig(record.current_status);

  return (
    <Modal
      visible={store.detailVisible}
      title={`设备履历详情 - ${record.device_name || '-'}（${record.device_sn || '-'}）`}
      onCancel={() => store.detailVisible = false}
      width={1100}
      footer={null}
    >
      {/* 页面头部 */}
      <div style={{ marginBottom: 20, paddingBottom: 16, borderBottom: '1px solid #f0f0f0' }}>
        <h3 style={{ marginBottom: 8 }}>
          <span role="img" aria-label={statusConfig.aria} title={statusConfig.aria}>{statusConfig.icon}</span> {record.device_name || '-'} <Tag color={statusConfig.color}>{statusConfig.text}</Tag>
        </h3>
        <span style={{ color: '#999' }}>资产编号: {record.device_sn || '-'}</span>
      </div>

      {/* 设备基础信息卡片 */}
      <Collapse defaultActiveKey={['basic']} style={{ marginBottom: 16 }}>
        <Panel header="基础信息" key="basic">
          <Descriptions bordered column={2} size="small">
            <Descriptions.Item label="设备编号">{record.device_sn || '-'}</Descriptions.Item>
            <Descriptions.Item label="设备名称">{record.device_name || '-'}</Descriptions.Item>
            <Descriptions.Item label="设备型号">{record.device_model || '-'}</Descriptions.Item>
            <Descriptions.Item label="工作频率">{record.frequency || '-'}</Descriptions.Item>
            <Descriptions.Item label="设备呼号">{record.call_sign || '-'}</Descriptions.Item>
            <Descriptions.Item label="安装地点">{record.install_location || '-'}</Descriptions.Item>
          </Descriptions>
        </Panel>
        <Panel header="扩展信息" key="extended">
          <Descriptions bordered column={2} size="small">
            <Descriptions.Item label="设备用途" span={2}>{record.device_purpose || '-'}</Descriptions.Item>
            <Descriptions.Item label="安装经纬度" span={2}>{record.geo_coordinate || '-'}</Descriptions.Item>
            <Descriptions.Item label="备注" span={2}>{record.remark || '-'}</Descriptions.Item>
            <Descriptions.Item label="档案创建时间">{record.created_at || '-'}</Descriptions.Item>
            <Descriptions.Item label="最后更新时间">{record.updated_at || '-'}</Descriptions.Item>
          </Descriptions>
        </Panel>
        <Panel header="时间/单位信息" key="time-unit">
          <Descriptions bordered column={2} size="small">
            <Descriptions.Item label="生产厂家">{record.manufacturer || '-'}</Descriptions.Item>
            <Descriptions.Item label="安装单位">{record.install_unit || '-'}</Descriptions.Item>
            <Descriptions.Item label="使用单位">{record.use_unit || '-'}</Descriptions.Item>
            <Descriptions.Item label="设备负责人">{record.responsible_user_name || '-'}</Descriptions.Item>
            <Descriptions.Item label="安装时间">{record.install_time || '-'}</Descriptions.Item>
            <Descriptions.Item label="启用时间">{record.enable_time || '-'}</Descriptions.Item>
          </Descriptions>
        </Panel>
      </Collapse>

      {/* 全生命周期时间线 */}
      <div style={{ marginTop: 24 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
          <span style={{ fontWeight: 500, fontSize: 16 }}>全生命周期时间线</span>
          <div>
            <Button onClick={() => store.detailVisible = false}>返回列表</Button>
            <AuthButton auth="device.device_resume.history_add" type="primary" onClick={() => {
              EventForm.show(record);
            }} style={{ marginLeft: 8 }}>新增事件</AuthButton>
          </div>
        </div>
        <Tabs
          activeKey={store.eventTypeFilter === null ? 'all' : String(store.eventTypeFilter)}
          onChange={(type) => store.setEventTypeFilter(type, record.id)}
        >
          <Tabs.TabPane tab={`全部事件 (${store.eventTotal})`} key="all" />
          <Tabs.TabPane tab={EVENT_TYPE_MAP['1'].text} key="1" />
          <Tabs.TabPane tab={EVENT_TYPE_MAP['2'].text} key="2" />
          <Tabs.TabPane tab={EVENT_TYPE_MAP['3'].text} key="3" />
        </Tabs>
        <EventTimeline />
      </div>
      {store.eventFormVisible && <EventForm />}
    </Modal>
  );
})

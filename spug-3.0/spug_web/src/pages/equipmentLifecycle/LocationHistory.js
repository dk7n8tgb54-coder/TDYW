/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect } from 'react';
import { observer } from 'mobx-react';
import { Modal, Table } from 'antd';
import store from './store';

/**
 * 设备位置历史弹窗（只读，历史只进不出）。
 * 查看权限跟随页面整体的 equipment_lifecycle.device.view；
 * 数据请求在组件挂载时发起（组件本身已处于权限门内）。
 */
const columns = [
  { title: '变更后位置', dataIndex: 'new_location', ellipsis: true },
  { title: '变更前位置', dataIndex: 'old_location', width: 170, ellipsis: true, render: (v) => v || '（初始登记）' },
  { title: '生效时间', dataIndex: 'effective_at', width: 160, render: (v) => v || '-' },
  { title: '失效时间', dataIndex: 'ended_at', width: 160, render: (v) => v || '至今' },
  { title: '变更类型', dataIndex: 'change_type_text', width: 90 },
  { title: '变更原因', dataIndex: 'reason', width: 150, ellipsis: true, render: (v) => v || '-' },
  { title: '操作人', dataIndex: 'created_by_name', width: 100, render: (v) => v || '-' },
];

export default observer(function LocationHistory() {
  useEffect(() => {
    store.fetchLocationHistory();
  }, []);

  return (
    <Modal
      visible={store.locationHistoryVisible}
      title={`位置历史 - ${store.record.device_name || '-'}（${store.record.device_sn || '-'}）`}
      onCancel={store.closeLocationHistory}
      width={880}
      footer={null}
    >
      <Table
        size="small"
        loading={store.locationHistoryLoading}
        dataSource={store.locationHistory}
        rowKey="id"
        columns={columns}
        pagination={false}
      />
    </Modal>
  );
})

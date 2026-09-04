/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect } from 'react';
import { observer } from 'mobx-react';
import { Modal, Descriptions, Tag, Button, Table } from 'antd';
import { AuthDiv, AuthButton } from 'components';
import store from './store';
import { relationStore } from './systems/store';
import { getDeviceStatusConfig } from './constants';
import LocationHistory from './LocationHistory';
import LocationChangeForm from './LocationChangeForm';
import RelationForm from './systems/RelationForm';

/**
 * 设备视角的所属系统关系（多对多的设备侧视图）。
 * 由外层 AuthDiv 门控——无 relation.view 权限时不挂载、不发起请求。
 * 必须包 observer：本组件读取 deviceRelationsLoading/deviceRelations，
 * 否则请求完成后不会重渲染，表格会永远停留在加载态。
 * 挂载期间登记 deviceId 上下文：新增关系成功后 store 会联动刷新本列表。
 */
const DeviceRelationsSection = observer(function ({ deviceId }) {
  useEffect(() => {
    relationStore.deviceId = deviceId;
    relationStore.fetchDeviceRelations(deviceId);
    return () => {
      relationStore.deviceId = null;
      relationStore.deviceRelations = [];
      // 详情关闭时若关系表单仍开着，一并复位，避免残留可见状态
      relationStore.closeForm();
    };
  }, [deviceId]);

  const columns = [
    { title: '所属系统', dataIndex: 'system_name', width: 160 },
    { title: '关系角色', dataIndex: 'role_text', width: 90 },
    {
      title: '主要归属', dataIndex: 'is_primary', width: 80, align: 'center',
      render: (v) => v ? <Tag color="blue">是</Tag> : <Tag>否</Tag>,
    },
    { title: '生效日期', dataIndex: 'valid_from', width: 100 },
    { title: '失效日期', dataIndex: 'valid_to', width: 100, render: (v) => v || '长期' },
    {
      title: '状态', dataIndex: 'status_text', width: 80,
      render: (text, record) => (
        <Tag color={record.status === 'active' ? 'green' : 'default'}>{text}</Tag>
      )
    },
  ];

  return (
    <div style={{marginTop: 16}}>
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8}}>
        <span style={{fontWeight: 500}}>所属系统关系</span>
        <AuthButton auth="equipment_lifecycle.relation.manage" type="primary" size="small"
                    onClick={() => relationStore.showForm({})}>新增关系</AuthButton>
      </div>
      <Table
        size="small"
        loading={relationStore.deviceRelationsLoading}
        dataSource={relationStore.deviceRelations}
        rowKey="id"
        columns={columns}
        pagination={false}
      />
    </div>
  );
});

/**
 * 设备生命周期设备详情弹窗
 * 展示设备档案基础信息 + 当前所在位置 + 所属系统关系（需 relation.view 权限）；
 * 位置历史查看（device.view）与位置变更（device.manage，后端独立校验）入口；
 * 所属系统关系区块内 relation.manage 可直接新增关系（设备锁定，与系统详情页镜像）。
 */
export default observer(function () {
  const record = store.record || {};
  const statusConfig = getDeviceStatusConfig(record.current_status);

  return (
    <React.Fragment>
      <Modal
        visible={store.detailVisible}
        title={`设备详情 - ${record.device_name || '-'}（${record.device_sn || '-'}）`}
        onCancel={store.closeDetail}
        width={900}
        footer={<Button type="primary" onClick={store.closeDetail}>关闭</Button>}
      >
        <Descriptions bordered column={2} size="small" style={{marginBottom: 16}}>
          <Descriptions.Item label="设备编号">{record.device_sn || '-'}</Descriptions.Item>
          <Descriptions.Item label="设备名称">{record.device_name || '-'}</Descriptions.Item>
          <Descriptions.Item label="设备型号">{record.device_model || '-'}</Descriptions.Item>
          <Descriptions.Item label="当前设备状况">
            <Tag color={statusConfig.color}>{statusConfig.text}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="安装时间">{record.install_time || '-'}</Descriptions.Item>
          <Descriptions.Item label="启用时间">{record.enable_time || '-'}</Descriptions.Item>
          <Descriptions.Item label="当前所在位置" span={2}>
            {record.current_location || '-'}
          </Descriptions.Item>
          <Descriptions.Item label="备注" span={2}>{record.remark || '-'}</Descriptions.Item>
        </Descriptions>
        <div style={{marginBottom: 8}}>
          <Button style={{marginRight: 8}} onClick={store.showLocationHistory}>位置历史</Button>
          <AuthButton auth="equipment_lifecycle.device.manage" onClick={store.showLocationChange}>
            变更位置
          </AuthButton>
        </div>
        <AuthDiv auth="equipment_lifecycle.relation.view">
          <DeviceRelationsSection deviceId={record.id}/>
        </AuthDiv>
      </Modal>
      {store.locationHistoryVisible && <LocationHistory/>}
      {store.locationChangeVisible && <LocationChangeForm/>}
      {relationStore.formVisible && (
        <RelationForm systemSelectable deviceId={record.id}
                      deviceLabel={record.device_sn ? `${record.device_sn}（${record.device_name}）` : ''}/>
      )}
    </React.Fragment>
  );
})

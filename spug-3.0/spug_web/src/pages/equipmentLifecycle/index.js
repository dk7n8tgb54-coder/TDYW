/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { FilterBar, AuthDiv, Breadcrumb, AuthButton } from 'components';
import ComTable from './Table';
import DetailView from './DetailView';
import DeviceForm from './DeviceForm';
import store from './store';
import { DEVICE_STATUS_OPTIONS } from './constants';

/**
 * 设备生命周期 - 设备档案（独立主数据，与旧 device 模块无关）。
 * 权限：equipment_lifecycle.device.view 查看 / equipment_lifecycle.device.manage 维护。
 */
export default observer(function EquipmentLifecycle() {
  return (
    <AuthDiv auth="equipment_lifecycle.device.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>设备生命周期</Breadcrumb.Item>
        <Breadcrumb.Item>设备档案</Breadcrumb.Item>
      </Breadcrumb>
      <FilterBar
        store={store}
        fields={[
          { key: 'f_device_sn', label: '设备编号/名称', type: 'input', placeholder: '请输入' },
          { key: 'f_device_model', label: '设备型号', type: 'input', placeholder: '请输入' },
          { key: 'f_current_status', label: '当前设备状况', type: 'multipleSelect', options: DEVICE_STATUS_OPTIONS },
        ]}
        onSearch={store.fetchRecords}
        onReset={store.resetFilter}
      />
      <div style={{marginBottom: 16}}>
        <AuthButton auth="equipment_lifecycle.device.manage" type="primary"
                    onClick={() => store.showForm({})}>新增设备</AuthButton>
      </div>
      <ComTable/>
      {store.detailVisible && <DetailView/>}
      {store.formVisible && <DeviceForm/>}
    </AuthDiv>
  );
})

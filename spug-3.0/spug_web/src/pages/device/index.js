/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { FilterBar, AuthDiv, Breadcrumb } from 'components';
import ComTable from './Table';
import ComForm from './Form';
import DetailView from './DetailView';
import store from './store';

const statusOptions = [
  { value: '1', label: '正常' },
  { value: '2', label: '故障' },
  { value: '3', label: '维修中' },
  { value: '4', label: '停用' },
  { value: '5', label: '报废' },
];

export default observer(function DeviceResume() {
  return (
    <AuthDiv auth="device.device_resume.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>设备履历</Breadcrumb.Item>
      </Breadcrumb>
      <FilterBar
        store={store}
        fields={[
          { key: 'f_device_sn', label: '设备编号/名称', type: 'input', placeholder: '请输入' },
          { key: 'f_device_model', label: '设备型号', type: 'select', options: store.deviceModels },
          { key: 'f_current_status', label: '当前设备状况', type: 'multipleSelect', options: statusOptions },
          { key: 'f_use_unit', label: '使用单位', type: 'select', options: store.useUnits },
        ]}
        onSearch={store.fetchRecords}
        onReset={store.resetFilter}
      />
      <ComTable/>
      {store.formVisible && <ComForm/>}
      {store.detailVisible && <DetailView/>}
    </AuthDiv>
  );
})

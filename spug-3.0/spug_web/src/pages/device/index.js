/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Input, Select, Button } from 'antd';
import { SearchForm, AuthDiv, Breadcrumb } from 'components';
import ComTable from './Table';
import ComForm from './Form';
import DetailView from './DetailView';
import store from './store';

export default observer(function DeviceResume() {
  const [isMounted, setIsMounted] = React.useState(true);

  React.useEffect(() => {
    return () => {
      setIsMounted(false);
    };
  }, []);

  const handleQuery = React.useCallback(() => {
    if (isMounted) {
      store.fetchRecords();
    }
  }, [isMounted]);

  return (
    <AuthDiv auth="device.device_resume.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>设备履历</Breadcrumb.Item>
      </Breadcrumb>
      <SearchForm>
        <SearchForm.Item span={6} title="设备编号/名称">
          <Input allowClear value={store.f_device_sn} onChange={e => store.f_device_sn = e.target.value} placeholder="请输入"/>
        </SearchForm.Item>
        <SearchForm.Item span={6} title="设备型号">
          <Select
            allowClear
            value={store.f_device_model}
            onChange={v => store.f_device_model = v}
            placeholder="请选择"
            open={isMounted ? undefined : false}
          >
            {store.deviceModels.map(item => (
              <Select.Option key={item} value={item}>{item}</Select.Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={6} title="当前设备状况">
          <Select
            mode="multiple"
            allowClear
            value={store.f_current_status}
            onChange={v => store.f_current_status = v}
            placeholder="请选择"
            open={isMounted ? undefined : false}
          >
            <Select.Option value="1">正常</Select.Option>
            <Select.Option value="2">故障</Select.Option>
            <Select.Option value="3">维修中</Select.Option>
            <Select.Option value="4">停用</Select.Option>
            <Select.Option value="5">报废</Select.Option>
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={6} title="使用单位">
          <Select
            allowClear
            value={store.f_use_unit}
            onChange={v => store.f_use_unit = v}
            placeholder="请选择"
            open={isMounted ? undefined : false}
          >
            {store.useUnits.map(item => (
              <Select.Option key={item} value={item}>{item}</Select.Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={18}>
          <Button type="primary" onClick={handleQuery}>查询</Button>
          <Button onClick={store.resetFilter} style={{ marginLeft: 8 }}>重置</Button>
        </SearchForm.Item>
      </SearchForm>
      <ComTable/>
      {store.formVisible && <ComForm/>}
      {store.detailVisible && <DetailView/>}
    </AuthDiv>
  );
})

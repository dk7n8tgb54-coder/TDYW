import React, { useEffect } from 'react';
import { Breadcrumb, Input, Select } from 'antd';
import { AuthDiv } from 'components';
import { observer } from 'mobx-react';
import SearchForm from 'components/SearchForm';
import store from './store';
import ComTable from './Table';
import ComForm from './Form';

export default observer(function FaultPart() {
  useEffect(() => {
    store.fetchRecords();
  }, []);

  return (
    <AuthDiv auth="fault.faultpart.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>批量执行</Breadcrumb.Item>
        <Breadcrumb.Item>故障管理</Breadcrumb.Item>
        <Breadcrumb.Item>故障件管理</Breadcrumb.Item>
      </Breadcrumb>
      <SearchForm>
        <SearchForm.Item span={8} title="故障件名称">
          <Input 
            allowClear 
            value={store.f_name} 
            onChange={e => store.f_name = e.target.value} 
            placeholder="请输入故障件名称"
          />
        </SearchForm.Item>
        <SearchForm.Item span={8} title="所属系统">
          <Select 
            allowClear 
            value={store.f_system} 
            onChange={v => store.f_system = v} 
            placeholder="请选择所属系统"
          >
            {store.system_names.map(name => (
              <Select.Option key={name} value={name}>{name}</Select.Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={8} title="状态">
          <Select 
            allowClear 
            value={store.f_status} 
            onChange={v => store.f_status = v} 
            placeholder="请选择状态"
          >
            <Select.Option value="故障">故障</Select.Option>
            <Select.Option value="送修">送修</Select.Option>
            <Select.Option value="运回测试">运回测试</Select.Option>
            <Select.Option value="正常归档">正常归档</Select.Option>
          </Select>
        </SearchForm.Item>
      </SearchForm>
      <ComTable />
      {store.formVisible && <ComForm />}
    </AuthDiv>
  );
});

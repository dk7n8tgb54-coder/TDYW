/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Input, Select } from 'antd';
import { SearchForm, AuthDiv, Breadcrumb } from 'components';
import ComTable from './Table';
import ComForm from './Form';
import store from './store';

export default observer(function () {
  return (
    <AuthDiv auth="fault.faultrecord.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>故障管理</Breadcrumb.Item>
        <Breadcrumb.Item>故障处置记录</Breadcrumb.Item>
      </Breadcrumb>
      <SearchForm>
        <SearchForm.Item span={6} title="系统名称">
          <Select allowClear value={store.f_system_name} onChange={v => store.f_system_name = v} placeholder="请选择">
            {store.systemNames.map(item => (
              <Select.Option value={item} key={item}>{item}</Select.Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={6} title="日期">
          <Input allowClear value={store.f_fault_date} onChange={e => store.f_fault_date = e.target.value} placeholder="请输入"/>
        </SearchForm.Item>
        <SearchForm.Item span={6} title="处置人员">
          <Input allowClear value={store.f_handler} onChange={e => store.f_handler = e.target.value} placeholder="请输入"/>
        </SearchForm.Item>
        <SearchForm.Item span={6} title="故障评级">
          <Select allowClear value={store.f_fault_level} onChange={v => store.f_fault_level = v} placeholder="请选择">
            <Select.Option value="A">A</Select.Option>
            <Select.Option value="B">B</Select.Option>
            <Select.Option value="C">C</Select.Option>
          </Select>
        </SearchForm.Item>
      </SearchForm>
      <ComTable/>
      {store.formVisible && <ComForm/>}
    </AuthDiv>
  );
})

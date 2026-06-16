/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Input, Select, DatePicker } from 'antd';
import { SearchForm, AuthDiv, Breadcrumb } from 'components';
import ComTable from './Table';
import ComForm from './Form';
import store from './store';
import moment from 'moment';

function RadioLicense() {
  return (
    <AuthDiv auth="radio_license.license.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>无线电台执照</Breadcrumb.Item>
      </Breadcrumb>
      <SearchForm>
        <SearchForm.Item span={6} title="台站">
          <Input
            allowClear
            value={store.f_station_name}
            onChange={e => store.f_station_name = e.target.value}
            placeholder="请输入台站名称"
          />
        </SearchForm.Item>
        <SearchForm.Item span={6} title="用途">
          <Input
            allowClear
            value={store.f_purpose}
            onChange={e => store.f_purpose = e.target.value}
            placeholder="请输入用途关键字"
          />
        </SearchForm.Item>
        <SearchForm.Item span={6} title="状态">
          <Select
            allowClear
            value={store.f_status}
            onChange={v => store.f_status = v}
            placeholder="请选择状态"
          >
            {store.statusOptions.map(item => (
              <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={6} title="截止日期">
          <DatePicker.RangePicker
            allowClear
            value={store.f_valid_to_range
              ? [moment(store.f_valid_to_range[0]), moment(store.f_valid_to_range[1])]
              : null}
            onChange={(dates) => {
              if (dates && dates[0] && dates[1]) {
                store.f_valid_to_range = [
                  dates[0].format('YYYY-MM-DD'),
                  dates[1].format('YYYY-MM-DD')
                ];
              } else {
                store.f_valid_to_range = undefined;
              }
            }}
            placeholder={['开始日期', '结束日期']}
            style={{ width: '100%' }}
          />
        </SearchForm.Item>
      </SearchForm>
      <ComTable/>
      {store.formVisible && <ComForm/>}
      {store.detailVisible && <ComForm/>}
    </AuthDiv>
  );
}

export default observer(RadioLicense);

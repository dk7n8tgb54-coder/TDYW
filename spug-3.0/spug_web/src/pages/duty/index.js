/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Select, DatePicker, Breadcrumb } from 'antd';
import { SearchForm, AuthDiv } from 'components';
import ComTable from './Table';
import ComForm from './Form';
import ComDetail from './Detail';
import store from './store';

const { Option } = Select;

export default observer(function () {
  return (
    <AuthDiv auth="duty.duty.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>值班日志</Breadcrumb.Item>
      </Breadcrumb>
      <SearchForm>
        <SearchForm.Item span={6} title="值班人员">
          <Select allowClear value={store.f_duty_person} onChange={v => store.f_duty_person = v} placeholder="请选择值班人员">
            {store.dutyPersons.map(item => (
              <Option value={item} key={item}>{item}</Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={6} title="所属科室">
          <Select allowClear value={store.f_department} onChange={v => store.f_department = v} placeholder="请选择科室">
            {store.departments.map(item => (
              <Option value={item} key={item}>{item}</Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={6} title="日期范围">
          <DatePicker.RangePicker
            value={store.f_start_date && store.f_end_date ? [store.f_start_date, store.f_end_date] : null}
            onChange={(dates) => {
              store.f_start_date = dates ? dates[0].format('YYYY-MM-DD') : null;
              store.f_end_date = dates ? dates[1].format('YYYY-MM-DD') : null;
            }}
          />
        </SearchForm.Item>
      </SearchForm>
      <ComTable/>
      {store.formVisible && <ComForm/>}
      {store.detailVisible && <ComDetail/>}
    </AuthDiv>
  );
})

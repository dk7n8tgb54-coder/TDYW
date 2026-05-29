/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React, { useEffect } from 'react';
import { observer } from 'mobx-react';
import { Select, DatePicker, Breadcrumb, Button, Radio } from 'antd';
import { SearchForm, AuthDiv } from 'components';
import { CalendarOutlined, UnorderedListOutlined } from '@ant-design/icons';
import ComTable from './Table';
import CalendarView from './CalendarView';
import RecordForm from './RecordForm';
import store from './store';

const { Option } = Select;

export default observer(function () {
  useEffect(() => {
    store.fetchFilterOptions();
  }, []);

  return (
    <AuthDiv auth="upgrade.upgrade.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>系统升级管理</Breadcrumb.Item>
        <Breadcrumb.Item>升级表单</Breadcrumb.Item>
      </Breadcrumb>
      <SearchForm>
        <SearchForm.Item span={6} title="系统">
          <Select allowClear value={store.f_system} onChange={v => { store.f_system = v; store.page = 1; store.fetchRecords(); }} placeholder="请选择系统">
            {store.filterOptions.systems.map(item => (
              <Option value={item} key={item}>{item}</Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={6} title="状态">
          <Select allowClear value={store.f_status} onChange={v => { store.f_status = v; store.page = 1; store.fetchRecords(); }} placeholder="请选择状态">
            {store.filterOptions.statuses.map(item => (
              <Option value={item} key={item}>{item}</Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={6} title="升级类型">
          <Select allowClear value={store.f_upgrade_type} onChange={v => { store.f_upgrade_type = v; store.page = 1; store.fetchRecords(); }} placeholder="请选择升级类型">
            {store.filterOptions.upgradeTypes.map(item => (
              <Option value={item} key={item}>{item}</Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={6} title="时间范围">
          <DatePicker.RangePicker
            value={store.f_start_date && store.f_end_date ? [store.f_start_date, store.f_end_date] : null}
            onChange={(dates) => {
              store.f_start_date = dates ? dates[0].format('YYYY-MM-DD') : null;
              store.f_end_date = dates ? dates[1].format('YYYY-MM-DD') : null;
              store.page = 1;
              store.fetchRecords();
            }}
          />
        </SearchForm.Item>
      </SearchForm>
      {/* 视图切换 */}
      <div style={{ marginBottom: 12, textAlign: 'right' }}>
        <Radio.Group
          value={store.viewMode}
          onChange={e => store.viewMode = e.target.value}
          buttonStyle="solid"
          size="small"
        >
          <Radio.Button value="list">
            <UnorderedListOutlined /> 列表
          </Radio.Button>
          <Radio.Button value="calendar">
            <CalendarOutlined /> 日历
          </Radio.Button>
        </Radio.Group>
      </div>
      {store.viewMode === 'calendar' ? <CalendarView /> : <ComTable />}
      {store.formVisible && <RecordForm />}
    </AuthDiv>
  );
})

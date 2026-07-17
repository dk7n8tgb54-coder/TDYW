/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright: (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Input, Select, DatePicker, Button} from 'antd';
import {AuthDiv, Breadcrumb, SearchForm} from 'components';
import ComTable from './DepartmentDutyLogTable';
import ComForm from './DepartmentDutyLogForm';
import ComDetail from './DepartmentDutyLogDetail';
import ComSignModal from './DepartmentDutyLogSignModal';
import {PlusOutlined} from '@ant-design/icons';
import store from './departmentDutyLogStore';

const {RangePicker} = DatePicker;

function DepartmentDutyLogIndex() {
  return (
    <AuthDiv auth="department_duty_log.department_duty_log.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>部门值班日志</Breadcrumb.Item>
      </Breadcrumb>

      <SearchForm>
        <SearchForm.Item span={6} title="日期范围">
          <RangePicker
            allowClear
            value={[store.f_start_date, store.f_end_date]}
            onChange={(dates) => {
              store.f_start_date = dates ? dates[0] : undefined;
              store.f_end_date = dates ? dates[1] : undefined;
            }}
            style={{width: '100%'}}
          />
        </SearchForm.Item>
        <SearchForm.Item span={5} title="值班员">
          <Input
            allowClear
            value={store.f_duty_person_name}
            onChange={e => store.f_duty_person_name = e.target.value}
            placeholder="值班员姓名"
            onPressEnter={() => {store.pageNum = 1; store.fetchRecords();}}
          />
        </SearchForm.Item>
        <SearchForm.Item span={4} title="状态">
          <Select
            allowClear
            value={store.f_status}
            onChange={v => {store.f_status = v; store.pageNum = 1; store.fetchRecords();}}
            placeholder="选择状态"
          >
            {store.statusOptions.map(item => (
              <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={5} title="关键字">
          <Input
            allowClear
            value={store.f_keyword}
            onChange={e => store.f_keyword = e.target.value}
            placeholder="值班记录/备注"
            onPressEnter={() => {store.pageNum = 1; store.fetchRecords();}}
          />
        </SearchForm.Item>
        <SearchForm.Item span={24}>
          <Button type="primary" onClick={() => {store.pageNum = 1; store.fetchRecords();}}>查询</Button>
          <Button style={{marginLeft: 8}} onClick={() => {
            store.f_start_date = undefined;
            store.f_end_date = undefined;
            store.f_duty_person_name = undefined;
            store.f_status = undefined;
            store.f_keyword = undefined;
            store.pageNum = 1;
            store.fetchRecords();
          }}>重置</Button>
        </SearchForm.Item>
      </SearchForm>

      <div style={{marginBottom: 16}}>
        <Button type="primary" icon={<PlusOutlined/>}
          onClick={() => store.showForm(null)}
        >新建值班日志</Button>
      </div>

      <ComTable/>

      {store.formVisible && <ComForm/>}
      {store.detailVisible && <ComDetail/>}
      {store.signVisible && <ComSignModal/>}
    </AuthDiv>
  );
}

export default observer(DepartmentDutyLogIndex);

/**
 * 台站频率批复页面入口。
 *
 * 设计方案 9.1：
 * - 查询区：文件名称、文件编号、状态、截止日期范围
 * - 列表 + 表单（新增/编辑/详情三态）
 * - ?id= 深链由 Table 加载详情
 * - 权限控制：radio_license.approval.view
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Input, Select, DatePicker, Button } from 'antd';
import { SearchForm, AuthDiv, Breadcrumb } from 'components';
import ComTable from './Table';
import ComForm from './Form';
import store from './store';
import moment from 'moment';

function StationFrequencyApproval({ location }) {
  return (
    <AuthDiv auth="radio_license.approval.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>台站频率批复</Breadcrumb.Item>
      </Breadcrumb>
      <SearchForm>
        <SearchForm.Item span={6} title="文件名称">
          <Input
            allowClear
            value={store.f_name}
            onChange={e => store.f_name = e.target.value}
            placeholder="请输入文件名称"
            onPressEnter={() => {store.pageNum = 1; store.fetchRecords();}}
          />
        </SearchForm.Item>
        <SearchForm.Item span={6} title="文件编号">
          <Input
            allowClear
            value={store.f_doc_no}
            onChange={e => store.f_doc_no = e.target.value}
            placeholder="请输入文件编号"
            onPressEnter={() => {store.pageNum = 1; store.fetchRecords();}}
          />
        </SearchForm.Item>
        <SearchForm.Item span={6} title="状态">
          <Select
            allowClear
            value={store.f_status}
            onChange={v => {store.f_status = v; store.pageNum = 1; store.fetchRecords();}}
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
        <SearchForm.Item span={24}>
          <Button type="primary" onClick={() => {store.pageNum = 1; store.fetchRecords();}}>查询</Button>
          <Button style={{marginLeft: 8}} onClick={() => {
            store.f_name = undefined;
            store.f_doc_no = undefined;
            store.f_status = undefined;
            store.f_valid_to_range = undefined;
            store.pageNum = 1;
            store.fetchRecords();
          }}>重置</Button>
        </SearchForm.Item>
      </SearchForm>
      <ComTable location={location} />
      {store.formVisible && <ComForm />}
      {store.detailVisible && <ComForm />}
    </AuthDiv>
  );
}

export default observer(StationFrequencyApproval);

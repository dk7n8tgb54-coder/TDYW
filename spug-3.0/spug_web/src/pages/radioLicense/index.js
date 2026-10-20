/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Input, Select, DatePicker } from 'antd';
import {SearchForm, AuthDiv} from 'components';
import ComTable from './Table';
import ComForm from './Form';
import store from './store';
import moment from 'moment';

/**
 * 筛选区（2026-10-20 统一交互，参照运行处置记录 RecordFilters）：
 * 常驻 台站/用途（草稿，查询/回车提交）/状态，截止日期收入"更多筛选"；
 * 状态与截止日期变更即查询但不代提交文本草稿；重置清空全部条件及草稿
 * 并回到第 1 页；展开收起本身不触发请求，收起时显示折叠区已启用条件
 * 数量（日期范围按一个条件计数）。
 */
function RadioLicense() {
  const [advancedOpen, setAdvancedOpen] = React.useState(false);
  const advancedCount = [
    store.f_valid_to_range && store.f_valid_to_range.length === 2,
  ].filter(Boolean).length;
  return (
    <AuthDiv auth="radio_license.license.view">
      <SearchForm>
        <SearchForm.Item span={6} title="台站">
          <Input
            allowClear
            value={store.input_station_name}
            onChange={e => store.setStationNameInput(e.target.value)}
            placeholder="请输入台站名称"
            onPressEnter={() => store.commitFilters()}
          />
        </SearchForm.Item>
        <SearchForm.Item span={6} title="用途">
          <Input
            allowClear
            value={store.input_purpose}
            onChange={e => store.setPurposeInput(e.target.value)}
            placeholder="请输入用途关键字"
            onPressEnter={() => store.commitFilters()}
          />
        </SearchForm.Item>
        <SearchForm.Item span={4} title="状态">
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
        <SearchForm.Actions
          onSearch={() => store.commitFilters()}
          onReset={() => {store.resetFilter(); store.fetchRecords();}}
          advancedOpen={advancedOpen}
          advancedCount={advancedCount}
          onToggleAdvanced={() => setAdvancedOpen(!advancedOpen)}
        />
        {advancedOpen && (
          <SearchForm.Item span={8} title="截止日期">
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
                store.pageNum = 1;
                store.fetchRecords();
              }}
              placeholder={['开始日期', '结束日期']}
              style={{ width: '100%' }}
            />
          </SearchForm.Item>
        )}
      </SearchForm>
      <ComTable/>
      {store.formVisible && <ComForm/>}
      {store.detailVisible && <ComForm/>}
    </AuthDiv>
  );
}

export default observer(RadioLicense);

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

// 【优化】命名组件，便于 React DevTools 调试
function Interference() {
  const [isMounted, setIsMounted] = React.useState(true);

  React.useEffect(() => {
    return () => {
      setIsMounted(false);
    };
  }, []);

  return (
    <AuthDiv auth="interference.interference.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>干扰信息统计</Breadcrumb.Item>
      </Breadcrumb>
      <SearchForm>
        <SearchForm.Item span={6} title="汇报科室">
          <Select
            allowClear
            value={store.f_report_dept}
            onChange={v => store.f_report_dept = v}
            placeholder="请选择"
            open={isMounted ? undefined : false}
          >
            {store.reportDepts.map(item => (
              <Select.Option value={item} key={item}>{item}</Select.Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={6} title="日期时间">
          <DatePicker.RangePicker
            allowClear
            value={store.f_datetime ? [moment(store.f_datetime[0]), moment(store.f_datetime[1])] : null}
            onChange={(dates) => {
              if (dates && dates[0] && dates[1]) {
                store.f_datetime = [
                  dates[0].format('YYYY-MM-DD'),
                  dates[1].format('YYYY-MM-DD')
                ];
              } else {
                store.f_datetime = [];
              }
            }}
            placeholder={['开始日期', '结束日期']}
            style={{ width: '100%' }}
            open={isMounted ? undefined : false}
          />
        </SearchForm.Item>
        <SearchForm.Item span={6} title="干扰类型">
          <Select
            allowClear
            value={store.f_interference_type}
            onChange={v => store.f_interference_type = v}
            placeholder="请选择"
            open={isMounted ? undefined : false}
          >
            {store.interferenceTypes.map(item => (
              <Select.Option value={item} key={item}>{item}</Select.Option>
            ))}
          </Select>
        </SearchForm.Item>
        <SearchForm.Item span={6} title="现象">
          <Input allowClear value={store.f_phenomenon} onChange={e => store.f_phenomenon = e.target.value} placeholder="请输入关键字"/>
        </SearchForm.Item>
      </SearchForm>
      <ComTable/>
      {store.formVisible && <ComForm/>}
    </AuthDiv>
  );
}

export default observer(Interference);

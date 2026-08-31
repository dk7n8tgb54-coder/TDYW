/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { FilterBar, AuthDiv, Breadcrumb } from 'components';
import ComTable from './Table';
import ComForm from './Form';
import store from './store';

function AirInterference() {
  return (
    <AuthDiv auth="interference.interference.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>干扰管理</Breadcrumb.Item>
        <Breadcrumb.Item>空中干扰</Breadcrumb.Item>
      </Breadcrumb>
      <FilterBar
        store={store}
        fields={[
          { key: 'f_flight_number', label: '航班号', type: 'input', placeholder: '请输入航班号' },
          { key: 'f_datetime', label: '日期时间', type: 'dateRange' },
        ]}
        beforeSearch={() => { store.pageNum = 1; }}
        onSearch={store.fetchRecords}
        onReset={store.resetFilter}
      />
      <ComTable/>
      {store.formVisible && <ComForm/>}
    </AuthDiv>
  );
}

export default observer(AirInterference);

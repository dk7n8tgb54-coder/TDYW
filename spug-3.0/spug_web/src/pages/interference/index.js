/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { FilterBar, AuthDiv, Breadcrumb } from 'components';
import ComTable from './Table';
import ComForm from './Form';
import store from './store';

// 【优化】命名组件，便于 React DevTools 调试
function Interference() {
  return (
    <AuthDiv auth="interference.interference.view">
      <Breadcrumb>
        <Breadcrumb.Item>首页</Breadcrumb.Item>
        <Breadcrumb.Item>干扰信息统计</Breadcrumb.Item>
      </Breadcrumb>
      <FilterBar
        store={store}
        fields={[
          { key: 'f_frequency', label: '频率', type: 'input', placeholder: '请输入频率' },
          { key: 'f_report_dept', label: '汇报科室', type: 'select', options: store.reportDepts },
          { key: 'f_datetime', label: '日期时间', type: 'dateRange' },
          { key: 'f_interference_type', label: '干扰类型', type: 'select', options: store.interferenceTypes },
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

export default observer(Interference);

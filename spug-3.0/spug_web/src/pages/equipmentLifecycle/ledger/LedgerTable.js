/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运维台账分页表格（antd Table，与模块内表格风格一致）。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {Table} from 'antd';

function LedgerTable({store, columns}) {
  return (
    <Table
      rowKey="id"
      loading={store.isFetching}
      dataSource={store.records}
      columns={columns}
      pagination={{
        current: store.page,
        pageSize: store.pageSize,
        total: store.total,
        showSizeChanger: false,
        onChange: page => {
          store.page = page;
          store.fetchRecords();
        },
      }}
    />
  );
}

export default observer(LedgerTable);

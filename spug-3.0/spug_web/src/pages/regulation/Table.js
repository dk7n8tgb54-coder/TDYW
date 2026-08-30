/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Table, Tag, Modal, message } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { http } from 'libs';
import { Action, TableCard, AuthButton } from 'components';
import store from './store';

const STATUS_TAG_MAP = {
  active: { color: 'green', text: '现行' },
  retired: { color: 'red', text: '已废止' },
};

@observer
class ComTable extends React.Component {
  componentDidMount() {
    store.fetchRecords();
  }

  handleDelete = (record) => {
    Modal.confirm({
      title: '删除确认',
      content: `确定要删除规章【${record.title}】吗？`,
      onOk: () => {
        return http.delete(`/api/regulation/${record.id}/`)
          .then(() => {
            message.success('删除成功');
            store.fetchRecords();
          });
      },
    });
  };

  handleRetire = (record) => {
    Modal.confirm({
      title: '废止确认',
      content: `确定要废止规章【${record.title}】吗？`,
      onOk: () => {
        return http.post(`/api/regulation/${record.id}/retire/`)
          .then(() => {
            message.success('废止成功');
            store.fetchRecords();
          });
      },
    });
  };

  renderStatus = (status) => {
    const tagInfo = STATUS_TAG_MAP[status] || STATUS_TAG_MAP.active;
    return <Tag color={tagInfo.color}>{tagInfo.text}</Tag>;
  };

  render() {
    return (
      <TableCard
        tKey="regulation"
        resizable
        title="规章列表"
        rowKey="id"
        loading={store.isFetching}
        dataSource={store.records}
        onReload={store.fetchRecords}
        onRow={record => ({
          onDoubleClick: () => store.showDetail(record),
          style: { cursor: 'pointer' },
        })}
        actions={[
          <AuthButton
            auth="document.regulation.add"
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => store.showForm({})}
          >新建</AuthButton>,
        ]}
        pagination={{
          current: store.pageNum,
          pageSize: store.pageSize,
          total: store.total,
          showSizeChanger: true,
          showLessItems: true,
          showTotal: total => `共 ${total} 条`,
          onChange: (page, pageSize) => {
            store.pageNum = page;
            store.pageSize = pageSize;
            store.fetchRecords();
          },
        }}
      >
        <Table.Column title="规章名称" dataIndex="title" width={200} ellipsis
          render={(text, record) => (
            <a onClick={() => store.showDetail(record)}>{text}</a>
          )}
        />
        <Table.Column title="规章编号" dataIndex="rule_no" width={140} ellipsis
          render={text => text || '-'}
        />
        <Table.Column title="发文单位" dataIndex="issuing_authority" width={180} ellipsis
          render={text => text || '-'}
        />
        <Table.Column title="业务类型" dataIndex="biz_type" width={120} ellipsis
          render={text => text || '-'}
        />
        <Table.Column title="状态" dataIndex="status" width={90}
          render={this.renderStatus}
        />
        <Table.Column title="生效日期" dataIndex="effective_date" width={110}
          render={text => text || '-'}
        />
        <Table.Column title="操作" width={180} fixed="right"
          render={(_, record) => (
            <Action>
              <Action.Button auth="document.regulation.view" onClick={() => store.showDetail(record)}>查看</Action.Button>
              {record.status !== 'retired' && (
                <Action.Button auth="document.regulation.edit" onClick={() => store.showForm(record)}>编辑</Action.Button>
              )}
              {record.status !== 'retired' && (
                <Action.Button auth="document.regulation.edit" onClick={() => this.handleRetire(record)}>废止</Action.Button>
              )}
              <Action.Button danger auth="document.regulation.delete" onClick={() => this.handleDelete(record)}>删除</Action.Button>
            </Action>
          )}
        />
      </TableCard>
    );
  }
}

export default ComTable;

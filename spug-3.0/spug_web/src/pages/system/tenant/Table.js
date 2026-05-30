/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { PlusOutlined } from '@ant-design/icons';
import { Button, Modal, message, Badge } from 'antd';
import { TableCard, Action } from 'components';
import http from 'libs/http';
import store from './store';

@observer
class ComTable extends React.Component {
  componentDidMount() {
    store.fetchRecords()
  }

  columns = [{
    title: '租户标识',
    dataIndex: 'id',
    width: 180,
  }, {
    title: '租户名称',
    dataIndex: 'name',
    width: 200,
  }, {
    title: '状态',
    dataIndex: 'is_active',
    width: 100,
    render: v => v ? <Badge status="success" text="启用"/> : <Badge status="default" text="禁用"/>
  }, {
    title: '描述',
    dataIndex: 'description',
  }, {
    title: '操作',
    width: 180,
    render: info => (
      <Action>
        <Action.Button auth="system.tenant.edit" onClick={() => this.handleToggle(info)}>
          {info['is_active'] ? '禁用' : '启用'}
        </Action.Button>
        <Action.Button auth="system.tenant.edit" onClick={() => store.showForm(info)}>编辑</Action.Button>
        <Action.Button auth="system.tenant.del" danger onClick={() => this.handleDelete(info)}>删除</Action.Button>
      </Action>
    )
  }];

  handleToggle = (text) => {
    Modal.confirm({
      title: '操作确认',
      content: `确定要${text['is_active'] ? '禁用' : '启用'}租户【${text['name']}】?`,
      onOk: () => {
        return http.patch('/api/account/tenant/', {
          id: text.id,
          is_active: !text['is_active']
        }).then(() => {
          message.success('操作成功');
          store.fetchRecords()
        })
      }
    })
  };

  handleDelete = (text) => {
    Modal.confirm({
      title: '删除确认',
      content: `确定要删除租户【${text['name']}】? 删除前请确保该租户下没有用户。`,
      okText: '删除',
      onOk: () => {
        return http.delete('/api/account/tenant/', {params: {id: text.id}})
          .then(() => {
            message.success('删除成功');
            store.fetchRecords()
          })
      }
    })
  };

  render() {
    return (
      <TableCard
        tKey="st"
        rowKey="id"
        title="租户列表"
        loading={store.isFetching}
        dataSource={store.records}
        onReload={store.fetchRecords}
        actions={[
          <Button type="primary" icon={<PlusOutlined/>} auth="system.tenant.add" onClick={() => store.showForm()}>新建租户</Button>,
        ]}
        pagination={{
          showSizeChanger: true,
          showLessItems: true,
          showTotal: total => `共 ${total} 条`,
          pageSizeOptions: ['10', '20', '50', '100']
        }}
        columns={this.columns}/>
    )
  }
}

export default ComTable

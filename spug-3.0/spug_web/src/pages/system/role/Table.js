/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Modal, Popover, Button, message, Tag, Tooltip } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { TableCard, AuthButton, Action } from 'components';
import RoleUsers from './RoleUsers';
import http from 'libs/http';
import store from './store';
import uStore from '../account/store';
import styles from './index.module.css';

@observer
class ComTable extends React.Component {
  componentDidMount() {
    store.fetchRecords()
    if (uStore.records.length === 0) {
      uStore.fetchRecords()
    }
  }

  columns = [{
    title: '角色名称',
    dataIndex: 'name',
  }, {
    title: '类型',
    width: 200,
    render: info => {
      const tags = [];
      // 归属：平台级（tenant_id 为空）或租户（tenant_id 非空）
      if (info.tenant_id) {
        tags.push(
          <Tooltip key="tenant" title={`租户：${info.tenant_id}`}>
            <Tag color="green">租户</Tag>
          </Tooltip>
        );
      } else {
        tags.push(<Tag color="blue" key="platform">平台级</Tag>);
      }
      // 系统内置角色
      if (info.is_system) {
        tags.push(<Tag color="orange" key="system">系统</Tag>);
      }
      // 全局管理员角色
      if (info.is_global_admin) {
        tags.push(<Tag color="red" key="global">全局管理员</Tag>);
      }
      return <span>{tags}</span>;
    }
  }, {
    title: '关联账户',
    render: info => info.used ? (
      <Popover overlayClassName={styles.roleUser} content={<RoleUsers id={info.id}/>}>
        <Button type="link">{info.used}</Button>
      </Popover>
    ) : <Button type="link" disabled>{info.used}</Button>
  }, {
    title: '描述信息',
    dataIndex: 'desc',
    ellipsis: true
  }, {
    title: '操作',
    width: 300,
    render: info => (
      <Action>
        <Action.Button auth="system.account.edit" onClick={() => store.showForm(info)}>编辑</Action.Button>
        <Action.Button auth="system.account.edit" onClick={() => store.showPagePerm(info)}>功能权限</Action.Button>
        <Action.Button auth="system.account.del" danger onClick={() => this.handleDelete(info)}>删除</Action.Button>
      </Action>
    )
  }];

  handleDelete = (text) => {
    Modal.confirm({
      title: '删除确认',
      content: `确定要删除角色【${text['name']}】?`,
      onOk: () => {
        return http.delete('/api/account/role/', {params: {id: text.id}})
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
        rowKey="id"
        title="角色列表"
        loading={store.isFetching}
        dataSource={store.dataSource}
        onReload={store.fetchRecords}
        actions={[
          <AuthButton type="primary" icon={<PlusOutlined/>} onClick={() => store.showForm()}>新建</AuthButton>
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

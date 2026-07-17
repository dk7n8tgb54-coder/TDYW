/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { ExclamationCircleOutlined, PlusOutlined, UndoOutlined } from '@ant-design/icons';
import { Form, Radio, Modal, Button, Badge, message, Input } from 'antd';
import { TableCard, Action } from 'components';
import http from 'libs/http';
import store from './store';
import rStore from '../role/store';

@observer
class ComTable extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      password: ''
    }
  }

  componentDidMount() {
    if (rStore.records.length === 0) {
      rStore.fetchRecords()
        .then(() => store.fetchRecords())
    } else {
      store.fetchRecords()
    }
  }

  columns = [{
    title: '登录名',
    dataIndex: 'username',
  }, {
    title: '姓名',
    dataIndex: 'nickname',
  }, {
    title: '所属租户',
    dataIndex: 'tenant_id',
  }, {
    title: '角色',
    dataIndex: 'role_ids',
    render: v => v.map(x => rStore.idMap[x]?.name).join(',')
  }, {
    title: '状态',
    render: text => {
      if (text['deleted_by_id']) {
        return <Badge status="error" text="已删除"/>;
      }
      return text['is_active'] ? <Badge status="success" text="正常"/> : <Badge status="default" text="禁用"/>
    }
  }, {
    title: '签名',
    key: 'signature',
    width: 110,
    render: info => {
      // 仅超管显示签名状态列
      if (!store.isSupper) return null;
      const s = info['signature_status'];
      if (s === 'active') return <Badge status="processing" text={`v${info['signature_version'] || ''}`}/>;
      if (s === 'disabled') return <Badge status="warning" text="已停用"/>;
      return <Badge status="default" text="未配置"/>;
    }
  }, {
    title: '最近登录',
    dataIndex: 'last_login'
  }, {
    title: '操作',
    render: info => {
      const isDeleted = !!(info['deleted_by_id']);
      if (isDeleted) {
        return (
          <Action>
            <Action.Button onClick={() => this.handleRestore(info)}>恢复</Action.Button>
          </Action>
        )
      }
      return (
        <Action>
          <Action.Button onClick={() => this.handleActive(info)}>
            {info['is_active'] ? '禁用' : '启用'}
          </Action.Button>
          <Action.Button onClick={() => store.showForm(info)}>编辑</Action.Button>
          <Action.Button onClick={() => this.handleReset(info)}>重置密码</Action.Button>
          <Action.Button danger onClick={() => this.handleDelete(info)}>删除</Action.Button>
          {store.isSupper && (
            <Action.Button onClick={() => store.showSignature(info)}>签名</Action.Button>
          )}
        </Action>
      )
    }
  }];

  handleActive = (text) => {
    Modal.confirm({
      title: '操作确认',
      content: `确定要${text['is_active'] ? '禁用' : '启用'}【${text['nickname']}】?`,
      onOk: () => {
        return http.patch(`/api/account/user/`, {id: text.id, is_active: !text['is_active']})
          .then(() => {
            message.success('操作成功');
            store.fetchRecords()
          })
      }
    })
  };

  handleReset = (info) => {
    Modal.confirm({
      icon: <ExclamationCircleOutlined/>,
      title: '重置登录密码',
      content: <Form layout="vertical" style={{marginTop: 24}}>
        <Form.Item required label="重置后的新密码" extra="至少8位，包含数字、小写和大写字母、特殊字符。">
          <Input.Password onChange={val => this.setState({password: val.target.value})}/>
        </Form.Item>
      </Form>,
      onOk: () => {
        return http.patch('/api/account/user/', {id: info.id, password: this.state.password})
          .then(() => message.success('重置成功', 0.5))
      },
    })
  };

  handleDelete = (text) => {
    Modal.confirm({
      title: '删除确认',
      content: `确定要删除【${text['nickname']}】? 删除后可通过"显示已删除"恢复。`,
      okText: '删除',
      onOk: () => {
        return http.delete('/api/account/user/', {params: {id: text.id}})
          .then(() => {
            message.success('删除成功');
            store.fetchRecords()
          })
      }
    })
  };

  handleRestore = (text) => {
    Modal.confirm({
      title: '恢复确认',
      content: `确定要恢复【${text['nickname']}】? 恢复后该账号可正常登录。`,
      okText: '恢复',
      onOk: () => {
        return http.post('/api/account/user/restore/', {id: text.id})
          .then(() => {
            message.success('恢复成功');
            store.fetchRecords()
          })
      }
    })
  };

  render() {
    // 非超管不显示签名列
    const cols = store.isSupper
      ? this.columns
      : this.columns.filter(c => c.key !== 'signature');
    return (
      <TableCard
        tKey="sa"
        rowKey="id"
        title="账户列表"
        loading={store.isFetching}
        dataSource={store.dataSource}
        onReload={store.fetchRecords}
        actions={[
          <Button type="primary" icon={<PlusOutlined/>} onClick={() => store.showForm()}>新建</Button>,
          <Radio.Group value={store.f_status} onChange={e => { store.f_status = e.target.value; store.fetchRecords(); }}>
            <Radio.Button value="">全部</Radio.Button>
            <Radio.Button value="true">正常</Radio.Button>
            <Radio.Button value="false">禁用</Radio.Button>
          </Radio.Group>,
          <Button
            icon={<UndoOutlined/>}
            type={store.f_show_deleted ? 'primary' : 'default'}
            onClick={() => { store.f_show_deleted = !store.f_show_deleted; store.fetchRecords(); }}>
            {store.f_show_deleted ? '返回正常列表' : '显示已删除'}
          </Button>
        ]}
        pagination={{
          showSizeChanger: true,
          showLessItems: true,
          showTotal: total => `共 ${total} 条`,
          pageSizeOptions: ['10', '20', '50', '100']
        }}
        columns={cols}/>
    )
  }
}

export default ComTable

/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Modal, Input, InputNumber, Button, Table, Switch, message } from 'antd';
import { http } from 'libs';
import store from './store';

@observer
class CategoryModal extends React.Component {
  state = {editingId: null, editingName: '', submitting: false};

  handleCreate = () => {
    const name = this.state.editingName.trim();
    if (!name) return message.warning('请输入类别名称');
    this.setState({submitting: true});
    http.post('/api/institution/categories/', {name, sort_order: 0})
      .then(() => {
        message.success('已添加');
        this.setState({editingName: '', editingId: null});
        store.fetchCategories();
      })
      .finally(() => this.setState({submitting: false}));
  };

  handleUpdate = (record, patch) => {
    const name = patch.name !== undefined ? patch.name : record.name;
    const is_active = patch.is_active !== undefined ? patch.is_active : record.is_active;
    if (!String(name).trim()) return message.warning('类别名称不能为空');
    http.put(`/api/institution/categories/${record.id}/`, {
      name: String(name).trim(), sort_order: record.sort_order || 0, is_active,
    }).then(() => {
      message.success('已保存');
      this.setState({editingId: null});
      store.fetchCategories();
    });
  };

  handleDelete = (record) => {
    http.delete(`/api/institution/categories/${record.id}/`)
      .then(() => {
        message.success('已删除');
        store.fetchCategories();
      });
  };

  columns = [
    {title: '类别名称', dataIndex: 'name', render: (v, record) => (
      this.state.editingId === record.id ? (
        <Input size="small" value={this.state.editingName}
          onChange={e => this.setState({editingName: e.target.value})}
          style={{width: 180}}/>
      ) : v
    )},
    {title: '手册数', dataIndex: 'manual_count', width: 80,
      render: v => v === undefined ? '-' : v},
    {title: '启用', dataIndex: 'is_active', width: 80, render: (v, record) => (
      <Switch size="small" checked={v}
        onChange={checked => this.handleUpdate(record, {is_active: checked})}/>
    )},
    {title: '操作', width: 140, render: (_, record) => (
      this.state.editingId === record.id ? (
        <span>
          <Button type="link" size="small" onClick={() => this.handleUpdate(record, {name: this.state.editingName})}>保存</Button>
          <Button type="link" size="small" onClick={() => this.setState({editingId: null})}>取消</Button>
        </span>
      ) : (
        <span>
          <Button type="link" size="small"
            onClick={() => this.setState({editingId: record.id, editingName: record.name})}>编辑</Button>
          {record.manual_count === 0 && (
            <Button type="link" size="small" danger
              onClick={() => this.handleDelete(record)}>删除</Button>
          )}
        </span>
      )
    )},
  ];

  render() {
    return (
      <Modal visible title="手册类别管理" width={520} footer={null}
        onCancel={() => store.categoryVisible = false}>
        <div style={{display: 'flex', gap: 8, marginBottom: 12}}>
          <Input style={{flex: 1}} placeholder="新类别名称" value={this.state.editingName}
            onChange={e => this.setState({editingName: e.target.value})}/>
          <Button type="primary" loading={this.state.submitting}
            onClick={this.state.editingId ? () => {
              const record = store.categories.find(c => c.id === this.state.editingId);
              if (record) this.handleUpdate(record, {name: this.state.editingName});
            } : this.handleCreate}>
            {this.state.editingId ? '保存修改' : '添加'}
          </Button>
          {this.state.editingId && (
            <Button onClick={() => this.setState({editingId: null, editingName: ''})}>取消</Button>
          )}
        </div>
        <Table rowKey="id" size="small" pagination={false}
          loading={store.categories === null}
          dataSource={store.categories || []} columns={this.columns}/>
        {store.categories && store.categories.some(c => c.manual_count > 0) && (
          <div style={{marginTop: 8, color: '#999', fontSize: 12}}>
            有关联手册的类别不能删除，只能停用。
          </div>
        )}
      </Modal>
    );
  }
}

export default CategoryModal;

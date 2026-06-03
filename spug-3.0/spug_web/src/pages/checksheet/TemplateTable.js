/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Modal, message, Tag } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { Action, TableCard, AuthButton } from "components";
import store from './store';

@observer
class TemplateTable extends React.Component {
  componentDidMount() {
    store.fetchTemplates()
  }

  handleDelete = async (text) => {
    const logInfo = text['project'];
    Modal.confirm({
      title: '删除确认',
      content: `确定要删除【${logInfo}】的检查表模板?`,
      onOk: async () => {
        await store.deleteTemplate(text.id);
        message.success('删除成功');
        store.fetchTemplates()
      }
    })
  };

  render() {
    const columns = [
      {
        title: '序号',
        width: 60,
        render: (_, __, index) => index + 1
      },
      {
        title: '项目名称',
        dataIndex: 'project',
        width: 150
      },
      {
        title: '现场巡视检查内容',
        dataIndex: 'check_items',
        render: (items) => (
          <div style={{ maxHeight: 150, overflowY: 'auto' }}>
            {Array.isArray(items) && items.map((item, idx) => (
              <Tag key={idx} color="blue" style={{ marginBottom: 4, marginRight: 4 }}>
                {item}
              </Tag>
            ))}
          </div>
        )
      },
      {
        title: '内容数量',
        dataIndex: 'check_items',
        width: 100,
        render: (items) => Array.isArray(items) ? items.length : 0
      },
      {
        title: '创建时间',
        dataIndex: 'created_at',
        width: 160
      },
      {
        title: '操作',
        width: 180,
        render: (info) => (
          <Action>
            <Action.Button onClick={() => store.showTemplateForm(info)}>查看</Action.Button>
            <Action.Button auth="checksheet.checksheet.template_edit" onClick={() => store.showTemplateForm(info)}>编辑</Action.Button>
            <Action.Button danger auth="checksheet.checksheet.template_del" onClick={() => this.handleDelete(info)}>删除</Action.Button>
          </Action>
        )
      }
    ];

    return (
      <TableCard
        tKey="ct"
        title="检查表模板列表"
        rowKey="id"
        loading={store.isFetching}
        dataSource={store.filteredTemplates}
        columns={columns}
        onReload={store.fetchTemplates}
        actions={[
          <AuthButton
            auth="checksheet.checksheet.template_add"
            type="primary"
            icon={<PlusOutlined/>}
            onClick={() => store.showTemplateForm({})}>新建模板</AuthButton>
        ]}
        pagination={{
          showSizeChanger: true,
          showLessItems: true,
          showTotal: total => `共 ${total} 条`,
          pageSizeOptions: ['10', '20', '50']
        }}
      />
    )
  }
}

export default TemplateTable

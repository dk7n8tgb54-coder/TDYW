/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 系统详情——配置快照页签。
 * 按需生成快照（普通修改不要求手工发布），支持与当前配置或另一快照比较差异。
 */
import React, { useState } from 'react';
import { observer } from 'mobx-react';
import { Table, Button, Modal, Form, Input, Tag, Divider, message } from 'antd';
import { AuthButton } from 'components';
import store from './store';
import { PERM } from './constants';

const {TextArea} = Input;

@observer
class SnapshotsTab extends React.Component {
  state = {diffTarget: {}};

  componentDidMount() {
    store.fetchSnapshots();
  }

  viewDiff = (record, target = 'current') => {
    if (target === 'previous') {
      const idx = store.snapshots.findIndex(s => s.id === record.id);
      const previous = store.snapshots[idx + 1];
      if (!previous) {
        message.warning('没有更早的快照可比较');
        return;
      }
      target = previous.id;
    }
    store.fetchSnapshotDiff(record.id, target)
      .catch(() => {});
  };

  render() {
    return (
      <div>
        <div style={{marginBottom: 12}}>
          <AuthButton
            auth={PERM.CFG_SNAPSHOT}
            type="primary"
            icon="camera"
            onClick={() => store.snapshotFormVisible = true}
          >
            生成快照
          </AuthButton>
          <span style={{color: '#999', marginLeft: 12}}>
            用于重要配置变更或技术改造前后的差异比较；普通修改自动记录变更历史，无需手工发布
          </span>
        </div>
        <Table
          rowKey="id"
          size="small"
          loading={store.isSnapshotsFetching}
          dataSource={store.snapshots}
          columns={[{
            title: '快照名称', dataIndex: 'name', width: 180,
          }, {
            title: '说明', dataIndex: 'remark', ellipsis: true,
          }, {
            title: '创建人', dataIndex: 'created_by_name', width: 110,
          }, {
            title: '创建时间', dataIndex: 'created_at', width: 170,
          }, {
            title: '操作', width: 200,
            render: (text, record) => (
              <span>
                <a onClick={() => this.viewDiff(record, 'current')}>与当前配置比较</a>
                <Divider type="vertical"/>
                <a onClick={() => this.viewDiff(record, 'previous')}>与上一份比较</a>
              </span>
            ),
          }]}
          pagination={{
            total: store.snapshotsTotal,
            pageSize: 10,
            showTotal: t => `共 ${t} 份`,
          }}
          locale={{emptyText: '暂无配置快照'}}
        />
        <SnapshotForm/>
        <DiffModal/>
      </div>
    );
  }
}

function SnapshotForm() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);

  function handleSubmit() {
    form.validateFields().then(values => {
      setLoading(true);
      store.createSnapshot(values)
        .catch(() => {})
        .finally(() => setLoading(false));
    }).catch(() => {});
  }

  return (
    <Modal
      visible={store.snapshotFormVisible}
      title="生成配置快照"
      maskClosable={false}
      confirmLoading={loading}
      onCancel={() => store.snapshotFormVisible = false}
      onOk={handleSubmit}
    >
      <Form form={form} labelCol={{span: 5}} wrapperCol={{span: 17}}>
        <Form.Item name="name" label="快照名称"
                   rules={[{required: true, message: '请输入快照名称'}, {max: 100, message: '长度不能超过 100'}]}>
          <Input placeholder="如：技术改造前配置"/>
        </Form.Item>
        <Form.Item name="remark" label="说明" rules={[{max: 500, message: '长度不能超过 500'}]}>
          <TextArea rows={2}/>
        </Form.Item>
      </Form>
    </Modal>
  );
}

@observer
class DiffModal extends React.Component {
  render() {
    const diff = store.snapshotDiff;
    if (!diff) return null;
    const {snapshot, target, diffs} = diff;
    return (
      <Modal
        visible
        width={760}
        title={`配置差异 - 快照「${snapshot.name}」 对比 「${target.label}」`}
        footer={<Button onClick={() => store.clearSnapshotDiff()}>关闭</Button>}
        onCancel={() => store.clearSnapshotDiff()}
      >
        <Table
          size="small"
          rowKey={(_, idx) => idx}
          pagination={false}
          dataSource={diffs}
          columns={[{
            title: '分组', dataIndex: 'group', width: 100,
            render: v => <Tag>{v}</Tag>,
          }, {
            title: '项目', dataIndex: 'label', width: 150,
          }, {
            title: snapshot.name, dataIndex: 'old', ellipsis: true,
          }, {
            title: target.label, dataIndex: 'new', ellipsis: true,
          }]}
          locale={{emptyText: '两者配置一致，无差异'}}
        />
      </Modal>
    );
  }
}

export default SnapshotsTab;

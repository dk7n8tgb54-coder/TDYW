import React, {useEffect, useState} from 'react';
import {Button, Form, Input, InputNumber, Modal, Select, Switch, message} from 'antd';
import {PlusOutlined} from '@ant-design/icons';
import {http} from 'libs';
import {Action, AuthButton, AuthDiv, TableCard} from 'components';

export const GROUP_OPTIONS = [
  {value: 'interference_kind', label: '具体干扰类型'},
  {value: 'affected_system', label: '受影响系统'},
  {value: 'source_type', label: '疑似干扰源'},
];

const CODE_PATTERN = /^[a-z][a-z0-9_]*$/;

const columns = (onEdit, onRemove) => [
  {title: '分组', dataIndex: 'group_text', width: 130},
  {title: '编码', dataIndex: 'code', width: 180},
  {title: '名称', dataIndex: 'name', width: 160},
  {title: '排序', dataIndex: 'sort_id', width: 80},
  {
    title: '状态', dataIndex: 'is_active', width: 90,
    render: value => value
      ? <span style={{color: '#52c41a'}}>启用</span>
      : <span style={{color: '#999999'}}>已停用</span>,
  },
  {title: '更新时间', dataIndex: 'updated_at', width: 170, render: value => value ? String(value).replace('T', ' ').slice(0, 19) : '-'},
  {title: '操作', width: 140, render: record => <Action>
    <Action.Button onClick={() => onEdit(record)}>编辑</Action.Button>
    <Action.Button danger onClick={() => onRemove(record)}>删除</Action.Button>
  </Action>},
];

function CategoryModal({visible, editing, onClose, onSaved}) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const isEdit = !!(editing && editing.id);

  useEffect(() => {
    if (visible) form.setFieldsValue(editing || {});
  }, [visible, editing, form]);

  function close() {
    form.resetFields();
    onClose();
  }

  function submit() {
    if (loading) return;
    setLoading(true);
    form.validateFields().then(values => (
      isEdit
        ? http.put(`/api/interference/categories/${editing.id}/`, values)
        : http.post('/api/interference/categories/', values)
    )).then(() => {
      message.success('保存成功');
      close();
      onSaved();
    }).catch(() => {}).finally(() => setLoading(false));
  }

  return <Modal
    visible={visible}
    title={isEdit ? '编辑分类选项' : '新增分类选项'}
    onCancel={close}
    maskClosable={false}
    destroyOnClose
    confirmLoading={loading}
    onOk={submit}
  >
    <Form form={form} layout="vertical">
      <Form.Item name="group" label="分组" rules={[{required: true, message: '请选择分组'}]}>
        <Select options={GROUP_OPTIONS} disabled={isEdit}/>
      </Form.Item>
      <Form.Item name="code" label="编码" rules={[
        {required: true, message: '请输入编码'},
        {pattern: CODE_PATTERN, message: '编码必须以小写字母开头，仅含小写字母、数字和下划线'},
      ]}>
        <Input disabled={isEdit} maxLength={40} placeholder="例如 harmonic"/>
      </Form.Item>
      <Form.Item name="name" label="名称" rules={[
        {required: true, message: '请输入名称'},
        {max: 100, message: '名称不能超过100个字符'},
      ]}>
        <Input maxLength={100}/>
      </Form.Item>
      <Form.Item name="sort_id" label="排序"><InputNumber min={0} style={{width: '100%'}}/></Form.Item>
      {isEdit && <Form.Item name="is_active" label="启用" valuePropName="checked"><Switch/></Form.Item>}
    </Form>
    <div style={{color: '#999999'}}>
      编码不可修改；未被任何干扰事件引用的选项可删除，已被引用的选项只能停用；
      停用后不再供新事件选择，历史记录仍按名称正常显示。「未知/待查」为新建事件的默认分类值，不可删除。
    </div>
  </Modal>;
}

function CategoriesPage() {
  const [records, setRecords] = useState([]);
  const [loading, setLoading] = useState(false);
  const [group, setGroup] = useState(undefined);
  const [editorVisible, setEditorVisible] = useState(false);
  const [editing, setEditing] = useState(null);

  function fetchRecords() {
    setLoading(true);
    return http.get('/api/interference/categories/', {
      params: {include_inactive: 1, group},
    }).then(data => {
      setRecords((data && data.records) || []);
    }).catch(() => {}).finally(() => setLoading(false));
  }

  useEffect(() => { fetchRecords(); }, [group]);

  function openCreate() {
    setEditing(null);
    setEditorVisible(true);
  }

  function openEdit(record) {
    setEditing(record);
    setEditorVisible(true);
  }

  function removeRecord(record) {
    Modal.confirm({
      title: '删除分类选项',
      content: `确定删除选项「${record.name}」吗？只有未被任何干扰事件引用的选项可以删除，已被引用的选项请使用停用功能。`,
      okType: 'danger',
      onOk: () => http.delete(`/api/interference/categories/${record.id}/`).then(() => {
        message.success('删除成功');
        return fetchRecords();
      }).catch(() => {}),
    });
  }

  return <AuthDiv auth="interference.category.manage">
    <TableCard
      tKey="interferenceCategories"
      title="干扰分类选项"
      rowKey="id"
      loading={loading}
      dataSource={records}
      onReload={fetchRecords}
      columns={columns(openEdit, removeRecord)}
      actions={[
        <Select
          key="group" allowClear placeholder="全部分组" style={{width: 160}}
          options={GROUP_OPTIONS} value={group}
          onChange={value => setGroup(value)}/>,
        <AuthButton
          key="add" auth="interference.category.manage" type="primary"
          icon={<PlusOutlined/>} onClick={openCreate}>新增选项</AuthButton>,
      ]}
      pagination={{pageSize: 50, showSizeChanger: false}}
    />
    {editorVisible && <CategoryModal
      visible={editing !== undefined}
      editing={editing}
      onClose={() => setEditorVisible(false)}
      onSaved={fetchRecords}
    />}
  </AuthDiv>;
}

export default CategoriesPage;

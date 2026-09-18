/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——系统类型管理页（含类型字段模板维护）。
 */
import React, { useState } from 'react';
import { observer } from 'mobx-react';
import {
  Table, Button, Modal, Form, Input, InputNumber, Select, Switch, Tag, Drawer,
  Divider, Popconfirm, Spin,
} from 'antd';
import {PlusOutlined} from '@ant-design/icons';
import { AuthDiv, Breadcrumb, AuthButton } from 'components';
import store from './store';
import { FIELD_TYPE_OPTIONS, FIELD_TYPE_TEXT, PERM } from '../constants';

const {TextArea} = Input;

@observer
class SystemTypeIndex extends React.Component {
  render() {
    return (
      <AuthDiv auth={PERM.TYPE_VIEW}>
        <Breadcrumb>
          <Breadcrumb.Item>首页</Breadcrumb.Item>
          <Breadcrumb.Item>设备全生命周期</Breadcrumb.Item>
          <Breadcrumb.Item>系统档案</Breadcrumb.Item>
          <Breadcrumb.Item>系统类型管理</Breadcrumb.Item>
        </Breadcrumb>
        <div style={{marginBottom: 12}}>
          <AuthButton
            auth={PERM.TYPE_ADD}
            type="primary"
            icon={<PlusOutlined/>}
            onClick={() => store.showForm()}
          >
            新增系统类型
          </AuthButton>
        </div>
        <Table
          rowKey="id"
          loading={store.isFetching}
          dataSource={store.types}
          columns={[{
            title: '类型名称', dataIndex: 'name', width: 200,
          }, {
            title: '说明', dataIndex: 'description', ellipsis: true,
          }, {
            title: '显示顺序', dataIndex: 'display_order', width: 90,
          }, {
            title: '系统数量', dataIndex: 'systems_count', width: 90,
          }, {
            title: '启用模板字段', dataIndex: 'template_fields_count', width: 110,
          }, {
            title: '状态', dataIndex: 'is_active', width: 90,
            render: v => (v ? <Tag color="green">启用</Tag> : <Tag color="default">停用</Tag>),
          }, {
            title: '操作', width: 220,
            render: (text, record) => (
              <span>
                <AuthButton auth={PERM.TYPE_VIEW} type="link" size="small" style={{padding: 0}}
                            onClick={() => store.showFields(record)}>
                  字段模板
                </AuthButton>
                <Divider type="vertical"/>
                <AuthButton auth={PERM.TYPE_EDIT} type="link" size="small" style={{padding: 0}}
                            onClick={() => store.showForm(record)}>
                  编辑
                </AuthButton>
                <Divider type="vertical"/>
                <Popconfirm
                  title="确定删除该系统类型？仅无系统和无模板字段的类型可删除。"
                  onOk={() => store.deleteType(record).catch(() => {})}
                >
                  <AuthButton auth={PERM.TYPE_DEL} type="link" size="small" style={{padding: 0}}>
                    删除
                  </AuthButton>
                </Popconfirm>
              </span>
            ),
          }]}
          pagination={false}
          locale={{emptyText: '暂无系统类型'}}
        />
        <TypeForm/>
        <FieldsDrawer/>
      </AuthDiv>
    );
  }
}

const TypeForm = observer(function TypeForm() {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const record = store.record;

  React.useEffect(() => {
    if (record.id) {
      form.setFieldsValue({
        name: record.name,
        description: record.description,
        display_order: record.display_order,
        is_active: record.is_active,
      });
    }
  }, [form, record]);

  function handleSubmit() {
    form.validateFields().then(values => {
      setLoading(true);
      store.submitForm(values)
        .catch(() => {})
        .finally(() => setLoading(false));
    }).catch(() => {});
  }

  return (
    <Modal
      visible={store.formVisible}
      title={record.id ? '编辑系统类型' : '新增系统类型'}
      maskClosable={false}
      confirmLoading={loading}
      onCancel={() => store.formVisible = false}
      onOk={handleSubmit}
    >
      <Form form={form} labelCol={{span: 5}} wrapperCol={{span: 17}}
            initialValues={{
              name: record.name,
              description: record.description,
              display_order: record.display_order === undefined ? 0 : record.display_order,
              is_active: record.is_active !== false,
            }}>
        <Form.Item name="name" label="类型名称"
                   rules={[{required: true, message: '请输入类型名称'}, {max: 50, message: '长度不能超过 50'}]}>
          <Input placeholder="如：通信系统 / 软件系统"/>
        </Form.Item>
        <Form.Item name="description" label="说明" rules={[{max: 500, message: '长度不能超过 500'}]}>
          <TextArea rows={2}/>
        </Form.Item>
        <Form.Item name="display_order" label="显示顺序">
          <InputNumber style={{width: '100%'}}/>
        </Form.Item>
        <Form.Item name="is_active" label="是否启用" extra="停用后不可用于新建系统" valuePropName="checked">
          <Switch/>
        </Form.Item>
      </Form>
    </Modal>
  );
});

@observer
class FieldsDrawer extends React.Component {
  render() {
    const type = store.currentType;
    return (
      <Drawer
        title={`字段模板 - ${type.name || ''}`}
        visible={store.drawerVisible}
        width={820}
        onClose={() => store.drawerVisible = false}
        destroyOnClose
      >
        <div style={{marginBottom: 12}}>
          <AuthButton
            auth={PERM.TYPE_ADD}
            type="primary"
            icon={<PlusOutlined/>}
            onClick={() => store.showFieldForm(null)}
          >
            新增模板字段
          </AuthButton>
          <span style={{color: '#999', marginLeft: 12}}>
            该类型的全部系统共享模板字段；停用字段不再用于新录入，历史值保留
          </span>
        </div>
        <Spin spinning={store.isFieldsFetching}>
          <Table
            rowKey="id"
            pagination={false}
            dataSource={store.fields}
            columns={[{
              title: '字段编码', dataIndex: 'field_code', width: 140,
            }, {
              title: '显示名称', dataIndex: 'display_name', width: 140,
            }, {
              title: '类型', dataIndex: 'field_type', width: 90,
              render: v => FIELD_TYPE_TEXT[v] || v,
            }, {
              title: '必填', dataIndex: 'is_required', width: 60,
              render: v => (v ? <Tag color="red">是</Tag> : '否'),
            }, {
              title: '顺序', dataIndex: 'display_order', width: 60,
            }, {
              title: '标记', key: 'flags', width: 160,
              render: (text, record) => (
                <span>
                  {record.is_sensitive && <Tag color="orange">敏感</Tag>}
                  {record.is_filterable && <Tag>可筛选</Tag>}
                  {record.is_exportable && <Tag>可导出</Tag>}
                </span>
              ),
            }, {
              title: '状态', dataIndex: 'is_active', width: 80,
              render: v => (v ? <Tag color="green">启用</Tag> : <Tag color="default">停用</Tag>),
            }, {
              title: '操作', width: 130,
              render: (text, record) => (
                <span>
                  <AuthButton auth={PERM.TYPE_EDIT} type="link" size="small" style={{padding: 0}}
                              onClick={() => store.showFieldForm(record)}>
                    编辑
                  </AuthButton>
                  <Divider type="vertical"/>
                  <Popconfirm
                    title="仅无历史值的字段可删除，确认删除？"
                    onOk={() => store.deleteField(record).catch(() => {})}
                  >
                    <AuthButton auth={PERM.TYPE_DEL} type="link" size="small" style={{padding: 0}}>
                      删除
                    </AuthButton>
                  </Popconfirm>
                </span>
              ),
            }]}
            locale={{emptyText: '暂无模板字段'}}
          />
        </Spin>
        <FieldForm/>
      </Drawer>
    );
  }
}

const FieldForm = observer(function FieldForm() {
  const [form] = Form.useForm();
  const [typeOverride, setTypeOverride] = useState(null);
  const record = store.fieldRecord || {};
  const isEdit = !!(record && record.id);
  const fieldType = typeOverride || record.field_type || 'text';
  const initialChoices = (record.choices ? JSON.parse(record.choices || '[]') : []).join('\n');
  const initialColumns = (record.detail_columns
    ? JSON.parse(record.detail_columns || '[]') : [])
    .map(col => `${col.code}:${col.name}`).join('\n');

  React.useEffect(() => {
    if (isEdit) {
      form.setFieldsValue({
        display_name: record.display_name,
        help_text: record.help_text,
        display_order: record.display_order,
        is_required: record.is_required,
        is_sensitive: record.is_sensitive,
        is_filterable: record.is_filterable,
        is_exportable: record.is_exportable,
        applies_to: record.applies_to,
        is_active: record.is_active,
      });
    }
  }, [form, record, isEdit]);

  function handleSubmit() {
    form.validateFields().then(values => {
      const data = {...values};
      if (data.field_type === 'choice' || data.field_type === 'multi_choice') {
        data.choices = JSON.stringify(
          (data.choices_raw || '').split('\n').map(x => x.trim()).filter(Boolean));
      }
      delete data.choices_raw;
      if (data.field_type === 'detail_table') {
        const columns = (data.detail_columns_raw || '')
          .split('\n').map(x => x.trim()).filter(Boolean)
          .map(line => {
            const [code, ...rest] = line.split(/\s*[:：,，]\s*/);
            return {code, name: rest.join(' ') || code};
          });
        data.detail_columns = JSON.stringify(columns);
      }
      delete data.detail_columns_raw;
      store.submitField(data).catch(() => {});
    }).catch(() => {});
  }

  return (
    <Modal
      visible={store.fieldFormVisible}
      title={isEdit ? '编辑模板字段' : '新增模板字段'}
      width={640}
      maskClosable={false}
      confirmLoading={store.isFieldSubmitting}
      onCancel={() => store.fieldFormVisible = false}
      onOk={handleSubmit}
    >
      <Form form={form} labelCol={{span: 6}} wrapperCol={{span: 16}}
            initialValues={{
              field_code: record.field_code,
              display_name: record.display_name,
              field_type: record.field_type || 'text',
              choices_raw: initialChoices,
              detail_columns_raw: initialColumns,
              number_min: record.number_min === null || record.number_min === undefined
                ? undefined : record.number_min,
              number_max: record.number_max === null || record.number_max === undefined
                ? undefined : record.number_max,
              text_regex: record.text_regex,
              help_text: record.help_text,
              display_order: record.display_order === undefined ? 0 : record.display_order,
              is_required: !!record.is_required,
              is_sensitive: !!record.is_sensitive,
              is_filterable: !!record.is_filterable,
              is_exportable: !!record.is_exportable,
              applies_to: record.applies_to || 'all',
              is_active: record.is_active !== false,
            }}>
        <Form.Item
          name="field_code"
          label="字段编码"
          extra="稳定编码，创建后不可修改；不得与固定核心字段重复"
          rules={[
            {required: true, message: '请输入字段编码'},
            {pattern: /^[a-z][a-z0-9_]{0,49}$/, message: '小写字母开头，仅含小写字母、数字、下划线'},
          ]}
        >
          <Input disabled={isEdit}/>
        </Form.Item>
        <Form.Item name="display_name" label="显示名称"
                   rules={[{required: true, message: '请输入显示名称'}, {max: 100, message: '长度不能超过 100'}]}>
          <Input/>
        </Form.Item>
        <Form.Item name="field_type" label="字段类型" extra="已有历史值的字段不可变更类型" rules={[{required: true}]}>
          <Select disabled={isEdit} onChange={v => setTypeOverride(v)}>
            {FIELD_TYPE_OPTIONS.map(item => (
              <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
            ))}
          </Select>
        </Form.Item>
        {(fieldType === 'choice' || fieldType === 'multi_choice') && (
          <Form.Item name="choices_raw" label="候选项" extra="每行一个候选项">
            <TextArea rows={3}/>
          </Form.Item>
        )}
        {fieldType === 'detail_table' && (
          <Form.Item name="detail_columns_raw" label="明细列" extra="每行一列，格式：列编码:列名">
            <TextArea rows={3}/>
          </Form.Item>
        )}
        {fieldType === 'number' && (
          <Form.Item label="数值范围">
            <Input.Group compact>
              <Form.Item name="number_min" noStyle>
                <InputNumber placeholder="最小值" style={{width: '50%'}}/>
              </Form.Item>
              <Form.Item name="number_max" noStyle>
                <InputNumber placeholder="最大值" style={{width: '50%'}}/>
              </Form.Item>
            </Input.Group>
          </Form.Item>
        )}
        {fieldType === 'text' && (
          <Form.Item name="text_regex" label="格式校验" extra="选填，JavaScript 正则表达式">
            <Input/>
          </Form.Item>
        )}
        <Form.Item name="help_text" label="帮助文字" rules={[{max: 200, message: '长度不能超过 200'}]}>
          <Input/>
        </Form.Item>
        <Form.Item name="display_order" label="显示顺序">
          <InputNumber style={{width: '100%'}}/>
        </Form.Item>
        <Form.Item name="is_required" label="是否必填" valuePropName="checked">
          <Switch/>
        </Form.Item>
        <Form.Item name="is_sensitive" label="敏感配置" extra="查看有值敏感字段将记录审计" valuePropName="checked">
          <Switch/>
        </Form.Item>
        <Form.Item name="is_filterable" label="允许筛选" valuePropName="checked">
          <Switch/>
        </Form.Item>
        <Form.Item name="is_exportable" label="允许导出" valuePropName="checked">
          <Switch/>
        </Form.Item>
        <Form.Item name="applies_to" label="适用范围" extra="仅新建系统：新增字段后已有系统显示为空，逐步补录">
          <Select>
            <Select.Option value="all">全部系统</Select.Option>
            <Select.Option value="new_only">仅新建系统</Select.Option>
          </Select>
        </Form.Item>
        {isEdit && (
          <Form.Item name="is_active" label="是否启用" extra="停用后不再用于新录入，历史值保留可查"
                     valuePropName="checked">
            <Switch/>
          </Form.Item>
        )}
      </Form>
    </Modal>
  );
});

export default SystemTypeIndex;

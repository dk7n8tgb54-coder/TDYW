/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 系统详情——配置字段页签。
 * 仅管理字段定义（本系统自定义字段），不录入字段值；
 * 字段值统一在新增或编辑系统页面填写。自定义字段管理需 system_config.field 权限。
 */
import React, { useState, useRef, useEffect } from 'react';
import { observer } from 'mobx-react';
import { Table, Tag, Alert, Divider, Popconfirm } from 'antd';
import { PlusOutlined } from '@ant-design/icons';
import { Form, Input, InputNumber, Select, Switch, Modal } from 'antd';
import { AuthButton } from 'components';
import store from './store';
import { PERM, FIELD_TYPE_TEXT, FIELD_TYPE_OPTIONS } from './constants';

const {TextArea} = Input;

function parseChoices(choices) {
  try {
    const data = JSON.parse(choices);
    return Array.isArray(data) ? data.map(String) : [];
  } catch (e) {
    return [];
  }
}

function parseDetailColumns(raw) {
  try {
    const data = JSON.parse(raw);
    return Array.isArray(data) ? data.filter(c => c && c.code) : [];
  } catch (e) {
    return [];
  }
}

function fieldColumns(showActions, handlers) {
  const columns = [{
    title: '字段编码', dataIndex: 'field_code', width: 150,
  }, {
    title: '显示名称', dataIndex: 'display_name', width: 150,
  }, {
    title: '类型', dataIndex: 'field_type', width: 90,
    render: v => FIELD_TYPE_TEXT[v] || v,
  }, {
    title: '必填', dataIndex: 'is_required', width: 60,
    render: v => (v ? <Tag color="red">是</Tag> : '否'),
  }, {
    title: '状态', dataIndex: 'is_active', width: 80,
    render: v => (v ? <Tag color="green">启用</Tag> : <Tag color="default">已停用</Tag>),
  }, {
    title: '当前值', key: 'value',
    render: (text, record) => record.display || '-',
  }];
  if (showActions) {
    columns.push({
      title: '操作', width: 250,
      render: (text, record) => (
        <span>
          <AuthButton auth={PERM.CFG_FIELD} type="link" size="small" style={{padding: 0}}
                      onClick={() => handlers.showFieldForm(record)}>
            编辑定义
          </AuthButton>
          <Divider type="vertical"/>
          <AuthButton auth={PERM.CFG_FIELD} type="link" size="small" style={{padding: 0}}
                      onClick={() => handlers.toggleFieldActive(record)}>
            {record.is_active ? '停用' : '启用'}
          </AuthButton>
          <Divider type="vertical"/>
          <Popconfirm
            title="删除后历史值与变更记录不受影响，确认删除？"
            onOk={() => handlers.handleFieldDeleted(record)}
          >
            <AuthButton auth={PERM.CFG_FIELD} type="link" size="small" style={{padding: 0}}>
              删除
            </AuthButton>
          </Popconfirm>
        </span>
      ),
    });
  }
  return columns;
}

@observer
class ConfigArchiveTab extends React.Component {
  state = {
    fieldFormVisible: false,
    fieldRecord: null, // null=新增自定义字段（仅定义）
  };

  showFieldForm = (record = null) => {
    this.setState({fieldFormVisible: true, fieldRecord: record});
  };

  refreshDetail = () => {
    store.fetchDetail();
  };

  handleFieldDeleted = (record) => {
    store.deleteCustomField(record.id)
      .then(() => this.refreshDetail())
      .catch(() => {});
  };

  toggleFieldActive = (record) => {
    store.toggleCustomField(record)
      .then(() => this.refreshDetail())
      .catch(() => {});
  };

  render() {
    const configFields = store.detail.config_fields || [];
    const customFields = configFields.filter(f => f.scope_type === 'custom');
    return (
      <div>
        <Alert
          type="info"
          showIcon
          message="本页仅管理字段定义"
          description="用于定义具体系统的扩展字段；字段值在新增或编辑系统时填写，不在此录入。"
        />
        <div style={{marginTop: 16, marginBottom: 8}}>
          <b>本系统自定义字段</b>
          <span style={{color: '#999', marginLeft: 8}}>
            仅作用于本系统
          </span>
          <AuthButton
            auth={PERM.CFG_FIELD}
            style={{float: 'right'}}
            size="small"
            type="primary"
            ghost
            icon={<PlusOutlined/>}
            onClick={() => this.showFieldForm(null)}
          >
            新增自定义字段
          </AuthButton>
        </div>
        <Table
          size="small"
          rowKey="id"
          pagination={false}
          dataSource={customFields}
          columns={fieldColumns(true, {
            showFieldForm: record => this.showFieldForm(record),
            toggleFieldActive: record => this.toggleFieldActive(record),
            handleFieldDeleted: record => this.handleFieldDeleted(record),
          })}
          locale={{emptyText: '暂无自定义字段'}}
        />
        {this.state.fieldFormVisible && (
          <CustomFieldForm
            system={{id: store.detailId}}
            record={this.state.fieldRecord}
            onClose={() => this.setState({fieldFormVisible: false})}
            onSaved={() => {
              this.setState({fieldFormVisible: false});
              this.refreshDetail();
            }}
          />
        )}
      </div>
    );
  }
}

/**
 * 自定义字段定义编辑/新增（仅定义，不填值）。
 * 新增时字段编码留空由后端自动生成稳定编码。
 */
function CustomFieldForm(props) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [typeOverride, setTypeOverride] = useState(null);
  const mountedRef = useRef(true);
  useEffect(() => () => { mountedRef.current = false; }, []);
  const record = props.record || {};
  const isEdit = !!record.id;

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
      if (!isEdit) {
        delete data.field_code; // 留空由后端生成稳定编码
      }
      setLoading(true);
      const request = isEdit
        ? store.updateCustomField(record.id, data)
        : store.createCustomField(data);
      request
        .then(() => props.onSaved())
        .catch(() => {})
        .finally(() => {
          if (mountedRef.current) setLoading(false);
        });
    }).catch(() => {});
  }

  const fieldType = typeOverride || record.field_type || 'text';
  const isChoice = fieldType === 'choice' || fieldType === 'multi_choice';
  const initialChoices = parseChoices(record.choices).join('\n');
  const initialColumns = parseDetailColumns(record.detail_columns)
    .map(col => `${col.code}:${col.name}`).join('\n');
  return (
    <Modal
      visible
      title={isEdit ? '编辑自定义字段' : '新增自定义字段'}
      maskClosable={false}
      confirmLoading={loading}
      onCancel={props.onClose}
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
              is_exportable: !!record.is_exportable,
              is_active: record.is_active !== false,
            }}>
        {isEdit && (
          <Form.Item
            name="field_code"
            label="字段编码"
            extra="稳定字段编码，创建后不可修改"
          >
            <Input disabled/>
          </Form.Item>
        )}
        <Form.Item
          name="display_name"
          label="显示名称"
          rules={[{required: true, message: '请输入显示名称'}, {max: 100, message: '长度不能超过 100'}]}
        >
          <Input/>
        </Form.Item>
        <Form.Item name="field_type" label="字段类型" rules={[{required: true}]}>
          <Select disabled={isEdit} onChange={v => setTypeOverride(v)}>
            {FIELD_TYPE_OPTIONS.map(item => (
              <Select.Option value={item.value} key={item.value}>{item.label}</Select.Option>
            ))}
          </Select>
        </Form.Item>
        {isChoice && (
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
            <Input placeholder="如 ^[0-9.]+MHz$"/>
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
        <Form.Item name="is_sensitive" label="敏感配置" valuePropName="checked">
          <Switch/>
        </Form.Item>
        <Form.Item name="is_exportable" label="允许导出" valuePropName="checked">
          <Switch/>
        </Form.Item>
        {isEdit && (
          <Form.Item name="is_active" label="是否启用" valuePropName="checked">
            <Switch/>
          </Form.Item>
        )}
      </Form>
      <div style={{color: '#999'}}>
        本弹窗仅定义字段；字段值请在新增或编辑系统页面填写。
      </div>
    </Modal>
  );
}

export default ConfigArchiveTab;

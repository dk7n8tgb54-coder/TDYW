/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 系统详情——配置档案页签。
 * 固定核心字段之外，按"类型模板字段 + 具体系统自定义字段"渲染动态表单；
 * 停用字段只读展示历史值；自定义字段管理需 system_config.field 权限。
 */
import React, { useState } from 'react';
import moment from 'moment';
import { observer } from 'mobx-react';
import {
  Spin, Form, Input, InputNumber, Select, DatePicker, Button, Table, Modal, Tag,
  Switch, Upload, Icon, message, Popconfirm, Divider,
} from 'antd';
import { AuthButton, AuthDiv } from 'components';
import store from './store';
import { FIELD_TYPE_TEXT, PERM, API_PREFIX } from './constants';

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

@observer
class ConfigArchiveTab extends React.Component {
  state = {
    values: {},       // 提交草稿：{[field_id]: value}
    fieldFormVisible: false,
    fieldRecord: null, // null=新增 自定义字段
  };

  componentDidMount() {
    store.fetchConfig();
    store.fetchConfigAttachments();
  }

  getValue = (field) => {
    if (this.state.values[field.id] !== undefined) return this.state.values[field.id];
    const entry = store.config && store.config.values[String(field.id)];
    return entry ? entry.value : '';
  };

  setValue = (field, value) => {
    this.setState(prev => ({values: {...prev.values, [field.id]: value}}));
  };

  handleSave = () => {
    store.saveConfig(this.state.values)
      .then(() => {
        message.success('配置已保存');
        this.setState({values: {}});
      })
      .catch(() => {});
  };

  renderControl = (field) => {
    const value = this.getValue(field);
    const disabled = !store.config || this.isSavingDisabled();
    switch (field.field_type) {
      case 'text':
        return (
          <Input
            maxLength={500}
            value={value}
            disabled={disabled}
            onChange={e => this.setValue(field, e.target.value)}
          />
        );
      case 'longtext':
        return (
          <TextArea
            rows={3}
            maxLength={10000}
            value={value}
            disabled={disabled}
            onChange={e => this.setValue(field, e.target.value)}
          />
        );
      case 'number': {
        const parsed = value === '' || value === null || value === undefined ? undefined : value;
        return (
          <InputNumber
            style={{width: '100%'}}
            min={field.number_min !== null && field.number_min !== undefined ? field.number_min : undefined}
            max={field.number_max !== null && field.number_max !== undefined ? field.number_max : undefined}
            value={parsed}
            disabled={disabled}
            onChange={v => this.setValue(field, v === undefined ? '' : v)}
          />
        );
      }
      case 'date':
        return (
          <DatePicker
            style={{width: '100%'}}
            value={value ? moment(value) : null}
            disabled={disabled}
            onChange={d => this.setValue(field, d ? d.format('YYYY-MM-DD') : '')}
          />
        );
      case 'choice':
        return (
          <Select
            allowClear
            style={{width: '100%'}}
            value={value || undefined}
            disabled={disabled}
            onChange={v => this.setValue(field, v === undefined ? '' : v)}
          >
            {parseChoices(field.choices).map(option => (
              <Select.Option value={option} key={option}>{option}</Select.Option>
            ))}
          </Select>
        );
      case 'multi_choice':
        return (
          <Select
            mode="multiple"
            style={{width: '100%'}}
            value={Array.isArray(value) ? value : []}
            disabled={disabled}
            onChange={v => this.setValue(field, v)}
          >
            {parseChoices(field.choices).map(option => (
              <Select.Option value={option} key={option}>{option}</Select.Option>
            ))}
          </Select>
        );
      case 'boolean':
        return (
          <Select
            allowClear
            style={{width: '100%'}}
            value={value === '' || value === null || value === undefined ? undefined : !!value}
            disabled={disabled}
            onChange={v => this.setValue(field, v === undefined ? '' : v)}
          >
            <Select.Option value={true}>是</Select.Option>
            <Select.Option value={false}>否</Select.Option>
          </Select>
        );
      case 'attachment':
        return this.renderAttachmentControl(field);
      case 'detail_table':
        return this.renderDetailTableControl(field);
      default:
        return <Input disabled value={value}/>;
    }
  };

  isSavingDisabled = () => this.state.saving === true;

  renderAttachmentControl = (field) => {
    const value = this.getValue(field);
    const ids = Array.isArray(value) ? value : [];
    const attachments = (store.configAttachments || []).filter(a => ids.includes(a.id));
    const uploading = this.state[`uploading_${field.id}`] || false;
    return (
      <div>
        <Table
          size="small"
          rowKey="id"
          pagination={false}
          dataSource={attachments}
          columns={[{
            title: '文件名', dataIndex: 'file_name', ellipsis: true,
          }, {
            title: '大小', dataIndex: 'file_size', width: 90,
            render: s => `${Math.max(1, Math.round((s || 0) / 1024))} KB`,
          }, {
            title: '操作', width: 130,
            render: (text, att) => (
              <span>
                <a href={`${API_PREFIX}/systems/${store.detailId}/config/attachments/${att.id}/download/`}
                   target="_blank" rel="noopener noreferrer">下载</a>
                <Divider type="vertical"/>
                <Popconfirm
                  title="删除该附件？"
                  onOk={() => {
                    store.deleteConfigAttachment(att.id)
                      .then(() => {
                        this.setValue(field, ids.filter(x => x !== att.id));
                        store.fetchConfigAttachments();
                      })
                      .catch(() => {});
                  }}
                >
                  <a>删除</a>
                </Popconfirm>
              </span>
            ),
          }]}
          locale={{emptyText: '暂无附件'}}
        />
        <Upload
          showUploadList={false}
          beforeUpload={(file) => {
            this.setState({[`uploading_${field.id}`]: true});
            store.uploadConfigAttachment(file)
              .then(res => {
                this.setValue(field, [...ids, res.id]);
                store.fetchConfigAttachments();
                this.setState({[`uploading_${field.id}`]: false});
              })
              .catch(() => {
                this.setState({[`uploading_${field.id}`]: false});
              });
            return false;
          }}
        >
          <Button size="small" loading={uploading} disabled={this.isSavingDisabled()}>
            <Icon type="upload"/> 上传附件
          </Button>
        </Upload>
      </div>
    );
  };

  renderDetailTableControl = (field) => {
    const value = this.getValue(field);
    const rows = Array.isArray(value) ? value : [];
    const columns = parseDetailColumns(field.detail_columns);
    const disabled = this.isSavingDisabled();
    const updateRow = (idx, key, val) => {
      const next = rows.map((row, i) => i === idx ? {...row, [key]: val} : row);
      this.setValue(field, next);
    };
    return (
      <div>
        <Table
          size="small"
          rowKey={(_, idx) => idx}
          pagination={false}
          dataSource={rows}
          columns={[
            ...columns.map(col => ({
              title: col.name,
              dataIndex: col.code,
              render: (text, row, idx) => (
                <Input
                  size="small"
                  value={(row && row[col.code]) || ''}
                  disabled={disabled}
                  onChange={e => updateRow(idx, col.code, e.target.value)}
                />
              ),
            })),
            {
              title: '操作', width: 60,
              render: (text, row, idx) => (
                <a disabled={disabled} onClick={() => {
                  this.setValue(field, rows.filter((_, i) => i !== idx));
                }}>删除</a>
              ),
            },
          ]}
          locale={{emptyText: '暂无明细行'}}
        />
        <Button
          size="small"
          icon="plus"
          disabled={disabled}
          onClick={() => {
            const blank = {};
            columns.forEach(col => blank[col.code] = '');
            this.setValue(field, [...rows, blank]);
          }}
        >
          添加行
        </Button>
      </div>
    );
  };

  // ========== 自定义字段管理 ==========
  showFieldForm = (record = null) => {
    this.setState({fieldFormVisible: true, fieldRecord: record});
  };

  handleFieldDeleted = (record) => {
    store.deleteCustomField(record.id)
      .then(() => store.fetchConfig())
      .catch(() => {});
  };

  handlePromote = (record) => {
    store.promoteCustomField(record.id)
      .then(() => {
        message.success('已提升为类型模板字段');
        store.fetchConfig();
      })
      .catch(() => {});
  };

  toggleFieldActive = (record) => {
    store.toggleCustomField(record)
      .then(() => store.fetchConfig())
      .catch(() => {});
  };

  renderCustomFieldSection() {
    const config = store.config;
    if (!config) return null;
    const customFields = config.fields.filter(f => f.scope_type === 'custom');
    const canManage = true; // 按钮内部由 AuthButton 按权限渲染
    return (
      <div style={{marginBottom: 16}}>
        <div style={{marginBottom: 8}}>
          <b>本系统自定义字段</b>
          <span style={{color: '#999', marginLeft: 8}}>
            仅作用于本系统；同一含义在多个系统复用时建议提升为类型模板字段
          </span>
          <AuthButton
            auth={PERM.CFG_FIELD}
            style={{float: 'right'}}
            size="small"
            type="primary"
            ghost
            icon="plus"
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
            title: '状态', dataIndex: 'is_active', width: 80,
            render: (v, record) => v
              ? <Tag color="green">启用</Tag>
              : <Tag color="default">已停用</Tag>,
          }, {
            title: '操作', width: 220,
            render: (text, record) => (
              <span>
                <AuthButton auth={PERM.CFG_FIELD} type="link" size="small"
                            style={{padding: 0}}
                            onClick={() => this.showFieldForm(record)}>
                  编辑
                </AuthButton>
                <Divider type="vertical"/>
                <AuthButton auth={PERM.CFG_FIELD} type="link" size="small"
                            style={{padding: 0}}
                            onClick={() => this.toggleFieldActive(record)}>
                  {record.is_active ? '停用' : '启用'}
                </AuthButton>
                <Divider type="vertical"/>
                <Popconfirm
                  title="删除后历史值与变更记录不受影响，确认删除？"
                  onOk={() => this.handleFieldDeleted(record)}
                >
                  <AuthButton auth={PERM.CFG_FIELD} type="link" size="small" style={{padding: 0}}>
                    删除
                  </AuthButton>
                </Popconfirm>
                <Divider type="vertical"/>
                <Popconfirm
                  title={`将该字段提升为类型「${config.system.system_type_name}」模板字段？本系统已有值将随字段迁移。`}
                  onOk={() => this.handlePromote(record)}
                >
                  <AuthButton auth={PERM.CFG_FIELD} type="link" size="small" style={{padding: 0}}>
                    提升为模板字段
                  </AuthButton>
                </Popconfirm>
              </span>
            ),
          }]}
          locale={{emptyText: '暂无自定义字段'}}
        />
      </div>
    );
  }

  render() {
    const config = store.config;
    if (store.isConfigFetching || !config) {
      return <Spin style={{display: 'block', marginTop: 60}}/>;
    }
    const activeFields = config.fields.filter(f => f.is_active);
    const inactiveFields = config.fields.filter(f => !f.is_active);
    const hasValues = Object.keys(this.state.values).length > 0;
    return (
      <div>
        {this.renderCustomFieldSection()}
        <Form labelCol={{span: 6}} wrapperCol={{span: 16}}>
          {activeFields.map(field => (
            <Form.Item
              key={field.id}
              label={(
                <span>
                  {field.display_name}
                  {field.is_required && <span style={{color: '#f5222d'}}> *</span>}
                  {field.is_sensitive && (
                    <Tag color="orange" style={{marginLeft: 6}}>敏感</Tag>
                  )}
                  {field.scope_type === 'custom' && (
                    <Tag style={{marginLeft: 6}}>自定义</Tag>
                  )}
                </span>
              )}
              extra={field.help_text}
            >
              {this.renderControl(field)}
            </Form.Item>
          ))}
          {activeFields.length === 0 && (
            <div style={{color: '#999'}}>
              当前系统类型暂无模板字段，可在「系统类型管理」中为类型配置字段模板。
            </div>
          )}
        </Form>
        <AuthDiv auth={PERM.CFG_EDIT} style={{marginTop: 8}}>
          <Button
            type="primary"
            loading={store.isConfigSaving}
            disabled={!hasValues}
            onClick={this.handleSave}
          >
            保存配置
          </Button>
          {hasValues && (
            <Button style={{marginLeft: 8}} onClick={() => this.setState({values: {}})}>
              放弃修改
            </Button>
          )}
        </AuthDiv>
        {inactiveFields.length > 0 && (
          <div style={{marginTop: 24}}>
            <b>已停用字段（历史值保留，只读）</b>
            <Table
              style={{marginTop: 8}}
              size="small"
              rowKey="id"
              pagination={false}
              dataSource={inactiveFields}
              columns={[{
                title: '显示名称', dataIndex: 'display_name', width: 160,
              }, {
                title: '字段编码', dataIndex: 'field_code', width: 160,
              }, {
                title: '类型', dataIndex: 'field_type', width: 90,
                render: v => FIELD_TYPE_TEXT[v] || v,
              }, {
                title: '历史值', key: 'value',
                render: (text, field) => {
                  const entry = config.values[String(field.id)];
                  return entry ? (entry.display || '-') : '-';
                },
              }]}
            />
          </div>
        )}
        {this.state.fieldFormVisible && (
          <CustomFieldForm
            system={config.system}
            record={this.state.fieldRecord}
            onClose={() => this.setState({fieldFormVisible: false})}
            onSaved={() => {
              this.setState({fieldFormVisible: false});
              store.fetchConfig();
            }}
          />
        )}
      </div>
    );
  }
}

function CustomFieldForm(props) {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [typeOverride, setTypeOverride] = useState(null);
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
      setLoading(true);
      const request = isEdit
        ? store.updateCustomField(record.id, data)
        : store.createCustomField(data);
      request
        .then(() => props.onSaved())
        .catch(() => {})
        .finally(() => setLoading(false));
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
        <Form.Item
          name="field_code"
          label="字段编码"
          extra="稳定字段编码，创建后不可修改"
          rules={[
            {required: true, message: '请输入字段编码'},
            {pattern: /^[a-z][a-z0-9_]{0,49}$/, message: '小写字母开头，仅含小写字母、数字、下划线'},
          ]}
        >
          <Input disabled={isEdit}/>
        </Form.Item>
        <Form.Item
          name="display_name"
          label="显示名称"
          rules={[{required: true, message: '请输入显示名称'}, {max: 100, message: '长度不能超过 100'}]}
        >
          <Input/>
        </Form.Item>
        <Form.Item name="field_type" label="字段类型" rules={[{required: true}]}>
          <Select disabled={isEdit} onChange={v => setTypeOverride(v)}>
            {Object.entries(FIELD_TYPE_TEXT).map(([value, label]) => (
              <Select.Option value={value} key={value}>{label}</Select.Option>
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
    </Modal>
  );
}

export default ConfigArchiveTab;

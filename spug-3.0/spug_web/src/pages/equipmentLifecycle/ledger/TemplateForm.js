/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 台账模板新增/编辑弹窗：模板基本信息 + 模板项目表格（一次提交）。
 * 编辑时项目逐条调用项目接口；新建时随模板一次提交。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {
  Modal, Form, Input, Select, InputNumber, Table, Button, Space, Divider, Tag, message,
} from 'antd';
import {PlusOutlined, DeleteOutlined} from '@ant-design/icons';
import {http} from 'libs';
import {
  API_PREFIX_L, CYCLE_TEXT, EXEC_SCOPE_TEXT, INPUT_TYPE_TEXT, LEDGER_TYPE, LEDGER_TYPE_TEXT,
} from './constants';

const {Option} = Select;

const EMPTY_ITEM = () => ({
  key: `it${Date.now()}${Math.random()}`,
  id: undefined,
  item_code: '',
  name: '',
  standard: '',
  input_type: 'text',
  unit: '',
  normal_range: '',
  number_min: null,
  number_max: null,
  choices: [],
  is_required: false,
  execution_scope: 'all',
  abnormal_rule: '',
  operation_guide: '',
  display_order: 0,
});

@observer
class TemplateForm extends React.Component {
  state = {
    loading: false,
    systemTypes: [],
    systems: [],
    items: [],
    template: {
      name: '',
      template_code: '',
      ledger_type: 'inspection',
      maintenance_cycle: '',
      applicable_system_type: undefined,
      applicable_systems: [],
      description: '',
    },
  };

  componentDidMount() {
    http.get(`${API_PREFIX_L}/system-types/`)
      .then(res => this.setState({systemTypes: res.data}))
      .catch(() => {});
    http.get(`${API_PREFIX_L}/systems/`, {params: {page: 1, page_size: 999}})
      .then(res => this.setState({systems: res.data}))
      .catch(() => {});
    const record = this.props.store.record || {};
    if (record.id) {
      this.setState({loading: true});
      http.get(`${API_PREFIX_L}/ledger-templates/${record.id}/`)
        .then(res => {
          this.setState({
            template: {
              name: res.name,
              template_code: res.template_code,
              ledger_type: res.ledger_type,
              maintenance_cycle: res.maintenance_cycle || '',
              applicable_system_type: res.applicable_system_type || undefined,
              applicable_systems: (res.applicable_systems || []).map(s => s.id),
              description: res.description || '',
            },
            items: (res.items || []).map(it => ({...EMPTY_ITEM(), ...it, choices: it.choices || []})),
          });
        })
        .finally(() => this.setState({loading: false}));
    }
  }

  setTemplate = (key, value) => {
    this.setState(prev => ({template: {...prev.template, [key]: value}}));
  };

  setItem = (key, patch) => {
    this.setState(prev => ({
      items: prev.items.map(it => (it.key === key ? {...it, ...patch} : it)),
    }));
  };

  addItem = () => {
    this.setState(prev => ({items: [...prev.items, EMPTY_ITEM()]}));
  };

  removeItem = (key) => {
    this.setState(prev => ({items: prev.items.filter(it => it.key !== key)}));
  };

  submit = () => {
    const {template, items} = this.state;
    const {store} = this.props;
    const isEdit = !!store.record.id;
    this.setState({loading: true});
    const base = {
      ...template,
      maintenance_cycle: template.ledger_type === LEDGER_TYPE.INSPECTION
        ? '' : template.ledger_type === LEDGER_TYPE.SEASONAL ? 'season' : template.maintenance_cycle,
    };
    const request = isEdit
      ? http.put(`${API_PREFIX_L}/ledger-templates/${store.record.id}/`, base)
      : http.post(`${API_PREFIX_L}/ledger-templates/`, {...base, items});
    let saveItems = Promise.resolve();
    if (isEdit) {
      const templateId = store.record.id;
      saveItems = Promise.all(items.map(it => {
        const payload = {...it};
        delete payload.key;
        if (it.id) {
          return http.put(`${API_PREFIX_L}/ledger-templates/${templateId}/items/${it.id}/`, payload);
        }
        return http.post(`${API_PREFIX_L}/ledger-templates/${templateId}/items/`, payload);
      }));
    }
    request
      .then(() => saveItems)
      .then(() => {
        store.formVisible = false;
        store.fetchRecords();
        message.success('保存成功');
      })
      .finally(() => this.setState({loading: false}));
  };

  itemColumns = () => {
    const {template} = this.state;
    const isWeekMonth = template.ledger_type === LEDGER_TYPE.WEEK_MONTH;
    const columns = [
      {
        title: '项目编码', width: 130,
        render: (t, it) => <Input size="small" value={it.item_code} onChange={e => this.setItem(it.key, {item_code: e.target.value})}/>,
      },
      {
        title: '项目名称', width: 150,
        render: (t, it) => <Input size="small" value={it.name} onChange={e => this.setItem(it.key, {name: e.target.value})}/>,
      },
      {
        title: '录入类型', width: 100,
        render: (t, it) => (
          <Select size="small" style={{width: '100%'}} value={it.input_type} onChange={v => this.setItem(it.key, {input_type: v})}>
            {Object.keys(INPUT_TYPE_TEXT).map(k => <Option value={k} key={k}>{INPUT_TYPE_TEXT[k]}</Option>)}
          </Select>
        ),
      },
      {
        title: '单位', width: 80,
        render: (t, it) => <Input size="small" value={it.unit} onChange={e => this.setItem(it.key, {unit: e.target.value})}/>,
      },
      {
        title: '正常范围', width: 110,
        render: (t, it) => <Input size="small" value={it.normal_range} onChange={e => this.setItem(it.key, {normal_range: e.target.value})}/>,
      },
      {
        title: '数值下限/上限', width: 130,
        render: (t, it) => (
          <Space size={4}>
            <InputNumber size="small" style={{width: 60}} value={it.number_min} onChange={v => this.setItem(it.key, {number_min: v})}/>
            <InputNumber size="small" style={{width: 60}} value={it.number_max} onChange={v => this.setItem(it.key, {number_max: v})}/>
          </Space>
        ),
      },
      {
        title: '候选项（逗号分隔）', width: 150,
        render: (t, it) => (
          <Input
            size="small" disabled={!['choice', 'multi_choice'].includes(it.input_type)}
            value={(it.choices || []).join(',')}
            onChange={e => this.setItem(it.key, {choices: e.target.value ? e.target.value.split(',').map(x => x.trim()) : []})}/>
        ),
      },
      {title: '必填', width: 55, align: 'center',
        render: (t, it) => <input type="checkbox" checked={it.is_required} onChange={e => this.setItem(it.key, {is_required: e.target.checked})}/>},
      ...(isWeekMonth ? [{
        title: '执行范围', width: 110,
        render: (t, it) => (
          <Select size="small" style={{width: '100%'}} value={it.execution_scope} onChange={v => this.setItem(it.key, {execution_scope: v})}>
            {Object.keys(EXEC_SCOPE_TEXT).map(k => <Option value={k} key={k}>{EXEC_SCOPE_TEXT[k]}</Option>)}
          </Select>
        ),
      }] : []),
      {
        title: '标准/说明', key: 'std',
        render: (t, it) => (
          <Input size="small" value={it.standard} onChange={e => this.setItem(it.key, {standard: e.target.value})}/>
        ),
      },
      {
        title: '操作', width: 45, align: 'center',
        render: (t, it) => <a style={{color: '#f5222d'}} onClick={() => this.removeItem(it.key)}><DeleteOutlined/></a>,
      },
    ];
    return columns;
  };

  render() {
    const {template, systemTypes, systems, items, loading} = this.state;
    const {store} = this.props;
    const isEdit = !!store.record.id;
    const isWeekMonth = template.ledger_type === LEDGER_TYPE.WEEK_MONTH;
    return (
      <Modal
        title={`${isEdit ? '编辑' : '新增'}台账模板`}
        visible={store.formVisible}
        width={1280}
        confirmLoading={loading}
        maskClosable={false}
        onCancel={() => {
          store.formVisible = false;
        }}
        onOk={this.submit}
        okText="保存">
        <Form layout="inline" style={{marginBottom: 8}}>
          <Form.Item required label="模板名称">
            <Input value={template.name} onChange={e => this.setTemplate('name', e.target.value)}/>
          </Form.Item>
          <Form.Item required label="模板编号">
            <Input
              disabled={isEdit} style={{width: 160}} value={template.template_code}
              onChange={e => this.setTemplate('template_code', e.target.value)}/>
          </Form.Item>
          <Form.Item required label="台账类型">
            <Select
              disabled={isEdit} style={{width: 130}} value={template.ledger_type}
              onChange={v => this.setTemplate('ledger_type', v)}>
              {Object.keys(LEDGER_TYPE_TEXT).map(k => <Option value={k} key={k}>{LEDGER_TYPE_TEXT[k]}</Option>)}
            </Select>
          </Form.Item>
          {isWeekMonth && (
            <Form.Item required label="维护周期">
              <Select
                style={{width: 100}} value={template.maintenance_cycle || undefined}
                onChange={v => this.setTemplate('maintenance_cycle', v)}
                placeholder="周/月">
                <Option value="week">{CYCLE_TEXT.week}</Option>
                <Option value="month">{CYCLE_TEXT.month}</Option>
              </Select>
            </Form.Item>
          )}
          <Form.Item label="适用系统类型">
            <Select
              allowClear style={{width: 180}} value={template.applicable_system_type}
              onChange={v => this.setTemplate('applicable_system_type', v)}>
              {systemTypes.map(t => <Option value={t.id} key={t.id}>{t.name}</Option>)}
            </Select>
          </Form.Item>
          <Form.Item label="适用系统（可多选）">
            <Select
              allowClear mode="multiple" style={{minWidth: 240}} value={template.applicable_systems}
              onChange={v => this.setTemplate('applicable_systems', v)}>
              {systems.map(s => (
                <Option value={s.id} key={s.id}>{s.system_code}｜{s.name}</Option>
              ))}
            </Select>
          </Form.Item>
          <Form.Item label="说明">
            <Input style={{width: 220}} value={template.description} onChange={e => this.setTemplate('description', e.target.value)}/>
          </Form.Item>
        </Form>
        <Divider orientation="left" style={{fontSize: 13, margin: '8px 0'}}>模板项目{isEdit ? '（逐行保存）' : ''}</Divider>
        <div style={{marginBottom: 8}}>
          <Button size="small" type="primary" ghost icon={<PlusOutlined/>} onClick={this.addItem}>添加项目</Button>
          {isEdit && (
            <Tag style={{marginLeft: 8}}>编辑模式下项目修改、新增逐行立即保存</Tag>
          )}
        </div>
        <Table
          rowKey="key" size="small"
          columns={this.itemColumns()}
          dataSource={items}
          pagination={false}
        />
      </Modal>
    );
  }
}

export default TemplateForm;

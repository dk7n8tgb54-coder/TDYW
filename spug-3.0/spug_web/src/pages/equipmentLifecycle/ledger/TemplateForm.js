/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 台账模板新增/编辑弹窗（第一阶段行对象树改造）：两部分结构。
 * - 行结构：行方向多级树（group/repeat_group/check，最大 5 级），
 *   新建随模板一次提交，编辑即时调用行节点接口；
 * - 列检查项目：平面结构（无列分组/列父子，第二阶段范围），
 *   录入类型收敛为 正常/不正常 与 数字/文本 两种。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {
  Modal, Form, Input, Select, Table, Button, Divider, Tag, Tabs, Alert, message,
} from 'antd';
import {PlusOutlined, DeleteOutlined} from '@ant-design/icons';
import {http} from 'libs';
import RowTreeEditor, {annotateNodeTree} from './RowTreeEditor';
import {
  API_PREFIX_L, FLAT_COLUMN_HINT, INPUT_TYPE_TEXT,
  LEDGER_TYPE_TEXT, NORMAL_ABNORMAL_CHOICES, TEMPLATE_INPUT_TYPE_KEYS,
} from './constants';

const {Option} = Select;
const {TabPane} = Tabs;

const EMPTY_ITEM = () => ({
  key: `it${Date.now()}${Math.random()}`,
  id: undefined,
  name: '',
  input_type: 'choice',
  unit: '',
  choices: [...NORMAL_ABNORMAL_CHOICES],
  is_required: true,
  abnormal_rule: '',
  operation_guide: '',
  display_order: 0,
});

/** 服务端行节点树 → 本地编辑树（补 key，保留嵌套 children）。 */
function withNodeKeys(tree) {
  return (tree || []).map(node => ({
    ...node,
    key: `srv${node.id}`,
    children: withNodeKeys(node.children || []),
  }));
}

/** 本地编辑树 → 创建载荷（去 key，display_order 按同级顺序）。 */
function toRowNodesPayload(tree) {
  return (tree || []).map((node, index) => ({
    name: node.name,
    node_type: node.node_type,
    display_order: index,
    children: toRowNodesPayload(node.children || []),
  }));
}

function hasEmptyNodeName(tree) {
  return (tree || []).some(node => !String(node.name || '').trim()
    || hasEmptyNodeName(node.children || []));
}

@observer
class TemplateForm extends React.Component {
  state = {
    loading: false,
    activeTab: 'rows',
    items: [],
    rowTree: [],
    rowTreeVersion: 0,
    template: {
      name: '',
      ledger_type: 'week_month',
      description: '',
    },
  };

  componentDidMount() {
    const record = this.props.store.record || {};
    if (record.id) {
      this.setState({loading: true});
      Promise.all([
        http.get(`${API_PREFIX_L}/ledger-templates/${record.id}/`),
        http.get(`${API_PREFIX_L}/ledger-templates/${record.id}/row-nodes/`),
      ]).then(([res, nodeRes]) => {
        this.setState({
          template: {
            name: res.name,
            ledger_type: res.ledger_type,
            description: res.description || '',
          },
          items: (res.items || []).map(it => ({...EMPTY_ITEM(), ...it, choices: it.choices || []})),
          rowTree: withNodeKeys(nodeRes.data || []),
          rowTreeVersion: this.state.rowTreeVersion + 1,
        });
      }).finally(() => this.setState({loading: false}));
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

  fetchRowNodes = (templateId) => {
    return http.get(`${API_PREFIX_L}/ledger-templates/${templateId}/row-nodes/`)
      .then(res => {
        this.setState(prev => ({
          rowTree: withNodeKeys(res.data || []),
          rowTreeVersion: prev.rowTreeVersion + 1,
        }));
      });
  };

  /** 编辑模式行节点远端动作（新增/编辑/停用/排序），成功后以服务端树为准。 */
  commitRowNode = (action) => {
    const templateId = this.props.store.record.id;
    const base = `${API_PREFIX_L}/ledger-templates/${templateId}/row-nodes`;
    if (action.type === 'create') {
      http.post(`${base}/`, {
        name: action.payload.name,
        node_type: action.payload.node_type,
        parent: action.parent ? action.parent.id : null,
      }).then(() => this.fetchRowNodes(templateId));
    } else if (action.type === 'update') {
      http.put(`${base}/${action.node.id}/`, {
        name: action.node.name,
        node_type: action.node.node_type,
        display_order: action.node.display_order || 0,
      }).then(() => this.fetchRowNodes(templateId));
    } else if (action.type === 'toggle') {
      http.put(`${base}/${action.node.id}/active/`, {is_active: action.node.is_active})
        .then(() => this.fetchRowNodes(templateId));
    } else if (action.type === 'sort') {
      const idByKey = {};
      annotateNodeTree(this.state.rowTree).forEach(node => {
        idByKey[node.key] = node.id;
      });
      const orderedIds = action.orderedKeys.map(k => idByKey[k]).filter(Boolean);
      http.put(`${base}/sort/`, {
        parent: action.parent ? action.parent.id : null,
        ordered_ids: orderedIds,
      }).then(() => this.fetchRowNodes(templateId));
    }
  };

  submit = () => {
    const {template, items, rowTree} = this.state;
    const {store} = this.props;
    if (!String(template.name || '').trim()) {
      message.error('模板名称不能为空');
      return;
    }
    if (hasEmptyNodeName(rowTree)) {
      message.error('行结构存在未命名的行节点，请填写名称');
      this.setState({activeTab: 'rows'});
      return;
    }
    if (!rowTree.length) {
      message.error('请至少配置一个行结构节点（行方向多级对象）');
      this.setState({activeTab: 'rows'});
      return;
    }
    const isEdit = !!store.record.id;
    this.setState({loading: true});
    const request = isEdit
      ? http.put(`${API_PREFIX_L}/ledger-templates/${store.record.id}/`, {...template})
      : http.post(`${API_PREFIX_L}/ledger-templates/`, {
          ...template, items, row_nodes: toRowNodesPayload(rowTree)});
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
    const {items} = this.state;
    // 数字/文本（含历史数值类型）行才涉及单位
    const isMeasureRow = it => it.input_type === 'text' || it.input_type === 'number';
    const hasMeasure = items.some(isMeasureRow);
    const notApplicable = <span style={{color: '#ccc'}}>—</span>;
    const columns = [
      {
        title: '项目名称', width: 150,
        render: (t, it) => <Input size="small" value={it.name} onChange={e => this.setItem(it.key, {name: e.target.value})}/>,
      },
      {
        title: '录入类型', width: 110,
        render: (t, it) => (
          <Select
            size="small" style={{width: '100%'}} value={it.input_type}
            onChange={v => {
              // 切换录入类型时清掉不再适用的字段；正常/不正常候选项固定不可配置
              const patch = {input_type: v};
              if (v !== 'text' && v !== 'number') {
                patch.unit = '';
              }
              patch.choices = v === 'choice' ? [...NORMAL_ABNORMAL_CHOICES] : [];
              this.setItem(it.key, patch);
            }}>
            {TEMPLATE_INPUT_TYPE_KEYS.map(k => <Option value={k} key={k}>{INPUT_TYPE_TEXT[k]}</Option>)}
            {!TEMPLATE_INPUT_TYPE_KEYS.includes(it.input_type) && (
              <Option value={it.input_type} key={it.input_type}>
                {INPUT_TYPE_TEXT[it.input_type] || it.input_type}（历史）
              </Option>
            )}
          </Select>
        ),
      },
      ...(hasMeasure ? [{
        title: '单位', width: 80,
        render: (t, it) => isMeasureRow(it)
          ? <Input size="small" value={it.unit} onChange={e => this.setItem(it.key, {unit: e.target.value})}/>
          : notApplicable,
      }] : []),
      {title: '必填', width: 55, align: 'center',
        render: (t, it) => <input type="checkbox" checked={it.is_required} onChange={e => this.setItem(it.key, {is_required: e.target.checked})}/>},
      {
        title: '操作', width: 45, align: 'center',
        render: (t, it) => <a style={{color: '#f5222d'}} onClick={() => this.removeItem(it.key)}><DeleteOutlined/></a>,
      },
    ];
    return columns;
  };

  render() {
    const {template, items, loading, activeTab, rowTree, rowTreeVersion} = this.state;
    const {store} = this.props;
    const isEdit = !!store.record.id;
    return (
      <Modal
        title={`${isEdit ? '编辑' : '新增'}台账模板`}
        visible={store.formVisible}
        width={1180}
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
          <Form.Item required label="台账类型">
            <Select
              disabled={isEdit} style={{width: 130}} value={template.ledger_type}
              onChange={v => this.setTemplate('ledger_type', v)}>
              {Object.keys(LEDGER_TYPE_TEXT).map(k => <Option value={k} key={k}>{LEDGER_TYPE_TEXT[k]}</Option>)}
            </Select>
          </Form.Item>
          <Form.Item label="说明">
            <Input style={{width: 220}} value={template.description} onChange={e => this.setTemplate('description', e.target.value)}/>
          </Form.Item>
        </Form>
        <Tabs activeKey={activeTab} onChange={k => this.setState({activeTab: k})}>
          <TabPane tab="行结构" key="rows">
            <RowTreeEditor
              tableKey={`rows-${rowTreeVersion}`}
              tree={rowTree}
              remote={isEdit}
              onChange={tree => this.setState({rowTree: tree})}
              onCommit={this.commitRowNode}
            />
          </TabPane>
          <TabPane tab={`列检查项目（${items.length}）`} key="items">
            <Alert type="info" showIcon message={FLAT_COLUMN_HINT} style={{marginBottom: 8}}/>
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
          </TabPane>
        </Tabs>
        {activeTab === 'rows' && !rowTree.length && (
          <Divider style={{margin: '4px 0 0'}} dashed>
            <span style={{color: '#999', fontSize: 12}}>
              尚未配置行结构：可参考 信道（可重复分组）→ 主电台 / 备电台（行对象）
            </span>
          </Divider>
        )}
      </Modal>
    );
  }
}

export default TemplateForm;

/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 台账模板新增/编辑弹窗：可视化表格设计（2026-09-27 第二轮改版）。
 * - 三个区块：基本信息 → 可视化设计表格 → 预览；设计表格即模板编辑主界面，
 *   行（检查对象/分组）与列（检查项目）以及行层级表头名称（如"信道""电台"）
 *   都在与实际台账一致的矩阵表格中配置，不再分设行树/列项目两张独立表格；
 * - 设计表格：行内添加子行/同级行/改名/排序/停用；点击列标题弹出配置气泡
 *   （录入类型/必填/单位/候选项/操作指导/异常规则/默认值）；工具栏"添加列"；
 * - 新建：全部内容（表头 + row_headers + items + row_nodes）随模板一次提交，
 *   后端同事务落库，成功后才提示"保存成功"；
 * - 编辑：保留既有保存时机——行结构修改后立即保存（行节点接口），
 *   层级表头/检查项目随底部「保存基本信息」一并保存；各区块右上角
 *   明确标注实际保存时机，不展示不准确的提示；
 * - 保存前校验：模板名称、至少一个检查对象（分组不生成填写行）、
 *   所有检查项目已命名；错误在对应区块红字提示并滚动定位；
 * - 预览复用 MatrixEditor 只读形态并显示层级表头名称，实时反映
 *   有效检查对象 × 检查项目交叉。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {
  Modal, Form, Input, Select, Tag, message,
} from 'antd';
import {http} from 'libs';
import {annotateNodeTree} from './RowTreeEditor';
import TemplateDesignTable, {makeEmptyColumn} from './TemplateDesignTable';
import TemplatePreview from './TemplatePreview';
import {
  API_PREFIX_L, LEDGER_TYPE_TEXT,
} from './constants';

const {Option} = Select;

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

/** 树中是否存在检查对象（check）节点：只有分组不生成填写行。 */
function hasCheckNode(tree) {
  return (tree || []).some(node => node.node_type === 'check'
    || hasCheckNode(node.children || []));
}

/** 配置区块：序号标题 + 保存时机提示 + 校验错误（红字）+ 滚动定位锚点。 */
function SectionCard({index, title, hint, error, innerRef, children}) {
  return (
    <div ref={innerRef} style={{marginBottom: 20}}>
      <div style={{marginBottom: 8}}>
        <span style={{fontWeight: 600}}>{index}. {title}</span>
        {hint && <Tag style={{marginLeft: 8}}>{hint}</Tag>}
        {error && (
          <span style={{color: '#f5222d', marginLeft: 8, fontSize: 12}}>{error}</span>
        )}
      </div>
      {children}
    </div>
  );
}

@observer
class TemplateForm extends React.Component {
  // 各区块滚动定位锚点（校验失败时定位到出错区块）
  sectionRefs = {
    basic: React.createRef(),
    design: React.createRef(),
  };

  state = {
    loading: false,
    items: [],
    rowTree: [],
    rowTreeVersion: 0,
    rowHeaders: [],
    errors: {},
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
          items: (res.items || []).map(
            it => ({...makeEmptyColumn(), ...it, choices: it.choices || []})),
          rowTree: withNodeKeys(nodeRes.data || []),
          rowHeaders: res.row_headers || [],
          rowTreeVersion: this.state.rowTreeVersion + 1,
        });
      }).finally(() => this.setState({loading: false}));
    }
  }

  clearError = (key) => {
    const current = this.state.errors || {};
    if (!current[key]) return;
    this.setState(prev => {
      const errors = {...prev.errors};
      delete errors[key];
      return {errors};
    });
  };

  setTemplate = (key, value) => {
    this.clearError('basic');
    this.setState(prev => ({template: {...prev.template, [key]: value}}));
  };

  onItemsChange = (items) => {
    this.clearError('items');
    this.setState({items});
  };

  onRowHeadersChange = (rowHeaders) => {
    this.setState({rowHeaders});
  };

  onRowTreeChange = (tree) => {
    this.clearError('rows');
    this.setState({rowTree: tree});
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

  scrollToSection = (key) => {
    // rows/items 校验错误都定位到可视化设计表格区块
    const target = (key === 'rows' || key === 'items') ? 'design' : key;
    const el = this.sectionRefs[target] && this.sectionRefs[target].current;
    if (el && el.scrollIntoView) el.scrollIntoView({behavior: 'smooth', block: 'start'});
  };

  /** 保存前校验；错误写入对应区块并滚动定位，返回是否通过。 */
  validate = () => {
    const {template, items, rowTree} = this.state;
    const isEdit = !!this.props.store.record.id;
    const errors = {};
    if (!String(template.name || '').trim()) {
      errors.basic = '请填写模板名称';
    }
    if (!isEdit) {
      if (!rowTree.length) {
        errors.rows = '请至少添加一个检查对象';
      } else if (hasEmptyNodeName(rowTree)) {
        errors.rows = '请为所有检查对象和分组填写名称';
      } else if (!hasCheckNode(rowTree)) {
        errors.rows = '请至少添加一个检查对象（分组仅用于组织，不生成填写行）';
      }
      if (!items.length) {
        errors.items = '请至少添加一个检查项目';
      } else if (items.some(it => !String(it.name || '').trim())) {
        errors.items = '请填写所有检查项目名称';
      }
    }
    this.setState({errors});
    const firstKey = ['basic', 'rows', 'items'].find(key => errors[key]);
    if (firstKey) {
      message.error(errors[firstKey]);
      this.scrollToSection(firstKey);
      return false;
    }
    return true;
  };

  submit = () => {
    if (!this.validate()) return;
    const {template, items, rowTree, rowHeaders} = this.state;
    const {store} = this.props;
    const isEdit = !!store.record.id;
    // 列项目顺序即本地数组顺序，保存时统一重排 display_order
    const itemPayload = it => {
      const payload = {...it};
      delete payload.key;
      return payload;
    };
    const orderedItems = items.map((it, index) => ({...itemPayload(it), display_order: index}));
    this.setState({loading: true});
    const request = isEdit
      ? http.put(`${API_PREFIX_L}/ledger-templates/${store.record.id}/`,
          {...template, row_headers: rowHeaders})
      : http.post(`${API_PREFIX_L}/ledger-templates/`, {
          ...template,
          row_headers: rowHeaders,
          items: orderedItems,
          row_nodes: toRowNodesPayload(rowTree),
        });
    let saveItems = Promise.resolve();
    if (isEdit) {
      const templateId = store.record.id;
      saveItems = Promise.all(orderedItems.map(payload => {
        if (payload.id) {
          return http.put(
            `${API_PREFIX_L}/ledger-templates/${templateId}/items/${payload.id}/`, payload);
        }
        return http.post(
          `${API_PREFIX_L}/ledger-templates/${templateId}/items/`, payload);
      }));
    }
    request
      .then(() => saveItems)
      .then(() => {
        store.formVisible = false;
        store.fetchRecords();
        message.success(isEdit ? '已保存' : '保存成功');
      })
      .finally(() => this.setState({loading: false}));
  };

  renderBasicSection = (isEdit) => {
    const {template} = this.state;
    return (
      <Form layout="inline" style={{marginBottom: 4}}>
        <Form.Item required label="模板名称">
          <Input
            placeholder="请输入模板名称" value={template.name}
            onChange={e => this.setTemplate('name', e.target.value)}/>
        </Form.Item>
        <Form.Item required label="台账类型">
          <Select
            disabled={isEdit} style={{width: 130}} value={template.ledger_type}
            onChange={v => this.setTemplate('ledger_type', v)}>
            {Object.keys(LEDGER_TYPE_TEXT).map(k => <Option value={k} key={k}>{LEDGER_TYPE_TEXT[k]}</Option>)}
          </Select>
        </Form.Item>
        <Form.Item label="说明">
          <Input
            style={{width: 220}} placeholder="选填" value={template.description}
            onChange={e => this.setTemplate('description', e.target.value)}/>
        </Form.Item>
      </Form>
    );
  };

  render() {
    const {template, items, loading, rowTree, rowTreeVersion, rowHeaders, errors} = this.state;
    const {store} = this.props;
    const isEdit = !!store.record.id;
    return (
      <Modal
        title={`${isEdit ? '编辑' : '新增'}台账模板`}
        visible={store.formVisible}
        width={1180}
        confirmLoading={loading}
        maskClosable={false}
        bodyStyle={{maxHeight: 'calc(100vh - 180px)', overflowY: 'auto'}}
        onCancel={() => {
          store.formVisible = false;
        }}
        onOk={this.submit}
        okText={isEdit ? '保存基本信息' : '保存'}>
        <SectionCard
          index={1} title="基本信息" error={errors.basic}
          hint={isEdit ? '点击底部「保存基本信息」后保存' : null}
          innerRef={this.sectionRefs.basic}>
          {this.renderBasicSection(isEdit)}
        </SectionCard>
        <SectionCard
          index={2} title="可视化设计表格（检查对象 × 检查项目）"
          error={[errors.rows, errors.items].filter(Boolean).join('；') || null}
          hint={isEdit ? '行结构修改后立即保存；层级表头与检查项目随底部「保存基本信息」一并保存' : null}
          innerRef={this.sectionRefs.design}>
          <TemplateDesignTable
            tableKey={`design-${rowTreeVersion}`}
            tree={rowTree}
            items={items}
            rowHeaders={rowHeaders}
            remote={isEdit}
            onChange={this.onRowTreeChange}
            onItemsChange={this.onItemsChange}
            onRowHeadersChange={this.onRowHeadersChange}
            onCommit={this.commitRowNode}
          />
        </SectionCard>
        <SectionCard index={3} title="预览（实际台账效果）">
          <TemplatePreview rows={rowTree} items={items} rowHeaders={rowHeaders}/>
        </SectionCard>
      </Modal>
    );
  }
}

export default TemplateForm;

/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 台账模板可视化设计表格（模板编辑主界面，2026-09-27 改版）。
 * - 与实际台账一致的矩阵形态：行层级独立列 × 平面列项目；
 *   层级列表头即"行层级表头名称"（如"信道""电台"），内联编辑；
 * - 行操作在表格内完成：添加子行 / 添加同级行 / 改名 / 上移下移 /
 *   停用启用 / 删除（仅新建模板的本地草稿）；行方向最多 ROW_MAX_LEVEL 级；
 * - 点击列标题弹出配置气泡（名称/录入类型/必填/单位/候选项/操作指导/
 *   异常判定规则/默认值 + 排序/停用/删除）；工具栏"添加列"；
 * - 新建（remote=false）：全部改动保存在本地，随模板一次提交；
 *   编辑（remote=true）：行结构动作经 onCommit 即时提交后端（远端"添加
 *   同级行"追加到同级末尾，可用上移/下移微调），列配置与层级表头随底部
 *   「保存基本信息」一并保存；
 * - 列方向本阶段保持平面结构：无列分组、无列父子表头，不做任意单元格合并。
 */
import React from 'react';
import {Button, Input, Tag, Tooltip, Dropdown, Menu, Popconfirm, message} from 'antd';
import {
  PlusCircleOutlined, PlusOutlined, ArrowUpOutlined, ArrowDownOutlined,
  StopOutlined, PlayCircleOutlined, DeleteOutlined, DownOutlined,
} from '@ant-design/icons';
import MatrixEditor from './MatrixEditor';
import ColumnConfigPopover from './ColumnConfigPopover';
import {annotateNodeTree, locateSiblings, mapTreeNodes, makeLocalNode,
  defaultNodeName} from './RowTreeEditor';
import {
  NORMAL_ABNORMAL_CHOICES, ROW_MAX_LEVEL, ROW_NODE_TYPE_TEXT,
} from './constants';

const CHILDLESS_TYPE = 'check';

let COLUMN_SEQ = 0;

/** 新建列项目草稿（设计器"添加列"）。 */
export function makeEmptyColumn() {
  COLUMN_SEQ += 1;
  return {
    key: `it${Date.now()}_${COLUMN_SEQ}`,
    id: undefined,
    name: '',
    input_type: 'choice',
    unit: '',
    choices: [...NORMAL_ABNORMAL_CHOICES],
    default_value: '',
    is_required: true,
    abnormal_rule: '',
    operation_guide: '',
    is_active: true,
    display_order: 0,
  };
}

/** 设计树 → MatrixEditor 行：标注 depth/path 与 isCellLeaf（保留停用行）。 */
export function designRows(tree) {
  const walk = nodes => (nodes || []).map(node => ({
    ...node,
    isCellLeaf: node.node_type === CHILDLESS_TYPE,
    children: (node.children || []).length ? walk(node.children) : undefined,
  }));
  return walk(annotateNodeTree(tree));
}

/** 在同级节点 key 之后插入新节点（嵌套层级通用；未命中返回原引用结构）。 */
export function insertSiblingAfter(tree, key, node) {
  const out = [];
  (tree || []).forEach(current => {
    if (current.key === key) {
      out.push(current, node);
      return;
    }
    const children = current.children || [];
    if (!children.length) {
      out.push(current);
      return;
    }
    const next = insertSiblingAfter(children, key, node);
    out.push(next === children ? current : {...current, children: next});
  });
  return out;
}

/** 行/列类型选择下拉：检查对象 / 分组 / 可重复分组。 */
function AddTypeDropdown({onPick, children}) {
  const menu = (
    <Menu onClick={({key}) => onPick(key)}>
      {Object.keys(ROW_NODE_TYPE_TEXT).map(k => (
        <Menu.Item key={k}>{ROW_NODE_TYPE_TEXT[k]}</Menu.Item>))}
    </Menu>
  );
  return <Dropdown overlay={menu} trigger={['click']}>{children}</Dropdown>;
}

export default class TemplateDesignTable extends React.Component {
  static defaultProps = {remote: false, rowHeaders: []};

  nameSnapshot = {key: null, value: ''};

  commit = (action) => {
    if (this.props.onCommit) this.props.onCommit(action);
  };

  // ===== 行结构操作 =====

  patchNode = (row, patch) => {
    this.props.onChange(mapTreeNodes(this.props.tree, row.key, n => ({...n, ...patch})));
  };

  addRoot = (nodeType) => {
    if (this.props.remote) {
      this.commit({type: 'create', parent: null,
        payload: {name: defaultNodeName(nodeType), node_type: nodeType}});
      return;
    }
    this.props.onChange([...(this.props.tree || []), makeLocalNode('', nodeType)]);
  };

  addChild = (parentNode, nodeType) => {
    if (parentNode.level >= ROW_MAX_LEVEL) {
      message.warning(`行节点最多支持 ${ROW_MAX_LEVEL} 级`);
      return;
    }
    if (parentNode.node_type === CHILDLESS_TYPE) {
      message.warning('检查对象不能再包含子项，请先将其改为分组');
      return;
    }
    if (this.props.remote) {
      this.commit({type: 'create', parent: parentNode,
        payload: {name: defaultNodeName(nodeType), node_type: nodeType}});
      return;
    }
    this.props.onChange(mapTreeNodes(this.props.tree, parentNode.key, n => ({
      ...n, children: [...(n.children || []), makeLocalNode('', nodeType)],
    })));
  };

  addSibling = (row, nodeType) => {
    if (this.props.remote) {
      const located = locateSiblings(this.props.tree, row.key);
      this.commit({type: 'create', parent: located ? located.parent : null,
        payload: {name: defaultNodeName(nodeType), node_type: nodeType}});
      return;
    }
    this.props.onChange(insertSiblingAfter(
      this.props.tree, row.key, makeLocalNode('', nodeType)));
  };

  commitName = (row, name) => {
    if (this.props.remote && row.id) {
      this.commit({type: 'update', node: {...row, name}});
    }
  };

  toggleNode = (row) => {
    if (this.props.remote) {
      this.commit({type: 'toggle', node: {...row, is_active: !row.is_active}});
      return;
    }
    this.patchNode(row, {is_active: !row.is_active});
  };

  removeNode = (row) => {
    this.props.onChange(mapTreeNodes(this.props.tree, row.key, () => null));
  };

  moveSibling = (row, direction) => {
    const {tree, remote, onChange} = this.props;
    const located = locateSiblings(tree, row.key);
    if (!located) return;
    const index = located.list.findIndex(n => n.key === row.key);
    const target = index + direction;
    if (target < 0 || target >= located.list.length) return;
    const reordered = [...located.list];
    [reordered[index], reordered[target]] = [reordered[target], reordered[index]];
    const orderedKeys = reordered.map(n => n.key);
    const rebuild = list => orderedKeys
      .map(k => list.find(n => n.key === k))
      .filter(Boolean);
    let nextTree;
    if (located.parent) {
      nextTree = mapTreeNodes(tree, located.parent.key, parent => ({
        ...parent, children: rebuild(parent.children || []),
      }));
    } else {
      nextTree = rebuild(tree);
    }
    onChange(nextTree);
    if (remote) this.commit({type: 'sort', parent: located.parent, orderedKeys});
  };

  // ===== 列项目操作 =====

  patchItem = (key, patch) => {
    this.props.onItemsChange(
      this.props.items.map(it => (it.key === key ? {...it, ...patch} : it)));
  };

  moveItem = (key, direction) => {
    const items = [...this.props.items];
    const index = items.findIndex(it => it.key === key);
    const target = index + direction;
    if (index < 0 || target < 0 || target >= items.length) return;
    [items[index], items[target]] = [items[target], items[index]];
    this.props.onItemsChange(items);
  };

  toggleItemActive = (key) => {
    const hit = this.props.items.find(it => it.key === key) || {};
    this.patchItem(key, {is_active: !hit.is_active});
  };

  removeItem = (key) => {
    this.props.onItemsChange(this.props.items.filter(it => it.key !== key));
  };

  addColumn = () => {
    this.props.onItemsChange([...this.props.items, makeEmptyColumn()]);
  };

  // ===== 表格渲染 =====

  setLevelHeader = (level, name) => {
    const next = [...(this.props.rowHeaders || [])];
    while (next.length < level) next.push('');
    next[level - 1] = name;
    this.props.onRowHeadersChange(next);
  };

  renderLevelTitle = (level) => {
    const value = (this.props.rowHeaders || [])[level - 1] || '';
    return (
      <Tooltip title={`第${level}级行层级表头名称（如"信道"），留空显示"第${level}级"`}>
        <Input placeholder={`第${level}级`} value={value}
               onChange={e => this.setLevelHeader(level, e.target.value)}/>
      </Tooltip>
    );
  };

  renderRowName = row => (
    <Input
      size="small" style={{width: 110}} placeholder="请输入名称"
      value={row.name}
      onFocus={() => { this.nameSnapshot = {key: row.key, value: row.name}; }}
      onChange={e => this.patchNode(row, {name: e.target.value})}
      onBlur={e => {
        const name = String(e.target.value || '').trim();
        if (!name) {
          message.warning('名称不能为空');
          this.patchNode(row, {name: this.nameSnapshot.key === row.key
            ? this.nameSnapshot.value : ''});
          return;
        }
        this.commitName(row, name);
      }}/>
  );

  renderRowTitle = row => (
    row.is_active === false
      ? <Tag color="default" style={{marginRight: 0}}>已停用</Tag> : null);

  renderRowActions = (row) => {
    const {remote} = this.props;
    const canAddChild = row.level < ROW_MAX_LEVEL
      && row.node_type !== CHILDLESS_TYPE;
    return (
      <span className="el-design-row-actions">
        <Tooltip title={canAddChild ? '添加子行' : (
          row.node_type === CHILDLESS_TYPE
            ? '检查对象不能再包含子项' : `最多支持 ${ROW_MAX_LEVEL} 级`)}>
          {canAddChild ? (
            <AddTypeDropdown onPick={t => this.addChild(row, t)}>
              <Button size="small" type="link" className="el-ra-child"
                      icon={<PlusOutlined/>}/>
            </AddTypeDropdown>
          ) : (
            <Button size="small" type="link" className="el-ra-child"
                    icon={<PlusOutlined/>} disabled/>
          )}
        </Tooltip>
        <AddTypeDropdown onPick={t => this.addSibling(row, t)}>
          <Tooltip title="添加同级行">
            <Button size="small" type="link" className="el-ra-sibling"
                    icon={<PlusCircleOutlined/>}/>
          </Tooltip>
        </AddTypeDropdown>
        <Button size="small" type="link" className="el-ra-up" title="上移"
                icon={<ArrowUpOutlined/>} onClick={() => this.moveSibling(row, -1)}/>
        <Button size="small" type="link" className="el-ra-down" title="下移"
                icon={<ArrowDownOutlined/>} onClick={() => this.moveSibling(row, 1)}/>
        <Popconfirm
          title={row.is_active === false
            ? '启用后该项及其子项参与台账生成，确定启用？'
            : '停用后该项及其子项不参与台账生成，确定停用？'}
          onConfirm={() => this.toggleNode(row)}>
          <Button size="small" type="link" className="el-ra-toggle"
                  title={row.is_active === false ? '启用' : '停用'}
                  icon={row.is_active === false ? <PlayCircleOutlined/> : <StopOutlined/>}/>
        </Popconfirm>
        {!remote && (
          <Popconfirm title="确定删除该项（含子项）？" onConfirm={() => this.removeNode(row)}>
            <Button size="small" type="link" className="el-ra-delete"
                    icon={<DeleteOutlined/>}/>
          </Popconfirm>
        )}
      </span>
    );
  };

  matrixColumns = () => this.props.items.map(it => ({
    id: it.key,
    name: String(it.name || '').trim() || '未命名项目',
    input_type: it.input_type,
    unit: it.unit,
    choices: it.choices,
    is_active: it.is_active,
    item: it,
  }));

  renderColumnTitle = (col) => {
    const {remote} = this.props;
    const item = col.item;
    if (!item) return col.name;
    return (
      <ColumnConfigPopover
        item={item}
        onChange={patch => this.patchItem(item.key, patch)}
        onMoveUp={() => this.moveItem(item.key, -1)}
        onMoveDown={() => this.moveItem(item.key, 1)}
        onToggleActive={() => this.toggleItemActive(item.key)}
        onDelete={remote && item.id ? null : () => this.removeItem(item.key)}/>
    );
  };

  render() {
    const {tree} = this.props;
    return (
      <div className="el-template-design">
        <div style={{marginBottom: 8}}>
          <Button size="small" type="primary" ghost icon={<PlusOutlined/>}
                  onClick={() => this.addRoot('check')}>
            添加检查对象
          </Button>
          <AddTypeDropdown onPick={key => this.addRoot(key)}>
            <Button size="small" style={{marginLeft: 8}}>
              添加分组 <DownOutlined/>
            </Button>
          </AddTypeDropdown>
          <Button size="small" style={{marginLeft: 8}} icon={<PlusOutlined/>}
                  onClick={this.addColumn}>
            添加列
          </Button>
          <span style={{marginLeft: 8, color: '#999', fontSize: 12}}>
            检查对象生成表格的填写行；分组仅用于组织（可重复分组在实际台账中可创建多个实例，
            如"信道"）；点击列标题配置该列；行最多 {ROW_MAX_LEVEL} 级。
          </span>
        </div>
        <MatrixEditor
          columns={this.matrixColumns()}
          rows={designRows(tree)}
          readOnly
          getCell={() => null}
          levelColumnWidth={140}
          renderRowName={this.renderRowName}
          renderRowTitle={this.renderRowTitle}
          renderRowActions={this.renderRowActions}
          renderLevelTitle={this.renderLevelTitle}
          renderColumnTitle={this.renderColumnTitle}
        />
      </div>
    );
  }
}

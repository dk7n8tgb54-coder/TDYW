/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 台账模板行结构树编辑器（第一阶段行方向多级结构）。
 * - 树形表格：名称/类型/层级/路径/子节点数/同级排序/停用；
 * - 新建模板（remote=false）：树在本地编辑，随模板一次提交；
 * - 编辑模板（remote=true）：新增/停用/排序即时提交后端并刷新；
 *   名称、类型本地改后失焦/切换即提交；
 * - 约束：最大层级 ROW_MAX_LEVEL、check 不能包含子节点。
 */
import React from 'react';
import {Table, Input, Select, Button, Tooltip, Popconfirm, message} from 'antd';
import {
  PlusOutlined, ArrowUpOutlined, ArrowDownOutlined,
  StopOutlined, PlayCircleOutlined, DeleteOutlined,
} from '@ant-design/icons';
import {ROW_MAX_LEVEL, ROW_NODE_TYPE_TEXT} from './constants';

const {Option} = Select;

let NODE_SEQ = 0;

export function newNodeKey() {
  NODE_SEQ += 1;
  return `n${Date.now()}_${NODE_SEQ}`;
}

export function makeLocalNode(name = '', node_type = 'group', children = []) {
  return {key: newNodeKey(), id: undefined, name, node_type, display_order: 0,
    is_active: true, children};
}

/** 树 → 表格数据源：每个节点原地附带 depth/level/path/childrenCount（保持嵌套）。 */
export function annotateNodeTree(tree, prefix = '', depth = 1) {
  return (tree || []).map(node => {
    const path = prefix ? `${prefix} / ${node.name}` : node.name;
    const children = annotateNodeTree(node.children || [], path, depth + 1);
    return {...node, path, depth, level: depth, childrenCount: (node.children || []).length,
      children: children.length ? children : undefined};
  });
}

/** 不可变树操作：按 key 映射节点（返回 null 表示删除）。 */
export function mapTreeNodes(tree, key, transform) {
  const next = [];
  (tree || []).forEach(node => {
    if (node.key === key) {
      const result = transform(node);
      if (result) next.push(result);
      return;
    }
    const children = node.children || [];
    if (!children.length) {
      next.push(node);
      return;
    }
    const nextChildren = mapTreeNodes(children, key, transform);
    next.push(nextChildren === children ? node : {...node, children: nextChildren});
  });
  return next;
}

/** 定位节点所在的同级数组与父节点（根级 parent 为 null）。 */
export function locateSiblings(tree, key, parent = null) {
  for (const node of tree || []) {
    if (node.key === key) return {list: tree, parent};
    const hit = locateSiblings(node.children || [], key, node);
    if (hit) return hit;
  }
  return null;
}

const CHILDLESS_TYPES = ['check'];

export default class RowTreeEditor extends React.Component {
  static defaultProps = {remote: false};

  /** 本地树更新 + 可选远端动作（remote 模式由父组件提交后刷新树）。 */
  apply = (nextTree, commit) => {
    const {onChange, onCommit} = this.props;
    if (nextTree !== null && onChange) onChange(nextTree);
    if (commit && onCommit) onCommit(commit);
  };

  patchLocal = (node, patch) => {
    const {tree} = this.props;
    this.apply(mapTreeNodes(tree, node.key, n => ({...n, ...patch})), null);
  };

  addRoot = () => {
    const {remote} = this.props;
    const node = makeLocalNode('', 'group');
    if (remote) {
      this.apply(null, {type: 'create', parent: null,
        payload: {name: '新行节点', node_type: 'group'}});
      return;
    }
    this.apply([...this.props.tree, node], null);
  };

  addChild = (parentNode) => {
    const {remote} = this.props;
    if (parentNode.depth >= ROW_MAX_LEVEL) {
      message.warning(`行结构最多支持 ${ROW_MAX_LEVEL} 级`);
      return;
    }
    if (CHILDLESS_TYPES.includes(parentNode.node_type)) {
      message.warning('行对象（check）节点不能包含子节点，请先改为行分组');
      return;
    }
    if (remote) {
      this.apply(null, {type: 'create', parent: parentNode,
        payload: {name: '新行节点', node_type: 'check'}});
      return;
    }
    const node = makeLocalNode('', 'check');
    this.apply(mapTreeNodes(this.props.tree, parentNode.key, n => ({
      ...n, children: [...(n.children || []), node],
    })), null);
  };

  commitName = (row) => {
    const name = String(row.name || '').trim();
    if (!name) {
      message.warning('行节点名称不能为空');
      this.patchLocal(row, {name: row._lastValidName || row.name});
      return;
    }
    if (this.props.remote && row.id) {
      this.apply(null, {type: 'update', node: {...row, name}});
    }
  };

  changeType = (row, nodeType) => {
    if (nodeType === 'check' && (row.children || []).length) {
      message.warning('该节点存在子节点，不能设置为行对象（check）');
      return;
    }
    this.patchLocal(row, {node_type: nodeType, is_repeatable: nodeType === 'repeat_group'});
    if (this.props.remote && row.id) {
      this.apply(null, {type: 'update',
        node: {...row, node_type: nodeType, is_repeatable: nodeType === 'repeat_group'}});
    }
  };

  removeNode = (node) => {
    this.apply(mapTreeNodes(this.props.tree, node.key, () => null), null);
  };

  toggleNode = (node) => {
    this.apply(null, {type: 'toggle', node: {...node, is_active: !node.is_active}});
  };

  moveSibling = (node, direction) => {
    const {tree, remote} = this.props;
    const located = locateSiblings(tree, node.key);
    if (!located) return;
    const index = located.list.findIndex(n => n.key === node.key);
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
    this.apply(nextTree, remote ? {type: 'sort', parent: located.parent,
      orderedKeys} : null);
  };

  columns = () => {
    const {remote} = this.props;
    return [
      {
        title: '名称', key: 'name', width: 180,
        render: (t, row) => (
          <Input
            size="small" placeholder="节点名称" value={row.name}
            onChange={e => this.patchLocal(row, {name: e.target.value})}
            onBlur={e => this.commitName({...row, name: e.target.value})}/>
        ),
      },
      {
        title: '类型', key: 'node_type', width: 130,
        render: (t, row) => (
          <Select
            size="small" style={{width: '100%'}} value={row.node_type}
            onChange={v => this.changeType(row, v)}>
            {Object.keys(ROW_NODE_TYPE_TEXT).map(k => (
              <Option value={k} key={k}
                      disabled={k === 'check' && (row.children || []).length > 0}>
                {ROW_NODE_TYPE_TEXT[k]}
              </Option>
            ))}
          </Select>
        ),
      },
      {title: '层级', key: 'level', width: 60, align: 'center',
        render: (t, row) => row.level},
      {
        title: '路径', key: 'path', width: 220, ellipsis: true,
        render: (t, row) => <span style={{color: '#888'}}>{row.path}</span>,
      },
      {title: '子节点数', key: 'children_count', width: 80, align: 'center',
        render: (t, row) => row.childrenCount},
      {
        title: '排序', key: 'order', width: 90, align: 'center',
        render: (t, row) => (
          <span>
            <Button size="small" type="link" icon={<ArrowUpOutlined/>}
                    onClick={() => this.moveSibling(row, -1)}/>
            <Button size="small" type="link" icon={<ArrowDownOutlined/>}
                    onClick={() => this.moveSibling(row, 1)}/>
          </span>
        ),
      },
      {
        title: '操作', key: 'action', width: 170, align: 'center',
        render: (t, row) => {
          const atMaxDepth = row.level >= ROW_MAX_LEVEL;
          const addDisabled = atMaxDepth || CHILDLESS_TYPES.includes(row.node_type);
          const addReason = atMaxDepth ? `最多 ${ROW_MAX_LEVEL} 级`
            : '行对象节点不能包含子节点';
          return (
            <span>
              <Tooltip title={addDisabled ? addReason : '添加子行节点'}>
                <Button size="small" type="link" icon={<PlusOutlined/>}
                        disabled={addDisabled} onClick={() => this.addChild(row)}/>
              </Tooltip>
              {remote ? (
                <Popconfirm
                  title={row.is_active ? '停用后该节点不参与台账生成，确定停用？' : '确定启用？'}
                  onConfirm={() => this.toggleNode(row)}>
                  <Button size="small" type="link"
                          icon={row.is_active ? <StopOutlined/> : <PlayCircleOutlined/>}>
                    {row.is_active ? '停用' : '启用'}
                  </Button>
                </Popconfirm>
              ) : (
                <Popconfirm title="确定删除该节点（含子节点）？" onConfirm={() => this.removeNode(row)}>
                  <Button size="small" type="link" icon={<DeleteOutlined/>}/>
                </Popconfirm>
              )}
            </span>
          );
        },
      },
    ];
  };

  render() {
    const {tree, tableKey} = this.props;
    const dataSource = annotateNodeTree(tree);
    return (
      <div>
        <div style={{marginBottom: 8}}>
          <Button size="small" type="primary" ghost icon={<PlusOutlined/>} onClick={this.addRoot}>
            添加根级行节点
          </Button>
          <span style={{marginLeft: 8, color: '#999', fontSize: 12}}>
            行方向最多 {ROW_MAX_LEVEL} 级；"行对象"为生成填写单元格的行叶子，"可重复分组"在实际台账中可创建多个实例（如多个信道）。
          </span>
        </div>
        <Table
          key={tableKey || 'row-tree'}
          rowKey="key" size="small"
          columns={this.columns()}
          dataSource={dataSource}
          pagination={false}
          defaultExpandAllRows
        />
      </div>
    );
  }
}

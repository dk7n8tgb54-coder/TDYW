/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 运维台账录入/编辑表单（第一阶段行对象树矩阵改造）：
 * - 新增：选择模板 → 预览生成"行路径 × 平面列项目"矩阵（计划实例态），
 *   列项目只配置一次、被所有行对象（主/备电台）复用；可新增/删除/重命名
 *   可重复分组实例（如第1/第2信道）；提交按系统拆分立账（每系统一条台账，
 *   client_token 幂等），行实例规格与已填单元格随创建载荷提交；
 * - 编辑（矩阵草稿）：行实例树 + 单元格即台账明细，单元格改动经
 *   /cells/ 接口一次保存；实例增删/重命名即时调用行实例接口；
 * - 编辑（历史草稿，无行实例）：旧结构不再提供矩阵编辑；
 * - 单元格结果：填写值派生（单选"不正常"→异常），未填写保持"未填写"，
 *   一键正常仅作用于未填写单元格；
 * - 周月维护不再选择维护周期（2026-09-26）：周表/月表合一，
 *   模板加载与预览仅按 ledger_type 区分。
 */
import React from 'react';
import {observer} from 'mobx-react';
import {
  Modal, Form, Input, Select, Button, Radio, Space, Divider, Alert, message, Popconfirm, Tag,
} from 'antd';
import {PlusOutlined, DeleteOutlined} from '@ant-design/icons';
import {http} from 'libs';
import MatrixEditor from './MatrixEditor';
import {
  API_PREFIX_L, LEDGER_TYPE_TEXT, MATRIX_FILTER_MODES,
} from './constants';
import {
  cellLooksAbnormal, cellValueEmpty, clonePlanned, filterMatrixRows, flattenPlanned,
  plannedCellKey, plannedFromRowNodes, rowProgress, buildRowSpec, todayStr,
} from './ledgerCommon';

const {Option} = Select;

const EMPTY_CELL = {value_text: '', value_number: null, value_bool: null, result: ''};

/** 服务端行节点树 → MatrixEditor 行（计划实例树，带 key/path/depth）。 */
function plannedRows(plannedTree, pathPrefix = '', depth = 1) {
  return (plannedTree || []).map(p => {
    const path = pathPrefix ? `${pathPrefix} / ${p.name}` : p.name;
    return {
      key: p.key,
      planned: p,
      name: p.name,
      path,
      depth,
      nodeType: p.node_type,
      isCellLeaf: p.node_type === 'check',
      children: plannedRows(p.children, path, depth + 1),
    };
  });
}

/** 详情行实例树 → MatrixEditor 行（编辑态）。 */
function instanceRows(instances, depth = 1) {
  return (instances || []).map(inst => ({
    key: `i${inst.id}`,
    instanceId: inst.id,
    name: inst.instance_name,
    path: inst.row_path,
    depth: inst.row_level || depth,
    templateNodeId: inst.template_node,
    isCellLeaf: !(inst.children || []).length,
    children: instanceRows(inst.children, depth + 1),
  }));
}

function plannedSiblingCount(plannedTree, key) {
  const find = list => {
    for (const p of list) {
      if (p.key === key) return list.length;
      const hit = find(p.children || []);
      if (hit) return hit;
    }
    return null;
  };
  return find(plannedTree || []) || 0;
}

function removeFromPlanned(plannedTree, key) {
  return (plannedTree || [])
    .filter(p => p.key !== key)
    .map(p => ({...p, children: removeFromPlanned(p.children, key)}));
}

function renamePlanned(plannedTree, key, name) {
  return (plannedTree || []).map(p => ({
    ...p,
    name: p.key === key ? name : p.name,
    children: renamePlanned(p.children, key, name),
  }));
}

function findPlanned(plannedTree, key) {
  for (const p of plannedTree || []) {
    if (p.key === key) return p;
    const hit = findPlanned(p.children, key);
    if (hit) return hit;
  }
  return null;
}

/** 在 afterKey 节点之后插入克隆实例（根级与嵌套同级通用）。 */
function insertAfterPlanned(list, afterKey, clone) {
  const out = [];
  (list || []).forEach(p => {
    const children = insertAfterPlanned(p.children || [], afterKey, clone);
    out.push(children === (p.children || []) ? p : {...p, children});
    if (p.key === afterKey) out.push(clone);
  });
  return out;
}

@observer
class LedgerForm extends React.Component {
  state = {
    loading: false,
    systems: [],
    templates: [],
    templateId: undefined,
    header: {
      executed_date: todayStr(),
      executed_start: null,
      executed_end: null,
      executor_names: '',
    },
    // 计划态（新增）
    preview: null,       // {template, row_nodes, items}
    planned: [],         // 计划实例树
    cellValues: {},      // `${plannedKey}|${itemId}` → cell
    // 编辑态
    editMode: null,      // 'matrix' | 'legacy'
    detail: null,
    columns: [],         // 列项目视图
    cellsMap: {},        // `${instanceId}|${itemId}` → 台账明细
    cellEdits: {},       // 编辑态本地改动
    repeatNodes: [],     // 可重复分组节点（实例新增入口）
    version: undefined,
    filterMode: 'all',
    submitToken: null,
  };

  componentDidMount() {
    const record = this.props.store.record || {};
    http.get(`${API_PREFIX_L}/systems/`, {params: {page: 1, page_size: 999}})
      .then(res => this.setState({systems: res.data}))
      .catch(() => {});
    if (record.id) {
      this.setState({loading: true});
      http.get(`${API_PREFIX_L}/ledgers/${record.id}/`)
        .then(res => this.setupEdit(res))
        .finally(() => this.setState({loading: false}));
    } else {
      this.fetchTemplates().then(templates => this.setState({templates}));
    }
  }

  setupEdit = (res) => {
    const hasInstances = (res.row_instances || []).length > 0;
    if (!hasInstances) {
      this.setState({editMode: 'legacy', detail: res});
      return;
    }
    // 列顺序：明细按 叶子×列 生成，取首个行实例的单元格顺序即模板列顺序
    const firstRowCells = res.items.filter(c => c.row_instance === res.items[0].row_instance);
    const columns = firstRowCells.map(c => ({
      id: c.template_item,
      name: c.column_name || c.item_name,
      input_type: c.input_type,
      unit: c.unit || '',
      choices: c.choices || [],
      is_required: c.is_required,
      operation_guide: c.operation_guide || '',
      abnormal_rule: c.abnormal_rule || '',
    }));
    const cellsMap = {};
    res.items.forEach(c => {
      if (c.row_instance) cellsMap[`${c.row_instance}|${c.template_item}`] = c;
    });
    this.setState({
      editMode: 'matrix',
      detail: res,
      columns,
      cellsMap,
      version: res.version,
      header: {
        executed_date: res.executed_date,
        executed_start: res.executed_start,
        executed_end: res.executed_end,
        executor_names: res.executor_names || '',
      },
    });
    this.fetchRepeatNodes(res.template);
  };

  fetchRepeatNodes = (templateId) => {
    if (!templateId) return;
    http.get(`${API_PREFIX_L}/ledger-templates/${templateId}/row-nodes/`)
      .then(res => {
        const repeatNodes = [];
        const walk = nodes => (nodes || []).forEach(n => {
          if (n.node_type === 'repeat_group' && n.is_active) repeatNodes.push(n);
          walk(n.children);
        });
        walk(res.data || []);
        this.setState({repeatNodes});
      })
      .catch(() => {});
  };

  fetchTemplates = () => {
    const {store} = this.props;
    let url = `${API_PREFIX_L}/ledger-templates/available/?ledger_type=${store.ledgerType}`;
    return http.get(url).then(res => res.data).catch(() => []);
  };

  setHeader = (key, value) => {
    this.setState(prev => ({header: {...prev.header, [key]: value}}));
  };

  generatePreview = () => {
    const {templateId, systems} = this.state;
    const {store} = this.props;
    if (!templateId) {
      message.error('请先选择模板');
      return;
    }
    const activeSystems = systems.filter(s => s.is_active !== false);
    if (!activeSystems.length) {
      message.error('系统档案中没有可用系统，请先维护系统');
      return;
    }
    this.setState({loading: true});
    http.post(`${API_PREFIX_L}/ledgers/preview/`, {
      ledger_type: store.ledgerType,
      entries: activeSystems.map(s => ({system_id: s.id, template_id: templateId})),
    }).then(res => {
      const entry = (res.data || [])[0];
      if (!entry || !(entry.items || []).length) {
        message.warning('所选模板没有启用的列项目');
        return;
      }
      if (!entry.is_matrix) {
        message.warning('该模板未配置行结构（旧模板已停用），请选择新模板');
        return;
      }
      this.setState({
        preview: entry,
        columns: entry.items || [],
        planned: plannedFromRowNodes(entry.row_nodes || []),
        cellValues: {},
      });
    }).finally(() => this.setState({loading: false}));
  };

  // ===== 计划实例操作 =====

  addPlannedInstance = (row) => {
    // 复制同级实例（可重复分组）：新增"第N信道"类实例，子树一并实例化
    const {planned} = this.state;
    const target = row.planned;
    const clone = clonePlanned(target);
    clone.name = `${target.name}${plannedSiblingCount(planned, target.key) + 1}`;
    this.setState({planned: insertAfterPlanned(planned, target.key, clone)});
  };

  removePlannedInstance = (row) => {
    this.setState(prev => ({planned: removeFromPlanned(prev.planned, row.key)}));
  };

  renamePlannedInstance = (row, name) => {
    this.setState(prev => ({planned: renamePlanned(prev.planned, row.key, name)}));
  };

  // ===== 单元格操作 =====

  getPlannedCell = (row, column) => {
    const stored = this.state.cellValues[plannedCellKey(row.key, column.id)];
    // 附带列录入类型：单元格判定（异常提示/多选空数组）依赖 input_type
    return {...EMPTY_CELL, input_type: column.input_type, ...(stored || {})};
  };

  setPlannedCell = (row, column, patch) => {
    const key = plannedCellKey(row.key, column.id);
    this.setState(prev => ({
      cellValues: {...prev.cellValues, [key]: {...EMPTY_CELL, ...prev.cellValues[key], ...patch}},
    }));
  };

  getEditCell = (row, column) => {
    const key = `${row.instanceId}|${column.id}`;
    const base = this.state.cellsMap[key];
    const patch = this.state.cellEdits[key];
    if (!base && !patch) return null;
    return {...EMPTY_CELL, ...(base || {}), ...(patch || {})};
  };

  setEditCell = (row, column, patch) => {
    const key = `${row.instanceId}|${column.id}`;
    this.setState(prev => ({
      cellEdits: {...prev.cellEdits, [key]: {...(prev.cellEdits[key] || {}), ...patch}},
    }));
  };

  confirmNormalPlanned = () => {
    // 一键正常（计划态）：仅未填写单元格显式置为正常（全部行叶子 × 列项目）
    const {planned, cellValues, preview} = this.state;
    const leaves = flattenPlanned(planned).filter(p => p.node_type === 'check');
    const next = {...cellValues};
    let count = 0;
    leaves.forEach(leaf => {
      ((preview && preview.items) || []).forEach(col => {
        const key = plannedCellKey(leaf.key, col.id);
        const cell = {...EMPTY_CELL, ...(next[key] || {})};
        if (cellValueEmpty(cell) && !cell.result) {
          next[key] = {...cell, result: 'normal'};
          count += 1;
        }
      });
    });
    this.setState({cellValues: next});
    message.success(`已将 ${count} 个未填写单元格标记为正常`);
  };

  confirmNormalEdit = () => {
    const {cellsMap, cellEdits} = this.state;
    const unsetIds = [];
    Object.keys(cellsMap).forEach(key => {
      const cell = {...cellsMap[key], ...(cellEdits[key] || {})};
      if (cellValueEmpty(cell) && !cell.result) unsetIds.push(cellsMap[key].id);
    });
    if (!unsetIds.length) {
      message.warning('没有未填写的单元格');
      return;
    }
    http.post(`${API_PREFIX_L}/ledgers/${this.state.detail.id}/confirm-normal/`, {item_ids: unsetIds})
      .then(res => this.applyDetail(res.data));
  };

  applyDetail = (detail) => {
    // 实例操作/单元格保存后以后端返回重建本地状态（保留未保存的单元格改动）
    const firstRowCells = detail.items.filter(
      c => c.row_instance === (detail.items[0] || {}).row_instance);
    const columns = this.state.columns.length ? this.state.columns : firstRowCells.map(c => ({
      id: c.template_item, name: c.column_name || c.item_name, input_type: c.input_type,
      unit: c.unit || '', choices: c.choices || [], is_required: c.is_required,
      operation_guide: c.operation_guide || '', abnormal_rule: c.abnormal_rule || '',
    }));
    const cellsMap = {};
    detail.items.forEach(c => {
      if (c.row_instance) cellsMap[`${c.row_instance}|${c.template_item}`] = c;
    });
    this.setState({detail, columns, cellsMap, version: detail.version});
  };

  saveEditCells = () => {
    const {cellEdits, detail, header} = this.state;
    const values = Object.keys(cellEdits).map(key => ({
      id: (this.state.cellsMap[key] || {}).id,
      ...cellEdits[key],
    })).filter(v => v.id);
    this.setState({loading: true});
    http.put(`${API_PREFIX_L}/ledgers/${detail.id}/cells/`, {
      version: this.state.version,
      executed_date: header.executed_date,
      executor_names: header.executor_names,
      values,
    }).then(res => {
      this.setState({cellEdits: {}});
      this.applyDetail(res.data);
      message.success('保存成功');
    }).finally(() => this.setState({loading: false}));
  };

  // ===== 行实例（编辑态） =====

  addInstance = (node) => {
    const count = this.countInstancesOf(node.id) + 1;
    http.post(`${API_PREFIX_L}/ledgers/${this.state.detail.id}/row-instances/`, {
      template_node: node.id,
      name: `${node.name}${count}`,
    }).then(res => {
      this.applyDetail(res.data);
      message.success(`已添加${node.name}实例（${node.name}${count}）`);
    });
  };

  countInstancesOf = (nodeId) => {
    const count = list => (list || []).reduce(
      (acc, i) => acc + (i.template_node === nodeId ? 1 : 0) + count(i.children || []), 0);
    return count((this.state.detail || {}).row_instances || []);
  };

  renameInstance = (row, name) => {
    http.put(`${API_PREFIX_L}/ledgers/${this.state.detail.id}/row-instances/${row.instanceId}/`,
      {instance_name: name})
      .then(res => this.applyDetail(res.data));
  };

  deleteInstance = (row) => {
    http.delete(`${API_PREFIX_L}/ledgers/${this.state.detail.id}/row-instances/${row.instanceId}/`)
      .then(res => {
        this.applyDetail(res.data);
        message.success('已删除实例及其单元格');
      });
  };

  // ===== 提交 =====

  submit = () => {
    const {store} = this.props;
    const {header, editMode} = this.state;
    if (editMode === 'matrix') {
      this.saveEditCells();
      return;
    }
    if (editMode === 'legacy') {
      message.warning('历史台账（旧结构）不支持在矩阵表单中编辑');
      return;
    }
    if (!header.executed_date) {
      message.error('请填写实际执行日期');
      return;
    }
    const {preview, planned, cellValues, systems} = this.state;
    if (!preview) {
      message.error('请先生成矩阵预览');
      return;
    }
    const spec = buildRowSpec(planned);
    if (!spec.length) {
      message.error('请至少保留一个行实例');
      return;
    }
    // 已填单元格：路径取填写时的行叶子路径，列以模板项目 ID 对齐
    const leaves = flattenPlanned(planned).filter(p => p.node_type === 'check');
    const values = [];
    leaves.forEach(leaf => {
      (preview.items || []).forEach(col => {
        const cell = {...EMPTY_CELL, ...(cellValues[plannedCellKey(leaf.key, col.id)] || {})};
        if (cellValueEmpty(cell) && !cell.result) return;
        values.push({
          path: leaf.path, column_id: col.id,
          value_text: cell.value_text, value_number: cell.value_number,
          value_bool: cell.value_bool, result: cell.result || undefined,
          abnormal_desc: cell.abnormal_desc || undefined,
        });
      });
    });
    const activeSystems = systems.filter(s => s.is_active !== false);
    if (!activeSystems.length) {
      message.error('系统档案中没有可用系统，请先维护系统');
      return;
    }
    this.setState({loading: true});
    if (!this.state.submitToken) {
      this.setState({submitToken: `lf_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`});
    }
    const token = this.state.submitToken;
    // 按系统拆分立账（语义不变）：每系统一条台账；行实例规格与单元格值一致
    const payload = {
      ledger_type: store.ledgerType,
      created_from: 'template',
      executed_date: header.executed_date,
      executed_start: header.executed_start,
      executed_end: header.executed_end,
      executor_names: header.executor_names,
      template_id: preview.template.id,
      row_instances: spec,
      values,
    };
    const posts = activeSystems.map(s => http.post(`${API_PREFIX_L}/ledgers/`, {
      ...payload,
      client_token: `${token}_s${s.id}`,
      system_id: s.id,
    }));
    Promise.all(posts).then(() => {
      store.formVisible = false;
      store.fetchRecords();
      message.success('保存成功');
    }).catch(() => {
      // 业务错误提示由 http 拦截器统一弹出；不重复提示、不乐观关闭弹窗
    }).finally(() => this.setState({loading: false}));
  };

  // ===== 渲染 =====

  renderHeader = () => {
    const {header} = this.state;
    const {store} = this.props;
    const isEdit = !!store.record.id;
    return (
      <Form layout="inline" style={{marginBottom: 8}} className="el-ledger-header-form">
        <Form.Item required label="实际执行日期">
          <Input
            style={{width: 130}}
            type="date"
            value={header.executed_date || ''}
            onChange={e => this.setHeader('executed_date', e.target.value)}/>
        </Form.Item>
        <Form.Item label="执行人">
          <Input style={{width: 150}} value={header.executor_names} onChange={e => this.setHeader('executor_names', e.target.value)}/>
        </Form.Item>
      </Form>
    );
  };

  renderTemplateSection = () => {
    const {templates, templateId, preview} = this.state;
    const {store} = this.props;
    if (store.record.id) return null;
    return (
      <div style={{marginBottom: 12}}>
        <Divider orientation="left" style={{fontSize: 13, margin: '12px 0 8px'}}>通过模板生成矩阵台账</Divider>
        <Space>
          <Select
            style={{width: 260}} placeholder="选择模板（需配置行结构）"
            value={templateId}
            onChange={v => this.setState({templateId: v, preview: null, planned: [], cellValues: {}})}>
            {templates.map(t => (
              <Option value={t.id} key={t.id}>{t.name}（{t.items_count} 项）</Option>
            ))}
          </Select>
          <Button type="primary" ghost onClick={this.generatePreview} loading={this.state.loading}>
            生成矩阵预览
          </Button>
        </Space>
        {preview && (
          <div style={{marginTop: 4, color: '#999', fontSize: 12}}>
            模板：{preview.template.name}；列项目在模板中只配置一次，所有行对象复用同一组列。
          </div>
        )}
      </div>
    );
  };

  plannedRowActions = (row) => {
    if (row.nodeType !== 'repeat_group') return null;
    const siblingCount = plannedSiblingCount(this.state.planned, row.planned.key);
    return (
      <span>
        <a onClick={() => this.addPlannedInstance(row)}>添加{row.name}</a>
        {siblingCount > 1 && (
          <Popconfirm title={`确定删除该${row.name}实例及其全部单元格？`}
                      onConfirm={() => this.removePlannedInstance(row)}>
            <a style={{color: '#f5222d', marginLeft: 8}}><DeleteOutlined/></a>
          </Popconfirm>
        )}
      </span>
    );
  };

  editRowActions = (row) => {
    const {repeatNodes} = this.state;
    const actions = [];
    // 可重复分组实例提供"新增同级实例"入口
    if (row.templateNodeId && repeatNodes.some(n => n.id === row.templateNodeId)) {
      const node = repeatNodes.find(n => n.id === row.templateNodeId);
      actions.push(<a key="add" onClick={() => this.addInstance(node)}>添加{node.name}</a>);
    }
    if (this.countSiblings(row) > 1) {
      actions.push(
        <Popconfirm key="del" title="确定删除该实例及其全部单元格？"
                    onConfirm={() => this.deleteInstance(row)}>
          <a style={{color: '#f5222d', marginLeft: 8}}><DeleteOutlined/></a>
        </Popconfirm>);
    }
    return <span>{actions}</span>;
  };

  countSiblings = (row) => {
    const find = list => {
      for (const inst of list || []) {
        if (inst.id === row.instanceId) return (list || []).length;
        const hit = find(inst.children || []);
        if (hit) return hit;
      }
      return null;
    };
    return find((this.state.detail || {}).row_instances || []) || 1;
  };

  renderFilterBar = (rows, getCell, onConfirmNormal) => {
    const {filterMode} = this.state;
    const abnormalCount = this.countCells(rows, c => cellLooksAbnormal(c), getCell);
    const unsetCount = this.countCells(rows, c => cellValueEmpty(c) && !c.result, getCell);
    return (
      <div style={{marginBottom: 8}}>
        <Radio.Group
          size="small" value={filterMode}
          onChange={e => this.setState({filterMode: e.target.value})}>
          {MATRIX_FILTER_MODES.map(m => (
            <Radio.Button value={m.key} key={m.key}>
              {m.text}{m.key === 'abnormal' && abnormalCount > 0 ? `（${abnormalCount}）` : ''}
              {m.key === 'unset' && unsetCount > 0 ? `（${unsetCount}）` : ''}
            </Radio.Button>
          ))}
        </Radio.Group>
        <Button size="small" style={{marginLeft: 8}} onClick={onConfirmNormal}>
          一键正常（仅未填写）
        </Button>
      </div>
    );
  };

  countCells = (rows, predicate, getCell) => {
    const {columns} = this.state;
    return (rows || []).reduce((acc, row) => {
      if (!row.isCellLeaf) return acc + this.countCells(row.children, predicate, getCell);
      return acc + columns.filter(col => predicate(getCell(row, col))).length;
    }, 0);
  };

  renderRowTitleProgress = (row, getCell) => {
    if (!this.state.columns.length) return null;
    const progress = rowProgress(row, this.state.columns, getCell);
    if (!progress.total) return null;
    const done = progress.filled >= progress.total;
    return (
      <Tag color={done ? 'success' : 'default'} style={{marginRight: 0}}>
        {progress.filled}/{progress.total}
      </Tag>
    );
  };

  renderMatrix = (rows, getCell, onCellChange, options) => {
    const {filterMode, columns} = this.state;
    const filtered = filterMatrixRows(
      rows, filterMode,
      r => columns.some(col => cellLooksAbnormal(getCell(r, col))),
      r => columns.some(col => cellValueEmpty(getCell(r, col)) && !getCell(r, col).result));
    return (
      <MatrixEditor
        columns={columns}
        rows={filtered}
        getCell={getCell}
        onCellChange={onCellChange}
        renderRowActions={options.rowActions}
        renderRowTitle={row => this.renderRowTitleProgress(row, getCell)}
        renderCellExtra={options.renderCellExtra}
      />
    );
  };

  renderPlannedAbnormalDesc = (row, column, cell) => {
    if (!cellLooksAbnormal(cell)) return null;
    return (
      <Input
        size="small" style={{marginTop: 2}} placeholder="异常说明"
        value={cell.abnormal_desc || ''}
        onChange={e => this.setPlannedCell(row, column, {abnormal_desc: e.target.value})}/>
    );
  };

  renderEditAbnormalDesc = (row, column, cell) => {
    if (!cell || !cellLooksAbnormal(cell)) return null;
    return (
      <Input
        size="small" style={{marginTop: 2}} placeholder="异常说明"
        value={(cell.abnormal_desc || '')}
        onChange={e => this.setEditCell(row, column, {abnormal_desc: e.target.value})}/>
    );
  };

  renderPlannedMatrix = () => {
    const {preview, planned, cellValues} = this.state;
    if (!preview) return null;
    const rows = plannedRows(planned);
    return (
      <div>
        {this.renderFilterBar(rows, this.getPlannedCell, this.confirmNormalPlanned)}
        {this.renderMatrix(rows, this.getPlannedCell, this.setPlannedCell, {
          rowActions: this.plannedRowActions,
          renderCellExtra: this.renderPlannedAbnormalDesc,
        })}
        {!Object.keys(cellValues).length && (
          <div style={{color: '#999', fontSize: 12, marginTop: 4}}>
            逐格填写或使用"一键正常"；每级行项目独立成列、父节点纵向合并，
            行实例（如第1/第2信道）在其分组合并单元格中增删。
          </div>
        )}
      </div>
    );
  };

  renderEditMatrix = () => {
    const {detail} = this.state;
    const rows = instanceRows(detail.row_instances);
    return (
      <div>
        {this.renderFilterBar(rows, this.getEditCell, this.confirmNormalEdit)}
        {this.renderMatrix(rows, this.getEditCell, this.setEditCell, {
          rowActions: this.editRowActions,
          renderCellExtra: this.renderEditAbnormalDesc,
        })}
        {Object.keys(this.state.cellEdits).length > 0 && (
          <Alert
            style={{marginTop: 8}} type="warning" showIcon
            message="有未保存的单元格改动，点击下方保存按钮一次提交。"
          />
        )}
      </div>
    );
  };

  renderRepeatNodeButtons = () => {
    const {repeatNodes, detail} = this.state;
    if (!repeatNodes.length) return null;
    return (
      <div style={{marginBottom: 8}}>
        <span style={{color: '#999', fontSize: 12, marginRight: 8}}>新增实例：</span>
        {repeatNodes.map(n => (
          <Button
            key={n.id} size="small" icon={<PlusOutlined/>}
            style={{marginRight: 8}}
            onClick={() => this.addInstance(n)}>
            {n.name}
          </Button>
        ))}
        <span style={{color: '#999', fontSize: 12}}>
          共 {this.countAllInstances(detail.row_instances)} 个行实例
        </span>
      </div>
    );
  };

  countAllInstances = (tree) => (tree || []).reduce(
    (acc, i) => acc + 1 + this.countAllInstances(i.children || []), 0);

  render() {
    const {store} = this.props;
    const {preview, editMode, detail} = this.state;
    const isEdit = !!store.record.id;
    const title = `${isEdit ? '编辑' : '新增'}${LEDGER_TYPE_TEXT[store.ledgerType]}台账`;
    return (
      <Modal
        title={title}
        visible={store.formVisible}
        width={1240}
        confirmLoading={this.state.loading}
        maskClosable={false}
        onCancel={() => {
          store.formVisible = false;
        }}
        onOk={this.submit}
        okText={editMode === 'matrix' ? '保存' : '整表一次提交'}>
        {this.renderHeader()}
        {this.renderTemplateSection()}
        {editMode === 'legacy' && (
          <Alert
            type="info" showIcon
            message="历史台账（旧结构）暂不支持矩阵编辑"
            description={`该台账由旧模板生成（编号 ${detail.ledger_no}），保持只读；仍可提交、作废与导出。`}
          />
        )}
        {!isEdit && preview && this.renderPlannedMatrix()}
        {editMode === 'matrix' && (
          <div>
            {this.renderRepeatNodeButtons()}
            {this.renderEditMatrix()}
          </div>
        )}
      </Modal>
    );
  }
}

export default LedgerForm;
export {LedgerForm};

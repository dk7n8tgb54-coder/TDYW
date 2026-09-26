/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 台账录入公共逻辑：明细行数据结构、填写值解析、预览行展开、
 * 提交 entries 组装、异常行判定。LedgerForm（新增/编辑弹窗）与
 * LedgerWorksheet（常驻工作台）共用，两处提交行为保持一致。
 */
import {NORMAL_ABNORMAL_CHOICES, ROW_PATH_SEPARATOR} from './constants';

let CLIENT_SEQ = 0;

const CHOICE_ABNORMAL_VALUE = NORMAL_ABNORMAL_CHOICES[1];

export function newClientKey() {
  CLIENT_SEQ += 1;
  return `k${Date.now()}_${CLIENT_SEQ}`;
}

const FREE_NUMBER_RE = /^-?\d+(\.\d+)?$/;

/**
 * 数字/文本行的填写值解析：纯数字输入同时产出 value_number（整洁存储，
 * 不参与判定）；其余内容仅保留文本。
 */
export function parseFreeValue(raw) {
  const text = String(raw === undefined || raw === null ? '' : raw);
  const trimmed = text.trim();
  if (FREE_NUMBER_RE.test(trimmed)) {
    return {value_text: text, value_number: parseFloat(trimmed)};
  }
  return {value_text: text, value_number: null};
}

/**
 * 行是否应按异常提示（红色高亮/角标计数）：结果为 abnormal（历史数据/后端
 * 派生回显），或正常/不正常单选填了"不正常"——结果列已从录入界面移除，
 * 异常由填写值体现，后端按填写值派生结果。
 */
export function rowLooksAbnormal(row) {
  if (row.result === 'abnormal') return true;
  return row.input_type === 'choice' && row.value_text === CHOICE_ABNORMAL_VALUE;
}

export function makeRow(base) {
  return Object.assign({
    client_key: newClientKey(),
    id: undefined,
    system_id: undefined,
    template_id: undefined,      // 来源模板（提交时随 entries 分组上报）
    template_item_id: undefined,
    item_name: '',
    input_type: 'text',
    unit: '',
    choices: [],
    is_required: false,
    value_text: '',
    value_number: null,
    value_bool: null,
    executed_at: null,
    is_temporary: false,
  }, base || {});
}

export function todayStr() {
  const d = new Date();
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

export function nowTimeStr() {
  const d = new Date();
  const pad = n => String(n).padStart(2, '0');
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/**
 * 明细执行时间（后端序列化为 YYYY-MM-DD HH:MM:SS）归一为 HH:mm 轮次时刻。
 */
export function roundTimeFromExecutedAt(value) {
  if (!value) return '';
  return String(value).replace('T', ' ').slice(11, 16);
}

/**
 * 台账详情还原为已记录轮次（"一日一账"回显）：按明细 executed_at 分组，
 * 时刻升序；行保留 id/填写值/结果供只读网格展示与后续 PUT 保留集组装。
 */
export function roundsFromDetail(detail) {
  const items = (detail && detail.items) || [];
  const map = {};
  const rounds = [];
  items.forEach(it => {
    const time = roundTimeFromExecutedAt(it.executed_at) || '--:--';
    if (!map[time]) {
      map[time] = {time, rows: []};
      rounds.push(map[time]);
    }
    map[time].rows.push({
      id: it.id,
      system_id: it.system,
      template_item_id: it.template_item,
      item_name: it.item_name,
      input_type: it.input_type,
      unit: it.unit || '',
      choices: it.choices || [],
      is_required: it.is_required,
      value_text: it.value_text || '',
      value_number: it.value_number === undefined ? null : it.value_number,
      value_bool: it.value_bool === undefined ? null : it.value_bool,
      result: it.result,
      is_temporary: it.is_temporary,
      executed_at: it.executed_at,
    });
  });
  rounds.sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0));
  return rounds;
}

/**
 * 组装"一日一账"累积记录 entries（对应 update_ledger 的
 * "带 id 保留并更新值 / 无 id 新增 / 缺失删除"契约）：
 * - 已记录轮次行（带 id）：仅上送 id+填写值，按系统分组，不含模板信息
 *   （已有明细的模板快照不可变，后端 _apply_item_edits 只更新填写值）；
 * - 当前轮新行（无 id）：复用 buildSubmitEntries 按 系统+模板 分组，
 *   并注入本轮 executed_at（明细级实际执行时刻，同日多轮的区分依据）。
 */
export function buildAccumulatedEntries(rounds, rows, executedAt) {
  const entries = [];
  const systemEntryMap = {};
  (rounds || []).forEach(round => {
    (round.rows || []).forEach(r => {
      if (!r.id) return;
      const key = String(r.system_id);
      if (!systemEntryMap[key]) {
        systemEntryMap[key] = {system_id: r.system_id, items: []};
        entries.push(systemEntryMap[key]);
      }
      systemEntryMap[key].items.push({
        id: r.id,
        value_text: r.value_text,
        value_number: r.value_number,
        value_bool: r.value_bool,
      });
    });
  });
  const built = buildSubmitEntries(rows);
  if (built.error) return built;
  built.entries.forEach(entry => {
    entry.items.forEach(item => {
      if (!item.id && executedAt) item.executed_at = executedAt;
    });
  });
  return {entries: entries.concat(built.entries)};
}

/**
 * 只读网格的填写值展示文本（取值口径与详情页一致）。
 */
export function rowValueText(row) {
  if (row.input_type === 'number') {
    return row.value_number === null || row.value_number === undefined ? '' : String(row.value_number);
  }
  if (row.input_type === 'boolean') {
    if (row.value_bool === null || row.value_bool === undefined) return '';
    return row.value_bool ? '是' : '否';
  }
  if (row.input_type === 'multi_choice') {
    try {
      const arr = row.value_text ? JSON.parse(row.value_text) : [];
      return arr.length ? arr.join('、') : '';
    } catch (e) {
      return row.value_text || '';
    }
  }
  return row.value_text || '';
}

/**
 * 预览响应展开为明细行（模板来源行带 template_id/template_item_id）。
 * 预览响应条目结构：{system, template, items}。
 */
export function rowsFromPreview(previewEntries) {
  const rows = [];
  (previewEntries || []).forEach(entry => {
    (entry.items || []).forEach(item => {
      rows.push(makeRow({
        system_id: entry.system.id,
        template_id: entry.template ? entry.template.id : undefined,
        template_item_id: item.id,
        item_name: item.name,
        input_type: item.input_type,
        unit: item.unit || '',
        choices: item.choices || [],
        is_required: item.is_required,
        value_text: item.default_value || '',
      }));
    });
  });
  return rows;
}

/**
 * 模板条目归一化：兼容旧版 {system_id, template_id} 单配对与
 * {template_id, system_ids: []} 多选形态，统一为 {template_id}。
 * 电台不再由录入人选择，旧种子中的系统限定一律忽略。
 */
export function normalizeTemplateEntries(entries) {
  const list = Array.isArray(entries) ? entries : [];
  const normalized = [];
  list.forEach(t => {
    if (!t || !t.template_id) return;
    normalized.push({template_id: t.template_id});
  });
  return normalized;
}

/**
 * 模板条目展开为预览接口的 系统×模板 配对条目（预览/提交接口契约不变）。
 * 每个模板条目自动覆盖全部未停用系统；系统候选由调用方传入
 * （来自系统档案列表，带停用标记的候选被剔除）。
 */
export function expandTemplateEntries(entries, systems) {
  const allIds = (systems || [])
    .filter(s => s && s.is_active !== false)
    .map(s => s.id);
  const pairs = [];
  normalizeTemplateEntries(entries).forEach(t => {
    allIds.forEach(systemId => pairs.push({system_id: systemId, template_id: t.template_id}));
  });
  return pairs;
}

/**
 * 按 系统+模板 分组组装创建/编辑 entries（同系统不同模板分列，
 * 后端逐条目校验快照来源）。明细缺系统时返回 {error}，由调用方提示。
 */
export function buildSubmitEntries(rows) {
  const groupMap = {};
  for (const r of rows) {
    if (!r.system_id) return {error: '每条明细必须选择所属系统'};
    const key = `${r.system_id}|${r.template_id || ''}`;
    if (!groupMap[key]) groupMap[key] = [];
    groupMap[key].push(r);
  }
  const entries = Object.keys(groupMap).map(key => {
    const [systemId, templateId] = key.split('|');
    const entry = {
      system_id: Number(systemId),
      items: groupMap[key].map(r => ({
        id: r.id,
        template_item_id: r.template_item_id || undefined,
        item_name: r.is_temporary || !r.id ? r.item_name : undefined,
        input_type: r.is_temporary || !r.id ? r.input_type : undefined,
        unit: r.is_temporary || !r.id ? r.unit : undefined,
        choices: r.is_temporary || !r.id ? r.choices : undefined,
        value_text: r.value_text,
        value_number: r.value_number,
        value_bool: r.value_bool,
      })),
    };
    if (templateId) entry.template_id = Number(templateId);
    return entry;
  });
  return {entries};
}

// ==================== 行对象树矩阵（第一阶段：行方向多级 + 平面列项目） ====================

let PLANNED_SEQ = 0;

export function newPlannedKey() {
  PLANNED_SEQ += 1;
  return `p${Date.now()}_${PLANNED_SEQ}`;
}

/**
 * 模板行节点树 → 计划实例树（录入端预览态）：每个节点默认 1 个计划实例，
 * 名称默认节点名；可重复分组（repeat_group）的计划实例可复制出"第2信道"等。
 */
export function plannedFromRowNodes(rowNodes) {
  return (rowNodes || []).map(node => plannedFromNode(node, null));
}

function plannedFromNode(node, parentKey) {
  return {
    key: newPlannedKey(),
    node_id: node.id,
    node_type: node.node_type,
    name: node.name,
    parentKey: parentKey,
    children: (node.children || []).map(c => plannedFromNode(c, null)),
  };
}

/** 复制计划实例子树（可重复分组"新增信道"），名称重置为节点名供用户修改 */
export function clonePlanned(planned) {
  const clone = {
    ...planned,
    key: newPlannedKey(),
    children: (planned.children || []).map(c => clonePlanned(c)),
  };
  clone.children.forEach(c => {
    c.parentKey = clone.key;
  });
  return clone;
}

/** 计划实例展平：附 path（实例名连接）与 depth（根为 1）。 */
export function flattenPlanned(plannedList, prefix = '', out = []) {
  (plannedList || []).forEach(p => {
    const path = prefix ? `${prefix}${ROW_PATH_SEPARATOR}${p.name}` : p.name;
    out.push({...p, path, depth: path.split(ROW_PATH_SEPARATOR).length});
    flattenPlanned(p.children, path, out);
  });
  return out;
}

/** 计划树中某实例的同级数量（"至少保留一个信道"判断用）。 */
export function siblingCount(plannedList, key) {
  const find = list => {
    for (const p of list) {
      if (p.key === key) return list.length;
      const hit = find(p.children || []);
      if (hit) return hit;
    }
    return null;
  };
  return find(plannedList || []) || 0;
}

/** 计划实例规格 → 创建载荷 row_instances（递归）。 */
export function buildRowSpec(plannedList) {
  return (plannedList || []).map(p => ({
    template_node: p.node_id,
    name: p.name,
    children: buildRowSpec(p.children || []),
  }));
}

/**
 * 计划模式单元格填写值：key = `${行叶子计划key}|${列项目id}`，
 * 与实例名解耦（重命名"第1信道"不丢已填内容）。
 */
export function plannedCellKey(plannedKey, itemId) {
  return `${plannedKey}|${itemId}`;
}

/** 填写值是否为空（多选空数组视为空，与后端 _cell_value_empty 口径一致）。 */
export function cellValueEmpty(cell) {
  if (!cell) return true;
  if (cell.value_number !== null && cell.value_number !== undefined) return false;
  if (cell.value_bool !== null && cell.value_bool !== undefined) return false;
  if (cell.input_type === 'multi_choice') {
    try {
      return !(cell.value_text ? JSON.parse(cell.value_text) : []).length;
    } catch (e) {
      return true;
    }
  }
  return !String(cell.value_text || '').trim();
}

/** 单元格是否按异常提示（结果异常，或正常/不正常单选填了"不正常"）。 */
export function cellLooksAbnormal(cell) {
  if (!cell) return false;
  if (cell.result === 'abnormal') return true;
  return cell.input_type === 'choice' && cell.value_text === NORMAL_ABNORMAL_CHOICES[1];
}

/**
 * 矩阵行过滤：mode=all 全部；abnormal 仅保留含异常单元格的行叶子
 * （及其祖先）；unset 仅保留含未填写单元格的行叶子（及其祖先）。
 * rows 为带 children 的树（叶子为 check 行对象）。
 */
export function filterMatrixRows(rows, mode, isRowAbnormal, isRowUnfilled) {
  if (mode !== 'abnormal' && mode !== 'unset') return rows;
  const hit = mode === 'abnormal' ? isRowAbnormal : isRowUnfilled;
  const walk = list => (list || []).reduce((out, row) => {
    const children = walk(row.children);
    if (children.length) {
      out.push({...row, children});
      return out;
    }
    if (!row.isCellLeaf) return out;
    if (hit(row)) out.push({...row, children: []});
    return out;
  }, []);
  return walk(rows);
}

/**
 * 行级完成进度（含子孙叶子汇总）：filled / total。
 * getCell(row, column) 由调用方提供（计划态取本地值，编辑态取台账单元格）。
 */
export function rowProgress(row, columns, getCell) {
  if (!row.isCellLeaf) {
    let filled = 0;
    let total = 0;
    (row.children || []).forEach(child => {
      const p = rowProgress(child, columns, getCell);
      filled += p.filled;
      total += p.total;
    });
    return {filled, total};
  }
  let filled = 0;
  columns.forEach(col => {
    if (!cellValueEmpty(getCell(row, col))) filled += 1;
  });
  return {filled, total: columns.length};
}

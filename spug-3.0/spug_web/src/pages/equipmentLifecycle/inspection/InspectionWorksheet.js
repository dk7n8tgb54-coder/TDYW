/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 */
/**
 * 设备全生命周期——今日巡检工作台（合并矩阵表改造）。
 *
 * 业务规则：
 * - 巡检单唯一范围 = 值班日 + 巡检模板；值班人员登记在单上（仅手输姓名回车添加，
 *   不再提供账号选择）；
 * - 进入页面未恢复草稿时自动选中上一次使用的模板（最近一张巡检单的模板；
 *   模板已停用/删除则保持未选择）；
 * - 固定四轮：当日 11:00 / 16:00 / 22:00、次日 06:30（归属前一值班日，可回选值班日）；
 * - 不记录实际填写时间、不标记迟填、不根据点击时间判断轮次；
 * - 页面结构 = 单张四轮巡检矩阵表（检查项目 | 检查内容 | 四轮），不再分"填写区/回显区"；
 *   同一批检查项目只渲染一次；
 * - 四个轮次彼此独立、可按任意顺序填写和记录：未记录轮次整列可编辑，轮次操作
 *   （一键正常/记录本轮）放在对应轮次列表头内部（吸顶），不再有顶部轮次选择区；
 * - 轮次状态持久化在后端 recorded_rounds：未记录（可编辑，可带"有草稿"提示）、
 *   已记录（只读、按钮隐藏、后端拒绝再改）、已提交/已作废（整单只读）；
 * - 已退回整改单（超管退回）：整单可改（含已记录轮次），打开时以服务端已存
 *   记录回显各轮次填写值（与本地草稿合并、本地优先），整改后重新提交；
 * - 底色按列：有草稿的未记录轮次列浅黄、草稿单中已记录轮次列浅蓝、异常浅红；
 * - "一键正常"只填充当前轮次未填写的检查项，不覆盖已填内容（含异常与现场处理）；
 * - "记录本轮"只提交当前轮次（后端单轮契约，version 乐观锁），请求期间按钮
 *   loading 且其余轮次记录按钮禁用，失败时轮次保持可编辑；
 * - 草稿按轮次保存在 localStorage（{values: {r1: {...}}}, 旧扁平格式兼容读取），
 *   切换轮次不丢内容；已记录轮次草稿自动清理；空白草稿不入存储；
 * - 巡检单只记录巡检结果、异常内容和现场处理：历史已转故障/已转工单的处置
 *   状态只读展示（转单功能已下线，故障/工单在对应模块创建，无跳转或创建入口）。
 *
 * 结构：数据与动作（useWorksheetDraft / useWorksheetActions）在本文件，
 * 展示卡片拆分在 WorksheetCards.js。
 */
import React, {useState, useEffect, useRef} from 'react';
import {observer} from 'mobx-react';
import {Card, Empty, Input, Modal, message} from 'antd';
import moment from 'moment';
import {AuthDiv, Breadcrumb} from 'components';
import store from './store';
import {HeaderCard, SheetMatrixCard} from './WorksheetCards';
import {EDITABLE_SHEET_STATUSES, NORMAL_VALUE, ROUND_TEXT} from './constants';

const ROUND_KEYS = ['r1', 'r2', 'r3', 'r4'];

function storageKey() {
  const nickname = sessionStorage.getItem('nickname') || '';
  return `el_insp_ws_${encodeURIComponent(nickname)}`;
}

function valueHasContent(v) {
  return !!v && !!((v.value_text && String(v.value_text).trim()) ||
    (v.onsite_action && String(v.onsite_action).trim()));
}

function compactRoundValues(roundValues) {
  const out = {};
  Object.entries(roundValues || {}).forEach(([key, v]) => {
    if (valueHasContent(v)) out[key] = v;
  });
  return out;
}

function normalizeSavedValues(saved) {
  // 新格式 values = {r1: {...}}；兼容旧扁平格式 {round: 'r1', values: {t_21: {...}}}
  const values = saved.values;
  if (!values || typeof values !== 'object') return null;
  const keys = Object.keys(values);
  if (!keys.length) return null;
  if (keys.every(k => ROUND_KEYS.includes(k))) return values;
  if (saved.round && ROUND_KEYS.includes(saved.round)) {
    return {[saved.round]: values};
  }
  return null;
}

function readSavedDraft() {
  // 恢复暂存（按轮次；跨日/模板不符自动忽略）
  try {
    const raw = sessionStorage.getItem('nickname') ? localStorage.getItem(storageKey()) : null;
    if (!raw) return null;
    const saved = JSON.parse(raw);
    if (!saved || !saved.duty_date || !saved.template_id) return null;
    const values = normalizeSavedValues(saved);
    if (!values) return null;
    return {
      duty_date: saved.duty_date,
      template_id: saved.template_id,
      persons: saved.persons || [],
      values,
    };
  } catch (e) { /* 暂存损坏时忽略 */ }
  return null;
}

function buildPersonPayloadRows(persons, users) {
  return (persons || []).map(v => {
    const user = users.find(u => String(u.id) === v);
    if (user) {
      return {user: user.id, person_name: user.nickname || user.username};
    }
    return {user: null, person_name: v};
  });
}

function buildRecordSpecs(template, roundValues, round) {
  const specs = [];
  (template ? template.devices : []).forEach(d => {
    (d.items || []).forEach(item => {
      const v = roundValues ? roundValues[`t_${item.id}`] : null;
      if (!valueHasContent(v)) return;
      specs.push({
        template_item_id: item.id,
        round_no: round,
        value_text: v.value_text || '',
        onsite_action: v.onsite_action || '',
      });
    });
  });
  return specs;
}

function findMissingRequired(template, roundValues) {
  // "记录本轮"前校验当前轮次必填检查内容（必填 = 模板 is_required）
  const missing = [];
  (template ? template.devices : []).forEach(d => {
    (d.items || []).forEach(item => {
      const v = roundValues ? roundValues[`t_${item.id}`] : null;
      const filled = v && v.value_text && String(v.value_text).trim();
      if (item.is_required && !filled) {
        missing.push(`${d.device_name}·${item.name}`);
      }
    });
  });
  return missing;
}

function confirmVoidSheet(sheet) {
  let reason = '';
  Modal.confirm({
    title: '作废巡检单',
    content: (
      <Input.TextArea
        rows={2}
        placeholder="请填写作废原因（必填）"
        onChange={e => {reason = e.target.value;}}
      />
    ),
    onOk: () => {
      if (!reason.trim()) {
        message.error('作废原因不能为空');
        return Promise.reject();
      }
      return store.voidSheet(sheet.id, reason.trim());
    },
  });
}

/** 已退回整改单：由服务端已存记录构建按轮次初始填写值（原有填写内容回显，
 *  key 与填写态一致 = t_{模板项id} / m_{client_key}）。 */
function buildValuesFromRecords(sheet) {
  const values = {};
  (sheet.records || []).forEach(r => {
    const key = r.template_item ? `t_${r.template_item}` : `m_${r.client_key || r.id}`;
    values[r.round_no] = values[r.round_no] || {};
    values[r.round_no][key] = {
      value_text: r.value_text || '',
      onsite_action: r.onsite_action || '',
    };
  });
  return values;
}

/** 加载值班日+模板对应的当日巡检单：有则拉取详情，无则清空详情等"开始巡检"。 */
function loadDutySheet(dateStr, tplId, mountedRef) {
  return store.fetchSheets({duty_date: dateStr, template: tplId, page_size: 1})
    .then(() => {
      if (!mountedRef.current) return null;
      const existing = (store.records || [])[0];
      if (existing) {
        return store.fetchSheet(existing.id);
      }
      // 无单：默认不自动建单，等用户点"开始巡检"（避免浏览即建单）
      store.resetDetail();
      return null;
    })
    .catch(() => {});
}

/** 草稿数据：值班日/模板/人员/按轮次填写的值 + 暂存恢复与持久化。 */
function useWorksheetDraft() {
  const [dutyDate, setDutyDate] = useState(moment().format('YYYY-MM-DD'));
  const [templateId, setTemplateId] = useState(null);
  const [persons, setPersons] = useState([]);
  const [values, setValues] = useState({});   // {r1: {t_21: {value_text, onsite_action}}}
  const [restored, setRestored] = useState(false);
  const mountedRef = useRef(true);
  // 暂存恢复标记：恢复的填写内容不被随后的加载流程清空（仅用户主动切换时清空）
  const restoredRef = useRef(false);

  useEffect(() => {
    mountedRef.current = true;
    // 值班人员已不选择账号；账号表仅用于历史草稿中账号值的姓名映射与回显
    store.fetchUsers().catch(() => {});
    const saved = readSavedDraft();
    if (saved) {
      restoredRef.current = true;
      setDutyDate(saved.duty_date);
      setTemplateId(saved.template_id);
      setPersons(saved.persons);
      setValues(saved.values);
      setRestored(true);
    }
    // 未恢复草稿时自动选中上一次使用的模板：取最近一张巡检单（按值班日倒序）
    // 的模板，且该模板仍在可用列表中，否则保持未选择
    store.fetchTemplates().catch(() => {}).then(() => {
      if (!mountedRef.current || saved) return undefined;
      return store.fetchSheets({page_size: 1}).then(() => {
        if (!mountedRef.current) return;
        const last = (store.records || [])[0];
        if (last && last.template &&
            store.templates.some(t => t.id === last.template)) {
          setTemplateId(last.template);
        }
      });
    });
    return () => {mountedRef.current = false;};
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!templateId) return;
    if (restoredRef.current) {
      // 首次进入且来自暂存恢复：不清空已恢复的填写内容
      restoredRef.current = false;
      loadDutySheet(dutyDate, templateId, mountedRef);
      return;
    }
    setValues({});
    loadDutySheet(dutyDate, templateId, mountedRef);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templateId, dutyDate]);

  useEffect(() => {
    // 草稿对账：已记录轮次草稿清理；非草稿单（已提交/已作废）内容全部只读且暂存无意义
    const sheet = store.detail;
    if (!sheet) return;
    if (sheet.status === 'returned') {
      // 已退回整改单：以服务端已存记录为底、本地未提交草稿优先合并，
      // 原有填写内容回显且不因退回清空（recorded_rounds 不限制整改）
      setValues(prev => {
        const base = buildValuesFromRecords(sheet);
        const merged = {};
        ROUND_KEYS.forEach(r => {
          merged[r] = {...(base[r] || {}), ...(prev[r] || {})};
        });
        return merged;
      });
      return;
    }
    if (sheet.status !== 'draft') {
      setValues({});
      localStorage.removeItem(storageKey());
      return;
    }
    const recorded = sheet.recorded_rounds || [];
    const stale = ROUND_KEYS.filter(r => recorded.includes(r) && values[r]);
    if (stale.length) {
      setValues(prev => {
        const next = {...prev};
        stale.forEach(r => {delete next[r];});
        return next;
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [store.detail]);

  useEffect(() => {
    // 暂存（按轮次）：空白草稿不入暂存
    const filled = {};
    ROUND_KEYS.forEach(r => {
      const compact = compactRoundValues(values[r]);
      if (Object.keys(compact).length) filled[r] = compact;
    });
    if (Object.keys(filled).length) {
      localStorage.setItem(storageKey(), JSON.stringify({
        duty_date: dutyDate, template_id: templateId, persons,
        values: filled, saved_at: Date.now(),
      }));
    } else {
      localStorage.removeItem(storageKey());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [values, dutyDate, templateId, persons]);

  function clearRound(round) {
    setValues(prev => {
      const next = {...prev};
      delete next[round];
      return next;
    });
  }

  function clearRestored() {
    setValues({});
    setRestored(false);
    localStorage.removeItem(storageKey());
  }

  return {
    dutyDate, setDutyDate, templateId, setTemplateId, persons, setPersons,
    values, setValues, restored,
    clearRound, clearRestored, mountedRef,
  };
}

/** 草稿动作：建单/人员变更/按轮次一键正常/按轮次记录本轮/提交，以及填写更新。 */
function useWorksheetActions(draft, template, sheet) {
  const [recordingRound, setRecordingRound] = useState(null);
  const {mountedRef} = draft;

  function handleStart() {
    store.createSheet({
      duty_date: draft.dutyDate,
      template_id: draft.templateId,
      persons: buildPersonPayloadRows(draft.persons, store.users),
      client_token: `ins-ws-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    }).catch(() => {});
  }

  function handlePersonsChange(vals) {
    draft.setPersons(vals);
    // 草稿/已退回整改单均可补改值班人员
    if (sheet && EDITABLE_SHEET_STATUSES.includes(sheet.status)) {
      store.saveSheet(sheet.id, {
        version: sheet.version,
        persons: buildPersonPayloadRows(vals, store.users),
      }).catch(() => {});
    }
  }

  function handleFillNormal(round) {
    // 一键正常：只作用于指定轮次这一列，且只填充"尚未填写"的选择型检查项；
    // 已填写内容（含"不正常"与现场处理）一律不覆盖，故无需覆盖确认；
    // 数值/文本项始终人工填写；草稿单已记录轮次不执行（退回整改单不限制）。
    if (sheet && !EDITABLE_SHEET_STATUSES.includes(sheet.status)) return;
    if (sheet && sheet.status === 'draft' &&
        recordedRounds(sheet).includes(round)) return;
    const {roundValues, filled, untouched, choiceCount} = computeFillNormal(
      template, draft.values[round] || {});
    if (!choiceCount) {
      message.info(`「${ROUND_TEXT[round]}」模板无选择型检查项，请人工填写`);
      return;
    }
    if (!filled) {
      message.info(`「${ROUND_TEXT[round]}」选择型检查项均已填写，未做修改`);
      return;
    }
    draft.setValues({...draft.values, [round]: roundValues});
    message.success(
      `已为「${ROUND_TEXT[round]}」${filled} 个未填写检查项填入"正常"` +
      (untouched ? `；${untouched} 个已填写项保持不变` : '；数值/文本项请人工填写'));
  }

  function handleRecordRound(round) {
    if (!sheet || !EDITABLE_SHEET_STATUSES.includes(sheet.status)) {
      message.warning('请先开始巡检（生成草稿巡检单）');
      return;
    }
    if (recordingRound) return;   // 已有轮次在记录中：防重复提交
    if (sheet.status === 'draft' && recordedRounds(sheet).includes(round)) {
      // 仅草稿单拒绝重复记录；退回整改单允许重改已记录轮次
      message.warning(`「${ROUND_TEXT[round]}」轮次已记录，不能再次修改`);
      return;
    }
    const roundValues = draft.values[round] || {};
    const missing = findMissingRequired(template, roundValues);
    if (missing.length) {
      message.error(`请先填写 ${ROUND_TEXT[round]} 轮次必填内容：${missing.join('、')}`);
      return;
    }
    const records = buildRecordSpecs(template, roundValues, round);
    if (!records.length) {
      message.warning(`请先填写 ${ROUND_TEXT[round]} 轮次的检查内容`);
      return;
    }
    setRecordingRound(round);
    store.saveSheet(sheet.id, {
      version: sheet.version,
      persons: buildPersonPayloadRows(draft.persons, store.users),
      records,
    }).then(() => {
      if (!mountedRef.current) return;
      draft.clearRound(round);
      message.success(`已记录 ${ROUND_TEXT[round]} 轮次`);
    }).catch(() => {
      // 保存失败：错误提示由 http 拦截器弹出，轮次保持可编辑、草稿保留
    }).finally(() => {
      if (mountedRef.current) setRecordingRound(null);
    });
  }

  function handleSubmit() {
    store.submitSheet(sheet.id).then(() => {
      if (!mountedRef.current) return;
      draft.setValues({});
      localStorage.removeItem(storageKey());
      message.success('巡检单已提交');
    }).catch(() => {});
  }

  function updateValue(round, key, field, val) {
    const roundValues = draft.values[round] || {};
    draft.setValues({
      ...draft.values,
      [round]: {...roundValues, [key]: {...roundValues[key], [field]: val}},
    });
  }

  return {
    recordingRound,
    handleStart, handlePersonsChange, handleFillNormal, handleRecordRound, handleSubmit,
    updateValue,
  };
}

function recordedRounds(sheet) {
  return (sheet && sheet.recorded_rounds) || [];
}

/** 一键正常取值计算：只给未填写的选择型检查项填"正常"，已填写项（含异常）
 *  与现场处理一律保留；返回 {roundValues, filled, untouched, choiceCount}。 */
function computeFillNormal(template, roundValues) {
  const next = {...roundValues};
  let filled = 0;
  let untouched = 0;
  let choiceCount = 0;
  (template ? template.devices : []).forEach(d => {
    (d.items || []).forEach(item => {
      if (item.input_type !== 'choice') return;
      choiceCount += 1;
      const existing = next[`t_${item.id}`];
      if (existing && existing.value_text && String(existing.value_text).trim()) {
        untouched += 1;
        return;
      }
      filled += 1;
      next[`t_${item.id}`] = {...(existing || {}), value_text: NORMAL_VALUE};
    });
  });
  return {roundValues: next, filled, untouched, choiceCount};
}

function InspectionWorksheet() {
  const draft = useWorksheetDraft();
  const template = store.templates.find(t => t.id === draft.templateId) || null;
  const sheet = store.detail;
  const isVoid = !!sheet && sheet.status === 'void';
  const actions = useWorksheetActions(draft, template, sheet);

  function handleVoid() {
    confirmVoidSheet(sheet);
  }

  return (
    <AuthDiv>
      <Breadcrumb>
        <Breadcrumb.Item>设备全生命周期管理</Breadcrumb.Item>
        <Breadcrumb.Item>运行维护</Breadcrumb.Item>
        <Breadcrumb.Item>今日巡检</Breadcrumb.Item>
      </Breadcrumb>
      {draft.restored && (
        <Card size="small" style={{marginBottom: 12, background: '#fffbe6'}}>
          已恢复上次未提交的填写内容
          <a style={{marginLeft: 8}} onClick={draft.clearRestored}>清除</a>
        </Card>
      )}
      <HeaderCard
        dutyDate={draft.dutyDate} onDutyDateChange={draft.setDutyDate}
        templateId={draft.templateId} onTemplateChange={draft.setTemplateId}
        persons={draft.persons} onPersonsChange={actions.handlePersonsChange}
        templates={store.templates} users={store.users} sheet={sheet}
        hasTemplate={!!template} isVoid={isVoid} onStart={actions.handleStart}/>
      {sheet && (
        <SheetMatrixCard
          sheet={sheet} template={template}
          recordedRounds={recordedRounds(sheet)}
          editable={EDITABLE_SHEET_STATUSES.includes(sheet.status)}
          values={draft.values} recordingRound={actions.recordingRound}
          onValueChange={actions.updateValue}
          onFillNormal={actions.handleFillNormal} onRecord={actions.handleRecordRound}
          onSubmit={actions.handleSubmit} onVoid={handleVoid}/>
      )}
      {!sheet && !template && <Empty description="请选择巡检模板开始今日巡检"/>}
      <style>{`
        .el-ins-matrix-wrap { overflow: auto; max-height: calc(100vh - 300px); }
        .el-ins-matrix th, .el-ins-matrix td { padding: 5px 8px; }
        .el-ins-matrix thead th {
          position: sticky; top: 0; z-index: 2; background: #fafafa;
        }
        .el-ins-matrix .el-ins-col-project, .el-ins-matrix .el-ins-col-content {
          position: sticky; background: #fff; z-index: 1;
        }
        .el-ins-matrix th.el-ins-col-project, .el-ins-matrix td.el-ins-col-project {
          left: 0; width: 120px; min-width: 120px; max-width: 120px;
        }
        .el-ins-matrix th.el-ins-col-content, .el-ins-matrix td.el-ins-col-content {
          left: 120px; width: 170px; min-width: 170px; max-width: 170px;
        }
        .el-ins-matrix thead th.el-ins-col-project,
        .el-ins-matrix thead th.el-ins-col-content { z-index: 3; background: #fafafa; }
        /* 轮次列固定宽度：标题行（名称+状态+有草稿占位）与按钮行均不超过
           200px，列宽不随 填写中/有草稿/已记录 状态切换而跳动 */
        .el-ins-matrix th.el-ins-col-round, .el-ins-matrix td.el-ins-round-cell {
          width: 200px; min-width: 200px;
        }
        .el-ins-round-head { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; }
        .el-ins-round-title { display: flex; align-items: baseline; gap: 6px; white-space: nowrap; }
        .el-ins-round-name { font-weight: 600; }
        .el-ins-round-status { font-weight: normal; font-size: 12px; color: #595959; }
        .el-ins-round-status-recorded { color: #1890ff; }
        .el-ins-round-draft-tag { font-weight: normal; font-size: 12px; color: #d48806; }
        .el-ins-round-actions { display: flex; gap: 4px; flex-wrap: wrap; margin-top: 2px; }
        .el-ins-cell-draft { background: #fffbe6; }
        .el-ins-cell-recorded { background: #f0f7ff; }
        .el-ins-cell-abnormal { background: #fff1f0; }
        .el-ins-legend-chip {
          display: inline-block; width: 10px; height: 10px; margin-right: 4px;
          border: 1px solid #e8e8e8; vertical-align: middle;
        }
        .el-ins-legend-draft { background: #fffbe6; }
        .el-ins-legend-recorded { background: #f0f7ff; }
        .el-ins-legend-abnormal { background: #fff1f0; }
      `}</style>
    </AuthDiv>
  );
}

export default observer(InspectionWorksheet);

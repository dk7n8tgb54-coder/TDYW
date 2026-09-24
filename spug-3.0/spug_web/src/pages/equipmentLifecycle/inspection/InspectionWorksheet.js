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
 * - 不记录实际填写时间、不标记迟填、不根据点击时间判断轮次（轮次显式选择）；
 * - 页面结构 = 单张四轮巡检矩阵表（检查项目 | 检查内容 | 四轮），不再分"填写区/回显区"；
 *   同一批检查项目只渲染一次；
 * - 轮次三态：当前选择轮次可编辑；已记录轮次（sheet.recorded_rounds）只读展示保存值；
 *   未记录轮次显示"—"；已提交/已作废巡检单全部只读；
 * - 底色只跟随当前选择轮次列（未记录=浅黄、已记录已填=浅蓝），未选中列无底色；
 * - "记录本轮"只提交当前选择的轮次（后端同样只允许单轮、已记录轮次拒绝再改）；
 * - 草稿按轮次保存在 localStorage（{values: {r1: {...}}}, 旧扁平格式兼容读取），
 *   切换轮次不丢内容；已记录轮次草稿自动清理；空白草稿不入存储；
 * - 巡检单不关联系统：异常转故障/工单时才在转换弹窗中选择系统（必填）。
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
import {ConvertToFaultModal, ConvertToWorkOrderModal} from './ConvertModals';
import {HeaderCard, SheetMatrixCard} from './WorksheetCards';
import {NORMAL_VALUE, ROUND_TEXT} from './constants';

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

/** 草稿数据：值班日/模板/人员/轮次/按轮次填写的值 + 暂存恢复与持久化。 */
function useWorksheetDraft() {
  const [dutyDate, setDutyDate] = useState(moment().format('YYYY-MM-DD'));
  const [templateId, setTemplateId] = useState(null);
  const [persons, setPersons] = useState([]);
  const [currentRound, setCurrentRound] = useState('r1');
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
    currentRound, setCurrentRound, values, setValues, restored,
    clearRound, clearRestored, mountedRef,
  };
}

/** 草稿动作：建单/人员变更/一键正常/记录本轮/提交，以及当前轮次填写更新。 */
function useWorksheetActions(draft, template, sheet) {
  const [convert, setConvert] = useState(null);
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
    if (sheet && sheet.status === 'draft') {
      store.saveSheet(sheet.id, {
        version: sheet.version,
        persons: buildPersonPayloadRows(vals, store.users),
      }).catch(() => {});
    }
  }

  function handleFillNormal() {
    // 一键正常：仅当前轮次的选择型检查项填入"正常"；数值/文本项与已记录轮次不动
    const roundKey = draft.currentRound;
    const roundValues = {...(draft.values[roundKey] || {})};
    let filled = false;
    (template ? template.devices : []).forEach(d => {
      (d.items || []).forEach(item => {
        if (item.input_type !== 'choice') return;
        filled = true;
        roundValues[`t_${item.id}`] = {
          ...(roundValues[`t_${item.id}`] || {}), value_text: NORMAL_VALUE,
        };
      });
    });
    if (filled) {
      draft.setValues({...draft.values, [roundKey]: roundValues});
      message.success('已一键填入"正常"；数值/文本项请人工填写');
    }
  }

  function handleRecordRound() {
    if (!sheet || sheet.status !== 'draft') {
      message.warning('请先开始巡检（生成草稿巡检单）');
      return;
    }
    const round = draft.currentRound;
    const roundValues = draft.values[round] || {};
    if (recordedRounds(sheet).includes(round)) {
      message.warning(`「${ROUND_TEXT[round]}」轮次已记录，不能再次修改`);
      return;
    }
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
    store.saveSheet(sheet.id, {
      version: sheet.version,
      persons: buildPersonPayloadRows(draft.persons, store.users),
      records,
    }).then(() => {
      if (!mountedRef.current) return;
      draft.clearRound(round);
      message.success(`已记录 ${ROUND_TEXT[round]} 轮次`);
    }).catch(() => {});
  }

  function handleSubmit() {
    store.submitSheet(sheet.id).then(() => {
      if (!mountedRef.current) return;
      draft.setValues({});
      localStorage.removeItem(storageKey());
      message.success('巡检单已提交');
    }).catch(() => {});
  }

  function updateValue(key, field, val) {
    const roundKey = draft.currentRound;
    const roundValues = draft.values[roundKey] || {};
    draft.setValues({
      ...draft.values,
      [roundKey]: {...roundValues, [key]: {...roundValues[key], [field]: val}},
    });
  }

  return {
    convert, setConvert,
    handleStart, handlePersonsChange, handleFillNormal, handleRecordRound, handleSubmit,
    updateValue,
  };
}

function recordedRounds(sheet) {
  return (sheet && sheet.recorded_rounds) || [];
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

  function closeConvert() {
    actions.setConvert(null);
    if (sheet) store.fetchSheet(sheet.id).catch(() => {});
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
          sheet={sheet} template={template} currentRound={draft.currentRound}
          recordedRounds={recordedRounds(sheet)} editable={sheet.status === 'draft'}
          values={draft.values}
          onRoundChange={draft.setCurrentRound} onValueChange={actions.updateValue}
          onFillNormal={actions.handleFillNormal} onRecord={actions.handleRecordRound}
          onSubmit={actions.handleSubmit} onVoid={handleVoid}
          onConvert={actions.setConvert}/>
      )}
      {!sheet && !template && <Empty description="请选择巡检模板开始今日巡检"/>}
      {actions.convert && actions.convert.type === 'fault' && (
        <ConvertToFaultModal visible record={actions.convert.record} onClose={closeConvert}/>
      )}
      {actions.convert && actions.convert.type === 'work_order' && (
        <ConvertToWorkOrderModal visible record={actions.convert.record} onClose={closeConvert}/>
      )}
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
        .el-ins-matrix th:not(.el-ins-col-project):not(.el-ins-col-content) { min-width: 150px; }
        .el-ins-cell-current { background: #fffbe6; }
        .el-ins-cell-recorded { background: #f0f7ff; }
        .el-ins-cell-abnormal { background: #fff1f0; }
        .el-ins-legend-chip {
          display: inline-block; width: 10px; height: 10px; margin-right: 4px;
          border: 1px solid #e8e8e8; vertical-align: middle;
        }
        .el-ins-legend-current { background: #fffbe6; }
        .el-ins-legend-recorded { background: #f0f7ff; }
        .el-ins-legend-abnormal { background: #fff1f0; }
      `}</style>
    </AuthDiv>
  );
}

export default observer(InspectionWorksheet);

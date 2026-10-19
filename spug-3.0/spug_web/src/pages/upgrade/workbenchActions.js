/**
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 升级工作台动作层（从 WorkbenchForm 抽出）：
 * 只封装 http 调用 + store 刷新 + 消息提示的纯动作函数，
 * 不持有组件状态；组件层（WorkbenchForm 及其子组件）负责编排。
 */
import { http } from 'libs';
import { message, Modal } from 'antd';
import store from './store';

const STEP_ACTION_TEXT = {complete: '完成', skip: '已跳过', reset: '待执行'};
const NODE_ACTION_TEXT = {test_fail: '已标记失败'};

// 在途请求守卫：同一目标的相同动作在请求返回前不重复提交（jsdom/弱网双击防护）
const pendingStepKeys = new Set();
const pendingNodeKeys = new Set();

/**
 * 提交升级表单（新建/编辑共用）：经 formRef.current.submit(redirectMode) 触发，
 * 成功后回调 onSaveSuccess(recordId, redirectMode)。
 */
export function submitUpgradeForm({form, isNew, recordId, redirectMode, selectedPlan,
                                   onSaveStart, onSaveEnd, onSaveSuccess, onSaveError}) {
  form.validateFields().then(values => {
    if (onSaveStart) onSaveStart();
    const formData = {...values};

    if (formData.upgrade_time) {
      formData.upgrade_time = formData.upgrade_time.format('YYYY-MM-DD HH:mm:ss');
    }

    // 新建模式：状态由后端默认"处理中"，前端不传
    if (isNew) {
      delete formData.status;
    }

    const url = isNew
      ? '/api/upgrade/records/create/'
      : `/api/upgrade/records/${recordId}/update/`;
    const method = isNew ? 'post' : 'put';

    http[method](url, formData)
      .then((res) => {
        if (isNew && selectedPlan && res && res.id) {
          return store.applyPlan(selectedPlan.id, res.id)
            .then((applyRes) => {
              message.success(`创建成功，已应用方案「${selectedPlan.name}」${applyRes.created_count} 个步骤`);
              return res;
            })
            .catch(() => {
              message.warning('创建成功，方案步骤应用失败，可在工作台中手动应用');
              return res;
            });
        }
        message.success(isNew ? '创建成功' : '保存成功');
        return res;
      })
      .then((res) => {
        if (onSaveSuccess) onSaveSuccess(res && res.id, redirectMode);
      })
      .catch(() => {
        if (onSaveError) onSaveError();
      });
  }).catch(() => {
    if (onSaveError) onSaveError();
  });
}

/** 步骤操作（完成/跳过/重置），成功后刷新步骤、状态时间线、失败单与主记录 */
export function postStepAction(recordId, step, action) {
  const guardKey = `${step.id}::${action}`;
  if (pendingStepKeys.has(guardKey)) return;
  pendingStepKeys.add(guardKey);
  http.put(`/api/upgrade/record-steps/${step.id}/update/`, {action})
    .then(() => {
      const actionText = STEP_ACTION_TEXT[action] || '处理';
      message.success(`步骤已标记为${actionText}`);
      store.fetchRecordSteps(recordId);
      store.fetchStatusLogs(recordId);
      store.fetchFailures(recordId);
      store.fetchRecords();
      // 后端步骤联动会自动更新主表 status（全部完成→已完成等），同步刷新
      store.fetchRecord(recordId).catch(() => {});
    })
    .catch(() => {})
    .finally(() => pendingStepKeys.delete(guardKey));
}

/** 删除单个步骤 */
export function deleteStep(recordId, step) {
  http.delete(`/api/upgrade/record-steps/${step.id}/delete/`)
    .then(() => {
      message.success('步骤已删除');
      store.fetchRecordSteps(recordId);
      store.fetchRecords();
      // 删除步骤后后端会重算主表状态，同步刷新
      store.fetchRecord(recordId).catch(() => {});
    })
    .catch(() => {});
}

/** 手动添加步骤；返回 promise 供弹窗在成功后再关闭 */
export function addStep(recordId, values) {
  return http.post(`/api/upgrade/records/${recordId}/steps/add/`, values)
    .then(() => {
      message.success('步骤添加成功');
      store.fetchRecordSteps(recordId);
      // 新增待执行步骤可能触发主表状态回退（已完成→处理中），同步刷新
      store.fetchRecord(recordId).catch(() => {});
    });
}

/** 清空所有步骤 */
export function clearSteps(recordId) {
  http.delete(`/api/upgrade/records/${recordId}/steps/clear/`)
    .then(() => {
      message.success('已清空所有步骤');
      store.fetchRecordSteps(recordId);
    })
    .catch(() => {});
}

/** 应用方案步骤到升级记录；replace=true 时先删除现有步骤 */
function applyPlanSteps(recordId, planId, replace) {
  return store.applyPlan(planId, recordId, replace)
    .then(res => {
      const plan = (store.plans || []).find(p => p.id === planId);
      const parts = [`已应用方案${plan ? `「${plan.name}」` : ''}`];
      if (res.deleted_count > 0) {
        parts.push(`替换 ${res.deleted_count} 个旧步骤`);
      }
      parts.push(`新增 ${res.created_count} 个步骤`);
      message.success(parts.join('，'));
      store.fetchRecordSteps(recordId);
    })
    .catch(() => {
      // 失败提示由 http 拦截器统一弹出，这里仅吞掉拒绝避免 unhandled rejection
    });
}

/**
 * 编辑模式应用方案（带替换确认）：已有步骤时弹窗确认整体替换，
 * 已执行的步骤越多越谨慎（确认按钮标红）。
 */
export function applyPlanToRecord(recordId, planId, onSettled) {
  const plan = (store.plans || []).find(p => p.id === planId);
  if (!plan) {
    message.error('应用方案失败');
    if (onSettled) onSettled();
    return;
  }
  const existingSteps = store.recordSteps;
  const hasExisting = existingSteps.length > 0;

  if (!hasExisting) {
    applyPlanSteps(recordId, planId, false).finally(() => {
      if (onSettled) onSettled();
    });
    return;
  }

  const executedCount = existingSteps.filter(
    s => s.status === 'completed' || s.status === 'skipped'
  ).length;
  const content = executedCount > 0
    ? `当前已有 ${existingSteps.length} 个步骤（其中 ${executedCount} 个已执行），应用方案将替换所有现有步骤，是否继续？`
    : `当前已有 ${existingSteps.length} 个步骤，应用方案将替换所有现有步骤，是否继续？`;
  Modal.confirm({
    title: '应用方案将替换现有步骤',
    content,
    okText: '替换',
    cancelText: '取消',
    okButtonProps: {danger: executedCount > 0},
    onOk: () => applyPlanSteps(recordId, planId, true).finally(() => {
      if (onSettled) onSettled();
    }),
    onCancel: () => {
      if (onSettled) onSettled();
    },
  });
}

/**
 * 流程节点操作（标记失败），成功后刷新时间线与失败单。
 * 回退/重新执行不再走 status-logs 旧接口，由 RedoFromModal 调 redo-execute；
 * 暂停/继续已下线。
 */
export function postNodeAction(recordId, action, node) {
  const guardKey = `${action}::${node.label}`;
  if (pendingNodeKeys.has(guardKey)) return;
  pendingNodeKeys.add(guardKey);
  const payload = {
    action,
    remark: '',
    target_action: '',
    phase: action === 'test_fail' ? node.label : '',
  };
  http.post(`/api/upgrade/records/${recordId}/status-logs/`, payload)
    .then((res) => {
      message.success(NODE_ACTION_TEXT[action]);
      if (res && res.id) {
        store.statusLogs = [res, ...store.statusLogs];
        if (res.to_status && res.to_status !== res.from_status) {
          store.record.status = res.to_status;
        }
      } else {
        store.fetchStatusLogs(recordId);
      }
      store.fetchFailures(recordId);
      store.fetchRecords();
    })
    .catch(() => {})
    .finally(() => pendingNodeKeys.delete(guardKey));
}

/** 标记阶段失败（带原因）：走 status-logs 旧入口，失败单由后端创建 */
export function markPhaseFailure(recordId, phase, reason) {
  return http.post(`/api/upgrade/records/${recordId}/status-logs/`, {
    action: 'test_fail', phase, remark: reason,
  }).then(res => {
    message.success(`已标记【${phase}】失败，请在"处理失败"中选择重做范围`);
    if (res && res.id) {
      store.statusLogs = [res, ...store.statusLogs];
    } else {
      store.fetchStatusLogs(recordId);
    }
    store.fetchFailures(recordId);
    store.fetchRecords();
    return res;
  });
}

/** 开始重做：提交选定范围，成功后刷新步骤/时间线/失败单/主记录 */
export function startFailureRedo(recordId, failureId, {stepIds, allSteps, note}) {
  return http.post(
    `/api/upgrade/records/${recordId}/failures/${failureId}/start-redo/`,
    {step_ids: stepIds || [], all_steps: !!allSteps, note: note || ''},
  ).then(res => {
    const selected = (res && res.selected_count) || 0;
    const reset = (res && res.reset_count) || 0;
    message.success(`已开始重做：选择 ${selected} 个步骤，实际重置 ${reset} 个步骤`);
    store.fetchRecordSteps(recordId);
    store.fetchStatusLogs(recordId);
    store.fetchFailures(recordId);
    store.fetchRecord(recordId).catch(() => {});
    store.fetchRecords();
    return res;
  });
}

/** 更正失败记录（误标场景）：填写原因，追加更正事件 */
export function correctFailure(recordId, failureId, reason) {
  return http.post(
    `/api/upgrade/records/${recordId}/failures/${failureId}/correct/`,
    {reason},
  ).then(() => {
    message.success('已更正失败记录');
    store.fetchStatusLogs(recordId);
    store.fetchFailures(recordId);
    store.fetchRecord(recordId).catch(() => {});
    store.fetchRecords();
  });
}

/**
 * 从某阶段重新执行：目标阶段及后续阶段重新执行，前面阶段保持原状。
 * 仅重置工作清单，不代表软件/配置/数据库已实际回滚；
 * later_action: 'redo' 同时重新执行后续阶段 | 'keep' 保留后续结果（须填理由）。
 */
export function executeRedoFrom(recordId, {targetPhase, laterAction, laterReason, note}) {
  return http.post(`/api/upgrade/records/${recordId}/redo-execute/`, {
    target_phase: targetPhase,
    later_action: laterAction,
    later_reason: laterReason || '',
    note: note || '',
  }).then(res => {
    message.success(`已从「${targetPhase}」重新执行（仅重置工作清单）`);
    store.fetchRecordSteps(recordId);
    store.fetchStatusLogs(recordId);
    store.fetchFailures(recordId);
    store.fetchRecord(recordId).catch(() => {});
    store.fetchRecords();
    return res;
  });
}

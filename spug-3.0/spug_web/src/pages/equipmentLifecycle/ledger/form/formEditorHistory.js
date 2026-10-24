/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 数字表单模板编辑器本地撤销/重做历史（2026-10-23 P1 交互整理）。
 *
 * - 整快照栈：每次结构/属性变更前 push 整个 form 的深拷贝，栈上限 50 步、
 *   超出丢最旧；撤销恢复的删除恢复原对象原 id（这是撤销相对"重新添加"
 *   的核心价值）；新变更清空重做栈；关闭编辑器即整体丢弃；
 * - 文本连续输入合并：带 label 的变更（名称/说明/单位等文本输入）在
 *   1 秒窗口内且 label 相同时不重复 push，一次输入突发=一步撤销；
 *   结构变更（增删移复制/类型切换）不带 label，永远独立成步；
 * - 只服务编辑器本地草稿 state，不涉及服务端与台账数据；form 对象按
 *   不可变约定更新，undo/redo 直接共享引用安全。
 */
export const HISTORY_LIMIT = 50;
const COALESCE_WINDOW_MS = 1000;

export function deepClone(value) {
  return JSON.parse(JSON.stringify(value));
}

/**
 * 创建历史控制器。formRef 持有当前 form（与组件 state 同引用），
 * setForm 触发重渲染，notify 在历史栈变化时同步撤销/重做按钮状态。
 */
export function createFormHistory(formRef, setForm, notify) {
  const state = {past: [], future: [], lastLabel: null, lastAt: 0};

  /** 变更前登记快照；label 用于合并连续文本输入。 */
  const pushHistory = (snapshot, label) => {
    const now = Date.now();
    const coalesce = !!label && label === state.lastLabel
      && now - state.lastAt < COALESCE_WINDOW_MS;
    state.lastLabel = label || null;
    state.lastAt = now;
    if (coalesce) return;
    state.past.push(deepClone(snapshot));
    if (state.past.length > HISTORY_LIMIT) state.past.shift();
    state.future = [];
    notify();
  };

  const undo = () => {
    if (!state.past.length) return false;
    state.lastLabel = null;
    const previous = state.past.pop();
    state.future.push(formRef.current);
    formRef.current = previous;
    setForm(previous);
    notify();
    return true;
  };

  const redo = () => {
    if (!state.future.length) return false;
    state.lastLabel = null;
    const next = state.future.pop();
    state.past.push(formRef.current);
    formRef.current = next;
    setForm(next);
    notify();
    return true;
  };

  return {
    state, pushHistory, undo, redo,
    canUndo: () => state.past.length > 0,
    canRedo: () => state.future.length > 0,
    /** 历史边界（保存成功等）：终止文本输入合并，下一次编辑重新入栈，
     * 保证撤销能回到最近一次保存的基线状态。 */
    markBoundary: () => {
      state.lastLabel = null;
    },
    reset: () => {
      state.past = [];
      state.future = [];
      state.lastLabel = null;
      state.lastAt = 0;
      notify();
    },
  };
}

/**
 * Ctrl+Z / Ctrl+Shift+Z（Cmd 同理）绑定到 document；isActive 为假时不
 * 接管（编辑器关闭后浏览器默认行为不受影响）。返回解绑函数。
 */
export function bindHistoryShortcuts(isActive, undo, redo) {
  const onKeyDown = event => {
    if (!isActive()) return;
    if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== 'z') return;
    event.preventDefault();
    if (event.shiftKey) redo(); else undo();
  };
  document.addEventListener('keydown', onKeyDown);
  return () => document.removeEventListener('keydown', onKeyDown);
}

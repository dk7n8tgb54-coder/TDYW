/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 数字表单模板编辑器草稿状态 hook（2026-10-23 P1 交互整理）：
 * form / baseline / selection / 本地历史的集合管理。
 *
 * - dirty 由"当前 form ≠ 最近保存/载入基线"推导（而非累加标记）：
 *   撤销回基线自动视为干净；基线只在载入草稿/保存成功时更新；
 * - 编辑基线初始化：仅在该模板详情加载完成后的首次渲染执行一次；
 *   保存/发布回写的新详情对象不会重置本地编辑（保留输入中的未保存内容）；
 *   关闭编辑器即丢弃本地草稿并重置基线（dirty 归零）；
 * - 选中对象被删除等失效情形经 resolveSelection 校验后回退不选中；
 * - Ctrl+Z / Ctrl+Shift+Z 在编辑器可见期间由 bindHistoryShortcuts 接管；
 * - dirty 接入工作页签未保存保护（当前页签不参与自动淘汰）；
 * - draftGenRef 生命周期代号：保存/载入示例等异步回调发起时记录、回调时
 *   比对，编辑器已关闭或重开则丢弃过期回调，不写本地草稿状态。
 */
import {useEffect, useMemo, useRef, useState} from 'react';
import {resolveSelection} from './FormTemplateCanvas';
import {bindHistoryShortcuts, createFormHistory, deepClone} from './formEditorHistory';
import useWorkTabUnsaved from 'layout/useWorkTabUnsaved';
import {PROTOCOL_VERSION} from './constants';

export const EMPTY_FORM = {protocol_version: PROTOCOL_VERSION, groups: []};

export function useFormEditorDraft(store) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [baseline, setBaseline] = useState(EMPTY_FORM);
  const [selection, setSelection] = useState(null);
  const [, setHistoryTick] = useState(0);
  const formRef = useRef(form);
  const initializedIdRef = useRef(null);
  // 编辑器生命周期代号：草稿载入与关闭各递增。保存/载入示例等异步回调
  // 发起时记下代号、回调执行时比对——编辑器已关闭或重开则丢弃过期回调，
  // 不再写本地草稿状态（否则会让已关闭的编辑器重新登记"未保存"）
  const draftGenRef = useRef(0);
  const history = useMemo(
    () => createFormHistory(formRef, setForm, () => setHistoryTick(t => t + 1)), []);

  const dirty = useMemo(
    () => JSON.stringify(form) !== JSON.stringify(baseline), [form, baseline]);

  // 编辑基线初始化：仅在该模板详情加载完成后的首次渲染执行一次；
  // 关闭编辑器即丢弃本地草稿（重置基线使 dirty 归零，工作页签未保存登记
  // 随之清除）；保存/发布回写的新详情对象不会重置本地编辑。
  // 存量 v1 草稿：工作副本本地升级为 v2（新键缺省即 v1 语义），基线保留
  // 服务端原始草稿——仅协议升级也视为未保存修改（dirty=true），发布流程
  // 会先保存（显式升级动作），解决"无 dirty 不发保存请求"与"仅升级版本
  // 也需保存"的冲突；直接发布 v1 草稿被后端明确拒绝。
  // 未知未来版本（v3+）：保持原值不改写（改写即绕过后端"不支持的未来
  // 协议版本整体拒绝"的 fail-closed 语义），编辑器按不支持协议禁编辑保存
  //（见 unsupportedProtocol）。
  useEffect(() => {
    const template = store.editorTemplate;
    if (!store.editorVisible || !template) {
      initializedIdRef.current = null;
      draftGenRef.current += 1;
      formRef.current = EMPTY_FORM;
      setForm(EMPTY_FORM);
      setBaseline(EMPTY_FORM);
      history.reset();
      return;
    }
    if (store.editorLoading || store.editorLoadError) return;
    if (initializedIdRef.current === template.id) return;
    initializedIdRef.current = template.id;
    draftGenRef.current += 1;
    const draft = template.draft && template.draft.form;
    const base = draft && draft.groups && draft.groups.length ? draft : EMPTY_FORM;
    // 仅 v1 草稿本地升级为 v2；其他非 v2 版本保持原值（禁止编辑保存）
    const working = base.protocol_version === 1
      ? {...base, protocol_version: PROTOCOL_VERSION} : base;
    const workingClone = deepClone(working);
    formRef.current = workingClone;
    setForm(workingClone);
    setBaseline(deepClone(base));
    history.reset();
    setSelection(base.groups.length
      ? {type: 'group', groupId: base.groups[0].id} : null);
  }, [store.editorVisible, store.editorTemplate, store.editorLoading,
      store.editorLoadError, history]);

  // 不支持的协议版本（v3+ 等未知版本，非空草稿且非 v2）：编辑器禁编辑
  // 保存/发布——保存接口会整体拒绝，提前在界面 fail-closed，避免误编辑
  // 后无法保存的困惑；v1 已在载入时升级为 v2 工作副本，不落入本分支。
  const unsupportedProtocol = useMemo(
    () => form.groups.length > 0 && form.protocol_version !== PROTOCOL_VERSION,
    [form]);

  const selectionInfo = useMemo(
    () => resolveSelection(form, selection), [form, selection]);

  // 选中对象被删除等失效情形：回退到不选中
  useEffect(() => {
    if (selection && !selectionInfo) setSelection(null);
  }, [selection, selectionInfo]);

  // Ctrl+Z / Ctrl+Shift+Z：编辑器可见期间接管（history 句柄稳定）
  useEffect(() => bindHistoryShortcuts(
    () => store.editorVisible,
    () => history.undo(),
    () => history.redo(),
  ), [history, store.editorVisible]);

  // 工作页签未保存保护：dirty 期间当前页签不参与自动淘汰
  useWorkTabUnsaved(dirty);

  return {
    form, setForm, formRef, baseline, setBaseline, dirty, unsupportedProtocol,
    selection, setSelection, selectionInfo, history, draftGenRef,
  };
}

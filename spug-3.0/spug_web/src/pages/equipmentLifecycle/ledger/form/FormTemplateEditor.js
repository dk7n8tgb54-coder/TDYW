/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 数字表单模板编辑抽屉（2026-10-22 三栏改版；2026-10-23 P1 交互整理，
 * 同日 P2 属性与校验增强）：
 * 左分组目录（导航/选中/分组排序）+ 中表单画布（预览/改名/新增/复制/删除/
 * 排序）+ 右选中项设置；不做通用电子表格/任意拖拽排版。
 *
 * - 草稿加载三态：加载中（不渲染可编辑内容）、加载失败（错误页 + 重试，
 *   禁止保存/发布/载入示例/预览，避免误操作空白表单）、已加载（列表行
 *   只有摘要，openEditor 统一按 id 拉取完整详情后才初始化编辑基线；
 *   确实没有草稿时呈现可编辑的空画布并给出引导）；存量 v1 草稿打开即
 *   本地升级为 v2 并以未保存修改呈现，显式保存后才能发布；
 * - 三栏职责单一化：结构操作贴内容在画布，数值配置在右栏，导航与分组
 *   排序在左栏，同一操作只有一个主入口；窄屏右栏仍进抽屉；
 * - 桌面三栏固定高度布局（2026-10-24）：抽屉 body 不再整页滚动，长画布
 *   在中栏内部滚动，左分组目录与右检查器为独立滚动容器——浏览长表单
 *   时两侧面板保持可见、可操作；抽屉头部/底部操作区由 Drawer 自身
 *   flex 布局承载，不与面板滚动叠加；窄屏（<992）与草稿加载中/失败态
 *   保持默认整页滚动，不强行三栏；
 * - 新增/复制自动选中新对象并滚动定位；复制一律生成全新结构 id（genId），
 *   名称自动追加"副本"；撤销恢复的删除恢复原对象原 id；
 * - 撤销/重做：本地整快照历史（formEditorHistory），画布顶部工具栏 +
 *   Ctrl+Z / Ctrl+Shift+Z，上限 50 步，关闭编辑器即丢弃；
 * - dirty 由"当前 form ≠ 最近保存/载入基线"推导：撤销回基线自动干净；
 *   基线只在载入草稿/保存成功时更新；保存草稿无 dirty 不发请求；
 *   dirty 接入工作页签未保存保护；
 * - 发布流程（P2，先检查后保存）：先对当前内容做无状态 publish-check
 *   （携带未保存 form——非法未保存草稿也能立即得到结构化、可点击定位的
 *   错误，不必先保存成功）→ 有阻断错误仅弹窗展示不保存不发布 → 无阻断
 *   错误时保存未保存内容（失败中止）→ 弹窗确认后发布；发布按钮在后端
 *   真实成功后才给成功反馈；检查/保存在途冻结全部编辑入口（回调使用
 *   点击时的表单快照，放行编辑会检查或保存旧内容），编辑器关闭立即
 *   清锁并作废在途令牌（旧请求的清理只属于旧生命周期，不得解开新
 *   检查的锁）；不支持的协议版本
 *   （v3+ 等）保持原值不改写，编辑器禁编辑保存（fail-closed，与后端
 *   整体拒绝一致）——两者经 editLocked 统一作用到画布/左栏/检查器
 *   （pointer-events 禁用 + 冻结 mutators + 撤销重做守卫双保险）；
 * - 两种预览（P2）：填写预览支持试填（值仅存弹窗本地内存，关闭即丢弃，
 *   不发任何写请求）；PDF 样张基于已保存草稿，另提供"保存草稿并预览
 *   样张"一步路径（保存失败中止生成）；
 * - 草稿未保存时关闭抽屉先确认。
 */
import React, {useEffect, useRef, useState} from 'react';
import {observer} from 'mobx-react';
import {Alert, Button, Drawer, Empty, Modal, Result, Space, Spin} from 'antd';
import {ArrowDownOutlined, ArrowUpOutlined, RedoOutlined, UndoOutlined} from '@ant-design/icons';
import FormTemplateCanvas, {
  cloneGroup, moveItem, newGroup, scrollSelectionIntoView,
} from './FormTemplateCanvas';
import FormTemplateInspector from './FormTemplateInspector';
import FormFillRenderer, {applyFillEdit, useNarrowViewport} from './FormFillRenderer';
import FormPublishCheckModal from './FormPublishCheckModal';
import {GROUP_KIND_TEXT} from './constants';
import {deepClone} from './formEditorHistory';
import {EMPTY_FORM, useFormEditorDraft} from './useFormEditorDraft';

/** 草稿变更动作（新增/删除/移动/插入分组、按 id 更新分组）。
 * 编辑器本体只持 form state，结构变换统一经本工厂产生不可变更新；
 * 每次变更先经 pushHistory 登记撤销快照（label 用于合并连续文本输入）。 */
function createFormDraftMutators(formRef, setForm, pushHistory) {
  const mutate = (updater, label) => {
    pushHistory(formRef.current, label);
    const next = updater(formRef.current);
    formRef.current = next;
    setForm(next);
  };
  const updateGroup = (groupId, updater, label) => {
    mutate(prev => ({
      ...prev,
      groups: prev.groups.map(group => group.id === groupId ? updater(group) : group),
    }), label);
  };
  const addGroup = kind => {
    const group = newGroup(kind);
    mutate(prev => ({...prev, groups: [...prev.groups, group]}));
    return group.id;
  };
  const removeGroup = groupId => {
    mutate(prev => {
      const groups = prev.groups.filter(group => group.id !== groupId);
      return {...prev, groups};
    });
  };
  const moveGroup = (groupId, dir) => {
    mutate(prev => {
      const index = prev.groups.findIndex(group => group.id === groupId);
      return {...prev, groups: moveItem(prev.groups, index, dir)};
    });
  };
  const insertGroupAfter = (afterGroupId, group) => {
    mutate(prev => {
      const index = prev.groups.findIndex(item => item.id === afterGroupId);
      const groups = [...prev.groups];
      groups.splice(index + 1, 0, group);
      return {...prev, groups};
    });
  };
  return {updateGroup, addGroup, removeGroup, moveGroup, insertGroupAfter};
}

/** 关闭编辑抽屉：有未保存修改先确认（已保存草稿不受影响）。 */
function confirmCloseEditor(dirty, onClose) {
  if (!dirty) {
    onClose();
    return;
  }
  Modal.confirm({
    title: '有未保存的草稿修改',
    content: '关闭后本次修改不会保留（已保存的草稿不受影响），确定关闭？',
    okText: '不保存并关闭', okButtonProps: {danger: true}, cancelText: '继续编辑',
    onOk: onClose,
  });
}

/** 桌面三栏布局的抽屉 body 样式：body 高度固定不整页滚动，滚动下沉到
 * 三栏各自的内部滚动容器（见 EditorLoadedBody）。窄屏与加载中/失败态
 * 不启用（保持默认整页滚动）。 */
const EDITOR_DESKTOP_BODY_STYLE = {
  display: 'flex', flexDirection: 'column', overflow: 'hidden',
};

/** 左侧分组目录：导航/选中（点击滚动定位到画布分组）与分组排序；
 * 分组新增/删除/复制在画布，同一操作只有一个主入口。
 * 桌面布局下为独立滚动面板（目录列表内部滚动，标题常驻）。 */
function GroupListPanel({form, selection, onSelect, onMoveGroup, narrow}) {
  const activeId = selection && selection.groupId;
  return (
    <div data-testid="editor-group-panel"
         style={narrow ? {width: '100%', flexShrink: 0} : {
           width: 200, flexShrink: 0, display: 'flex',
           flexDirection: 'column', minHeight: 0}}>
      <div style={{color: '#999', fontSize: 12, marginBottom: 6, flexShrink: 0}}>
        分组目录
      </div>
      <div data-testid="editor-group-list"
           style={narrow ? undefined : {flex: 1, minHeight: 0, overflowY: 'auto'}}>
        {form.groups.map((group, index) => {
          const active = activeId === group.id;
          return (
            <div key={group.id} data-testid={`editor-group-${group.id}`}
                 onClick={() => onSelect({type: 'group', groupId: group.id})}
                 style={{
                   padding: '6px 10px', marginBottom: 4, cursor: 'pointer',
                   borderRadius: 4, display: 'flex', alignItems: 'center',
                   background: active ? '#e6f7ff' : '#fafafa',
                   border: active ? '1px solid #91d5ff' : '1px solid transparent',
                 }}>
              <span style={{flex: 1, overflow: 'hidden', textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap'}}>
                {group.name}
              </span>
              <span style={{color: '#999', marginLeft: 6, fontSize: 12, flexShrink: 0}}>
                {GROUP_KIND_TEXT[group.kind]}
              </span>
              <span style={{flexShrink: 0}} onClick={e => e.stopPropagation()}>
                <Button size="small" type="text" title="上移分组"
                        icon={<ArrowUpOutlined/>} disabled={index === 0}
                        data-testid={`editor-group-up-${group.id}`}
                        onClick={() => onMoveGroup(group.id, -1)}/>
                <Button size="small" type="text" title="下移分组"
                        icon={<ArrowDownOutlined/>}
                        disabled={index === form.groups.length - 1}
                        data-testid={`editor-group-down-${group.id}`}
                        onClick={() => onMoveGroup(group.id, 1)}/>
              </span>
            </div>
          );
        })}
        {!form.groups.length && (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无分组"/>
        )}
      </div>
    </div>
  );
}

/** 画布顶部工具栏：撤销/重做（本地快照历史；Ctrl+Z / Ctrl+Shift+Z 同效）。
 * 桌面布局下常驻中栏顶部（不随画布滚动）。 */
function EditorToolbar({canUndo, canRedo, onUndo, onRedo}) {
  return (
    <div style={{display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8,
                 flexShrink: 0}}>
      <Button size="small" icon={<UndoOutlined/>} disabled={!canUndo}
              data-testid="editor-undo" onClick={onUndo}>撤销</Button>
      <Button size="small" icon={<RedoOutlined/>} disabled={!canRedo}
              data-testid="editor-redo" onClick={onRedo}>重做</Button>
      <span style={{color: '#bbb', fontSize: 12}}>Ctrl+Z 撤销 · Ctrl+Shift+Z 重做</span>
    </div>
  );
}

/** 抽屉底部操作条（载入示例/预览/预览PDF/保存并预览样张/保存草稿/发布；
 * 草稿加载中或失败时全部禁用）。容器与两组按钮均可换行：窄屏（实测
 * 390px）按钮总宽超容器时折行而非溢出，发布按钮保持可见可达。 */
function EditorFooter({dirty, savingDraft, publishing, actionsDisabled, onLoadSample,
                       onPreview, onPreviewPdf, onSaveAndPreviewPdf, onSave, onPublish}) {
  return (
    <div style={{display: 'flex', justifyContent: 'space-between',
                 flexWrap: 'wrap', gap: 8}}>
      <Space wrap>
        <Button data-testid="editor-load-sample" disabled={actionsDisabled}
                onClick={onLoadSample}>载入示例</Button>
        <Button data-testid="editor-preview" disabled={actionsDisabled}
                onClick={onPreview}>预览</Button>
        <Button data-testid="editor-preview-pdf" disabled={actionsDisabled}
                onClick={onPreviewPdf}>预览 PDF</Button>
        <Button data-testid="editor-save-preview-pdf" disabled={actionsDisabled}
                loading={savingDraft}
                onClick={onSaveAndPreviewPdf}>保存草稿并预览样张</Button>
      </Space>
      <Space wrap>
        {dirty && <span style={{color: '#fa8c16'}}>有未保存修改</span>}
        <Button loading={savingDraft} disabled={actionsDisabled}
                data-testid="editor-save-draft" onClick={onSave}>保存草稿</Button>
        <Button type="primary" loading={publishing} disabled={actionsDisabled}
                data-testid="editor-publish" onClick={onPublish}>发布版本</Button>
      </Space>
    </div>
  );
}

/** 草稿加载中占位（不渲染任何可编辑内容）。 */
function EditorLoading() {
  return (
    <div style={{padding: '90px 0', textAlign: 'center'}}>
      <Spin size="large"/>
      <div style={{marginTop: 12, color: '#999'}}>正在加载模板草稿…</div>
    </div>
  );
}

/** 草稿加载失败页：禁止一切写操作，提供重试与关闭。 */
function EditorLoadError({error, onRetry, onClose}) {
  return (
    <Result status="warning" title="模板草稿加载失败"
            subTitle={`${error}。为避免覆盖已保存内容，保存与发布已禁用。`}
            extra={
              <Space>
                <Button type="primary" data-testid="editor-load-retry"
                        onClick={onRetry}>重新加载</Button>
                <Button onClick={onClose}>关闭</Button>
              </Space>
            }/>
  );
}

/** 已加载态主体：无草稿引导 + 左目录/中画布/右检查器（窄屏检查器进抽屉）。
 * editLocked（不支持的协议版本/发布检查在途）：编辑区 pointer-events 禁用
 * 并降透明度，配合冻结 mutators 双保险，画布与检查器不可改变本地表单。
 * 桌面布局（2026-10-24）：三栏等高拉伸，画布在中栏内部滚动，左右面板
 * 各自内部滚动（长表单浏览时保持可见可操作）；窄屏维持原有文档流滚动。 */
function EditorLoadedBody({template, form, selection, setSelection, selectionInfo,
                           narrow, mutators, historyControls, selectAndScroll,
                           unsupportedProtocol, editLocked}) {
  const draftMissing = !(template.draft && template.draft.form
    && template.draft.form.groups && template.draft.form.groups.length);
  const {updateGroup} = mutators;
  const canvasProps = {
    form, selection, updateGroup, addGroup: mutators.addGroupAndSelect,
    removeGroup: mutators.removeGroupAndReselect,
    copyGroup: mutators.copyGroupAndSelect,
    onSelect: setSelection,
  };
  const inspectorProps = {selectionInfo, updateGroup};
  return (
    <div style={narrow ? undefined
      : {display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0}}>
      {unsupportedProtocol && (
        <Alert type="error" showIcon style={{marginBottom: 12}}
               message="草稿协议版本不支持，已禁用编辑与发布"
               description={`该草稿使用协议 v${form.protocol_version}，当前版本不支持；`
                 + '为避免保存被整体拒绝或覆盖内容，编辑、保存、发布与载入示例均已禁用。'
                 + '请升级系统后重试。'}/>
      )}
      {draftMissing && !unsupportedProtocol && (
        <div style={{background: '#fffbe6', border: '1px solid #ffe58f',
                     borderRadius: 4, padding: '6px 12px', marginBottom: 12}}>
          该模板尚未编辑过表单内容，从画布下方添加第一个分组开始。
        </div>
      )}
      <div data-testid="editor-edit-area"
           style={{
             display: 'flex', gap: 16,
             alignItems: narrow ? 'flex-start' : 'stretch',
             flexWrap: narrow ? 'wrap' : 'nowrap',
             ...(narrow ? {} : {flex: 1, minHeight: 0}),
             pointerEvents: editLocked ? 'none' : 'auto',
             opacity: editLocked ? 0.6 : 1}}>
        <GroupListPanel form={form} selection={selection}
                        onSelect={selectAndScroll} onMoveGroup={mutators.moveGroup}
                        narrow={narrow}/>
        <div style={narrow ? {flex: '1 1 100%', minWidth: 0} : {
          flex: '1 1 auto', minWidth: 0, display: 'flex',
          flexDirection: 'column', minHeight: 0}}>
          <EditorToolbar canUndo={historyControls.canUndo}
                         canRedo={historyControls.canRedo}
                         onUndo={historyControls.undo} onRedo={historyControls.redo}/>
          <div data-testid="editor-canvas-scroll"
               style={narrow ? undefined : {flex: 1, minHeight: 0, overflowY: 'auto'}}>
            <FormTemplateCanvas {...canvasProps}/>
          </div>
        </div>
        {!narrow && (
          <div data-testid="editor-inspector-panel"
               style={{width: 300, flexShrink: 0, display: 'flex',
                       flexDirection: 'column', minHeight: 0}}>
            <div data-testid="editor-inspector-scroll"
                 style={{flex: 1, minHeight: 0, overflowY: 'auto'}}>
              <FormTemplateInspector {...inspectorProps}/>
            </div>
          </div>
        )}
      </div>
      {narrow && (
        <Drawer title="选中项设置" placement="right" width="85%"
                visible={!!selectionInfo} destroyOnClose
                onClose={() => setSelection(null)}>
          <FormTemplateInspector {...inspectorProps}/>
        </Drawer>
      )}
    </div>
  );
}

/** 示例表单应用到编辑器本地状态（登记撤销快照并选中新首分组）。 */
function applySampleToState(sample, formRef, setForm, pushHistory, setSelection) {
  pushHistory(formRef.current);
  formRef.current = sample;
  setForm(sample);
  setSelection(sample.groups.length
    ? {type: 'group', groupId: sample.groups[0].id} : null);
}

/** 载入示例确认：有未保存内容时先确认覆盖。 */
function confirmLoadSample(dirty, hasGroups, proceed) {
  if (!dirty || !hasGroups) {
    proceed();
    return;
  }
  Modal.confirm({
    title: '载入示例将覆盖当前未保存的表单内容',
    okText: '覆盖载入', cancelText: '取消',
    onOk: proceed,
  });
}

/** 试填预览弹层：以当前未保存结构渲染可编辑表单，验证异常说明联动、
 * 明细加行、矩阵逐格填写的手感。试填值仅存弹窗本地内存（applyFillEdit
 * 纯函数不可变更新），关闭即重置丢弃——不写草稿、不发任何写请求
 * （Modal 组件常驻，destroyOnClose 只销毁子级，本地值须显式清理）；
 * 窄屏传 narrow（矩阵逐列卡片），与台账填写页同一渲染口径。 */
function PreviewModal({visible, form, onClose}) {
  const narrow = useNarrowViewport(768);
  const [trialValues, setTrialValues] = useState({});
  useEffect(() => {
    if (!visible) setTrialValues({});
  }, [visible]);
  return (
    <Modal title="填写预览（以当前未保存内容为准）" visible={visible}
           width={820} destroyOnClose onCancel={onClose}
           footer={
             <Space>
               <Button data-testid="preview-clear-trial" onClick={() => setTrialValues({})}>
                 清空试填
               </Button>
               <Button type="primary" onClick={onClose}>关闭</Button>
             </Space>
           }>
      <Alert type="warning" showIcon style={{marginBottom: 12}}
             message="试填内容不会保存，关闭弹窗即丢弃"/>
      {form.groups.length ? (
        <FormFillRenderer form={form} values={trialValues} editable
                          narrow={narrow}
                          onEdit={(kind, ...args) => setTrialValues(
                            current => applyFillEdit(current, kind, ...args))}/>
      ) : (
        <Empty description="暂无分组内容"/>
      )}
    </Modal>
  );
}

/**
 * 模板样张 PDF 弹层：打开时按已保存草稿请求后端生成（POST preview/pdf/），
 * iframe 内嵌展示 + 页数/纸张反馈；生成失败显示失败态可重试。
 * 关闭时释放 blob URL（closeSamplePdf）。
 * observer：弹窗读取 store 的加载/失败/URL 状态，必须订阅变更。
 */
const SamplePdfModal = observer(function SamplePdfModal({visible, template, store, onClose}) {
  useEffect(() => {
    if (visible && template) {
      store.fetchSamplePdf(template.id).catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, template && template.id]);
  return (
    <Modal title={`模板样张 PDF：${template ? template.name : ''}`} visible={visible}
           footer={<Button onClick={onClose}>关闭</Button>}
           onCancel={onClose} width={900} destroyOnClose>
      {store.samplePdfError ? (
        <Empty description={
          <span>
            {store.samplePdfError}
            <Button type="link" size="small" data-testid="form-sample-pdf-retry"
                    onClick={() => store.fetchSamplePdf(template && template.id).catch(() => {})}>
              重新生成
            </Button>
          </span>}/>
      ) : store.samplePdfUrl ? (
        <div data-testid="form-sample-pdf-body">
          <div style={{marginBottom: 8, color: '#999', fontSize: 12}}
               data-testid="form-sample-pdf-meta">
            {store.samplePdfMeta && store.samplePdfMeta.pages
              ? `共 ${store.samplePdfMeta.pages} 页` : ''}
            {store.samplePdfMeta && store.samplePdfMeta.paper
              ? ` · ${store.samplePdfMeta.paper}` : ''}
            {' '}· 样张基于已保存的草稿生成
          </div>
          <iframe title="模板样张 PDF" src={store.samplePdfUrl}
                  style={{width: '100%', height: 560, border: '1px solid #e8e8e8'}}
                  data-testid="form-sample-pdf-iframe"/>
        </div>
      ) : (
        <div style={{padding: '80px 0', textAlign: 'center'}}>
          <Spin/>
          <div style={{marginTop: 12, color: '#999'}}>正在生成模板样张…</div>
        </div>
      )}
    </Modal>
  );
});

/** 编辑器动作工厂（载入示例/保存草稿/发布检查/发布/预览样张），独立于
 * 组件渲染。异步回调执行前经 draftGenRef 比对生命周期代号：编辑器已关闭
 * 或重开时丢弃过期回调，不写本地草稿状态（否则已关闭的编辑器会重新登记
 * 未保存）。 */
function createEditorHandlers(deps) {
  const {store, template, form, formRef, draftGenRef, dirty, history,
         setBaseline, setForm, actionsDisabled, setSelection, openSamplePdf,
         openPublishCheck, publishChecking, setPublishChecking,
         checkSeqRef} = deps;

  const handleLoadSample = () => {
    const gen = draftGenRef.current;
    confirmLoadSample(dirty, !!form.groups.length,
      () => store.loadSample().then(sample => {
        if (draftGenRef.current !== gen) return;
        applySampleToState(
          sample, formRef, setForm, history.pushHistory, setSelection);
      }));
  };

  // 无 dirty 修改时不发送保存请求（服务端整体替换，重复保存无意义）
  const handleSaveDraft = () => {
    if (actionsDisabled || !dirty) return;
    const gen = draftGenRef.current;
    const snapshot = form;
    store.saveDraftForm(template.id, snapshot).then(() => {
      if (draftGenRef.current !== gen) return;
      // 保存成功是历史边界：终止文本输入合并，撤销可回到本次保存的基线
      history.markBoundary();
      setBaseline(deepClone(snapshot));
    }).catch(() => {});
  };

  /** 保存未保存内容后继续（无 dirty 直接继续）；保存失败（结构校验等）
   * 由拦截器提示并中止后续动作——发布不基于未保存内容，样张不基于
   * 过期草稿。返回 Promise（含失败吞并，调用方可接续解锁等收尾）。 */
  const saveThen = proceed => {
    if (!dirty) {
      proceed();
      return Promise.resolve();
    }
    const gen = draftGenRef.current;
    const snapshot = form;
    return store.saveDraftForm(template.id, snapshot).then(() => {
      if (draftGenRef.current !== gen) return;
      history.markBoundary();
      setBaseline(deepClone(snapshot));
      proceed();
    }).catch(() => {});
  };

  /** 发布入口（先检查后保存，检查期间锁定编辑）：
   * 1. 先对当前内容做无状态 publish-check——非法未保存草稿也能立即得到
   *    结构化、可点击定位的错误，不必先保存成功；
   * 2. 检查/随后保存的在途期间冻结全部编辑入口（回调使用点击时捕获的
   *    表单快照，期间放行编辑会检查或保存旧内容）；
   * 3. 有阻断错误只弹窗展示，不保存不发布；无阻断错误时保存未保存内容
   *    （失败中止、弹窗不出现）→ 弹窗确认后发布（后端行锁内仍会重新
   *    全量校验）。
   * 清锁仅作用于自己发起的检查生命周期（checkSeqRef 令牌）：编辑器关闭
   * 立即清锁并作废在途令牌，旧请求返回不得解开新检查的锁。 */
  const handlePublish = () => {
    if (actionsDisabled || publishChecking) return;
    const gen = draftGenRef.current;
    const token = ++checkSeqRef.current;
    const unlockIfCurrent = () => {
      if (checkSeqRef.current === token) setPublishChecking(false);
    };
    setPublishChecking(true);
    store.publishCheck(template.id, form).then(issues => {
      if (draftGenRef.current !== gen) {
        unlockIfCurrent();
        return;
      }
      if (issues.errors.length) {
        unlockIfCurrent();
        openPublishCheck(issues);
        return;
      }
      saveThen(() => {
        if (draftGenRef.current !== gen) return;
        openPublishCheck(issues);
      }).then(unlockIfCurrent);
    }).catch(unlockIfCurrent);
  };

  /** 预览 PDF：基于已保存草稿生成样张；有未保存修改先明确提示。 */
  const handlePreviewPdf = () => {
    if (!dirty) {
      openSamplePdf();
      return;
    }
    Modal.confirm({
      title: '预览 PDF 将基于已保存的草稿生成',
      content: '当前有未保存的修改不会包含在样张中；如需包含，请先保存草稿再预览，'
        + '或使用「保存草稿并预览样张」一步完成。',
      okText: '继续预览', cancelText: '取消',
      onOk: openSamplePdf,
    });
  };

  /** 保存草稿并预览样张（一步）：无 dirty 直接预览；有 dirty 先保存，
   * 保存失败（结构校验）中止并提示，不基于过期草稿生成。 */
  const handleSaveAndPreviewPdf = () => {
    if (actionsDisabled) return;
    saveThen(openSamplePdf);
  };

  return {handleLoadSample, handleSaveDraft, handlePublish,
          handlePreviewPdf, handleSaveAndPreviewPdf};
}

/** 冻结 mutators：不支持的协议版本或发布检查在途时，画布/左栏/检查器
 * 的全部结构编辑入口（改名/类型/复制/排序/删除/新增）为 no-op，保证本地
 * 表单不可被改变——与界面 pointer-events 禁用互为兜底（后者可被键盘
 * 焦点绕过）。 */
function freezeMutators() {
  const noop = () => {};
  return {updateGroup: noop, moveGroup: noop, addGroupAndSelect: noop,
          copyGroupAndSelect: noop, removeGroupAndReselect: noop};
}

/** 画布 mutators 组装：新增/复制自动选中滚动定位、删除后重选（收口于
 * 一处，编辑器组件本体只负责装配）。 */
function createCanvasMutators(base, deps) {
  const {formRef, selection, setSelection, selectAndScroll} = deps;
  const {updateGroup, moveGroup, addGroup, removeGroup, insertGroupAfter} = base;
  return {
    updateGroup, moveGroup,
    addGroupAndSelect: kind => {
      const groupId = addGroup(kind);
      selectAndScroll({type: 'group', groupId});
    },
    copyGroupAndSelect: groupId => {
      const source = formRef.current.groups.find(item => item.id === groupId);
      if (!source) return;
      const clone = cloneGroup(source);
      insertGroupAfter(groupId, clone);
      selectAndScroll({type: 'group', groupId: clone.id});
    },
    removeGroupAndReselect: groupId => {
      removeGroup(groupId);
      if (selection && selection.groupId === groupId) {
        const rest = formRef.current.groups.filter(group => group.id !== groupId);
        setSelection(rest.length ? {type: 'group', groupId: rest[0].id} : null);
      }
    },
  };
}

/** 编辑器弹层集合：试填预览 / 样张 PDF / 发布检查（各自关闭时清理）。 */
function EditorModals({previewVisible, setPreviewVisible, form,
                       samplePdfVisible, setSamplePdfVisible, template, store,
                       publishIssues, setPublishIssues, onLocate}) {
  return (
    <React.Fragment>
      <PreviewModal visible={previewVisible} form={form}
                    onClose={() => setPreviewVisible(false)}/>
      <SamplePdfModal visible={samplePdfVisible} template={template} store={store}
                      onClose={() => {
                        setSamplePdfVisible(false);
                        store.closeSamplePdf();
                      }}/>
      <FormPublishCheckModal
        visible={publishIssues !== null}
        issues={publishIssues}
        publishing={store.publishing}
        onClose={() => setPublishIssues(null)}
        onLocate={onLocate}
        onPublish={() => {
          setPublishIssues(null);
          store.publish(template.id).catch(() => {});
        }}/>
    </React.Fragment>
  );
}

function FormTemplateEditor({store}) {
  const template = store.editorTemplate;
  const {form, setForm, formRef, setBaseline, dirty, unsupportedProtocol,
          selection, setSelection, selectionInfo, history, draftGenRef} =
    useFormEditorDraft(store);
  const [previewVisible, setPreviewVisible] = useState(false);
  const [samplePdfVisible, setSamplePdfVisible] = useState(false);
  // 发布检查结果（null=弹窗关闭；{errors, warnings}=弹窗打开）
  const [publishIssues, setPublishIssues] = useState(null);
  // 发布检查在途：锁定全部编辑入口（检查/保存回调使用点击时的表单快照）
  const [publishChecking, setPublishChecking] = useState(false);
  // 检查生命周期令牌：每次发起新检查递增；关闭编辑器时作废在途令牌并
  // 立即清锁——挂起的旧请求返回时令牌不匹配，解锁回调为 no-op，不得
  // 解开新检查的锁（关闭/重开竞态，与 draftGenRef 同一思路）
  const checkSeqRef = useRef(0);
  const narrow = useNarrowViewport(992);
  const baseMutators = createFormDraftMutators(formRef, setForm, history.pushHistory);

  // 关闭编辑器立即清检查锁：不等在途请求返回（挂起请求不得让重开的
  // 编辑器持续锁定），并作废在途令牌（旧请求的清理只属于旧生命周期）
  useEffect(() => {
    if (!store.editorVisible) {
      checkSeqRef.current += 1;
      setPublishChecking(false);
    }
  }, [store.editorVisible]);

  if (!template) return null;

  // 加载中/加载失败/不支持的协议版本/发布检查在途：全部写操作禁用
  const actionsDisabled = store.editorLoading || !!store.editorLoadError
    || unsupportedProtocol || publishChecking;
  // 编辑锁定（画布/左栏/检查器 pointer-events 禁用 + mutators 冻结）：
  // 不支持的协议版本（保持原值不可改写），或发布检查在途（快照一致性）
  const editLocked = unsupportedProtocol || publishChecking;
  const selectAndScroll = sel => {
    setSelection(sel);
    scrollSelectionIntoView(sel);
  };

  /** 发布检查条目点击定位：关闭弹窗并选中对应对象滚动定位
   * （anchor 与 selection 同构；分组/字段/检查项/矩阵列均可定位）。 */
  const locatePublishIssue = anchor => {
    setPublishIssues(null);
    if (!anchor || !anchor.groupId) return;
    selectAndScroll({
      type: anchor.type || 'group',
      groupId: anchor.groupId,
      fieldId: anchor.fieldId,
      columnId: anchor.columnId,
    });
  };

  const mutators = editLocked
    ? freezeMutators()
    : createCanvasMutators(baseMutators,
      {formRef, selection, setSelection, selectAndScroll});

  const {
    handleLoadSample, handleSaveDraft, handlePublish, handlePreviewPdf,
    handleSaveAndPreviewPdf,
  } = createEditorHandlers({
    store, template, form, formRef, draftGenRef, dirty, history, setBaseline,
    setForm, actionsDisabled, setSelection,
    openSamplePdf: () => setSamplePdfVisible(true),
    openPublishCheck: issues => setPublishIssues(issues),
    publishChecking, setPublishChecking, checkSeqRef,
  });

  const handleClose = () => confirmCloseEditor(dirty, () => store.closeEditor());

  return (
    <Drawer
      title={`编辑表单：${template.name}${template.latest_version_no ? `（最新版本 v${template.latest_version_no}）` : ''}`}
      visible={store.editorVisible} onClose={handleClose} width="86%"
      destroyOnClose
      bodyStyle={(!narrow && !store.editorLoading && !store.editorLoadError)
        ? EDITOR_DESKTOP_BODY_STYLE : undefined}
      footer={
        <EditorFooter
          dirty={dirty} savingDraft={store.savingDraft}
          publishing={store.publishing || publishChecking}
          actionsDisabled={actionsDisabled} onLoadSample={handleLoadSample}
          onPreview={() => setPreviewVisible(true)}
          onPreviewPdf={handlePreviewPdf}
          onSaveAndPreviewPdf={handleSaveAndPreviewPdf}
          onSave={handleSaveDraft} onPublish={handlePublish}/>
      }>
      {store.editorLoading ? (
        <EditorLoading/>
      ) : store.editorLoadError ? (
        <EditorLoadError error={store.editorLoadError}
                         onRetry={() => store.retryLoadEditor()}
                         onClose={() => store.closeEditor()}/>
      ) : (
        <EditorLoadedBody template={template} form={form} selection={selection}
                          setSelection={setSelection} selectionInfo={selectionInfo}
                          narrow={narrow} mutators={mutators}
                          historyControls={{
                            canUndo: history.canUndo() && !editLocked,
                            canRedo: history.canRedo() && !editLocked,
                            undo: () => { if (!editLocked) history.undo(); },
                            redo: () => { if (!editLocked) history.redo(); },
                          }}
                          selectAndScroll={selectAndScroll}
                          unsupportedProtocol={unsupportedProtocol}
                          editLocked={editLocked}/>
      )}
      <EditorModals
        previewVisible={previewVisible} setPreviewVisible={setPreviewVisible}
        form={form} samplePdfVisible={samplePdfVisible}
        setSamplePdfVisible={setSamplePdfVisible} template={template} store={store}
        publishIssues={publishIssues} setPublishIssues={setPublishIssues}
        onLocate={locatePublishIssue}/>
    </Drawer>
  );
}

export default observer(FormTemplateEditor);

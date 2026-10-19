/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 原生台账模板编辑宿主（iframe 壳 + 工具栏）。
 *
 * 工具栏动作（保存草稿/发布版本）先经消息桥 collect 编辑器全量状态
 * （快照/绑定/纸张），再调用后端正式接口；发布 = 先保存草稿再 POST
 * publish（服务端把草稿快照落为不可变版本）。保存成功后通知编辑器
 * 复位脏标记；返回列表前有未保存修改先确认。
 */
import React, {useEffect, useRef} from 'react';
import {observer} from 'mobx-react';
import {Alert, Button, Modal, Space, Tag, message} from 'antd';
import {ArrowLeftOutlined, SaveOutlined, ThunderboltOutlined} from '@ant-design/icons';

import {useEditorChannel} from './bridge';
import EditorIframePane from './EditorIframePane';
import {LEDGER_TYPE_TEXT} from '../constants';

const STATUS_TEXT = {draft: '草稿', published: '已发布', used: '使用中', deleted: '已停用'};

/** 编辑器工具栏：返回 / 模板状态 / 保存草稿 / 发布版本。 */
function EditorToolbar({detail, store, onSave, onPublish, onBack}) {
  return (
    <div style={{marginBottom: 10, display: 'flex', alignItems: 'center', gap: 8}}>
      <Button icon={<ArrowLeftOutlined/>} data-testid="native-editor-back"
              onClick={onBack}>返回列表</Button>
      <Space size={6}>
        <span style={{fontWeight: 600}}>{detail.name}</span>
        <Tag>{LEDGER_TYPE_TEXT[detail.ledger_type] || detail.ledger_type}</Tag>
        <Tag color={detail.latest_version_no ? 'blue' : 'default'}>
          {STATUS_TEXT[detail.status] || detail.status}
          {detail.latest_version_no ? ` · v${detail.latest_version_no}` : ''}
        </Tag>
        {store.editorDirty && <Tag color="orange">有未保存修改</Tag>}
      </Space>
      <Space style={{marginLeft: 'auto'}}>
        <Button icon={<SaveOutlined/>} data-testid="native-save-draft"
                loading={store.saving} disabled={store.publishing}
                onClick={onSave}>保存草稿</Button>
        <Button type="primary" icon={<ThunderboltOutlined/>}
                data-testid="native-publish" loading={store.publishing}
                disabled={store.saving} onClick={onPublish}>
          {detail.latest_version_no ? '发布新版本' : '发布版本'}
        </Button>
      </Space>
    </div>
  );
}

function NativeTemplateEditorHost({store, onBack}) {
  const iframeRef = useRef(null);
  const collectingRef = useRef(false);

  const channel = useEditorChannel(iframeRef, {
    onDraftMeta: meta => store.applyEditorMeta(meta),
  });

  // 编辑器就绪（含重试/重挂载后的再次就绪）后注入初始化数据
  useEffect(() => {
    if (!channel.readySeq || !store.detail) return;
    const detail = store.detail;
    channel.sendInit({
      mode: 'template',
      template: {id: detail.id, name: detail.name},
      draft: detail.draft
        ? {
          snapshot: detail.draft.snapshot,
          bindings: detail.draft.bindings || [],
          paper: detail.draft.paper,
        }
        : null,
    });
  }, [channel.readySeq, store.detail && store.detail.id]); // eslint-disable-line react-hooks/exhaustive-deps

  const requireState = async () => {
    if (collectingRef.current) {
      message.warning('正在处理上一个请求，请稍候');
      return null;
    }
    try {
      collectingRef.current = true;
      return await channel.collect();
    } catch (e) {
      message.warning(e.message || '编辑器状态获取失败，请重试');
      return null;
    } finally {
      collectingRef.current = false;
    }
  };

  const _saveCurrentDraft = async state => {
    await store.saveDraft({
      snapshot: state.snapshot,
      bindings: state.bindings,
      paper: state.paper,
    });
    channel.notifySaved();
    store.applyEditorMeta({...(store.editorMeta || {}), dirty: false});
  };

  const handleSave = async () => {
    const state = await requireState();
    if (!state) return;
    try {
      await _saveCurrentDraft(state);
    } catch (e) {
      // 业务错误已由公共拦截器提示
    }
  };

  const handlePublish = async () => {
    const state = await requireState();
    if (!state) return;
    try {
      await _saveCurrentDraft(state);
      await store.publish();
    } catch (e) {
      // 业务错误已由公共拦截器提示
    }
  };

  const handleBack = () => {
    if (store.editorDirty) {
      // 有未保存修改先确认：继续编辑保留内容，确认放弃才返回
      Modal.confirm({
        title: '有未保存的修改',
        content: '返回列表将放弃尚未保存的模板草稿修改，是否继续？',
        okText: '放弃修改并返回',
        cancelText: '继续编辑',
        onOk: () => onBack(),
      });
      return;
    }
    onBack();
  };

  const detail = store.detail;
  if (!detail) return null;
  return (
    <div data-testid="native-template-editor">
      <EditorToolbar detail={detail} store={store}
                     onSave={handleSave} onPublish={handlePublish} onBack={handleBack}/>
      <Alert
        style={{marginBottom: 8}}
        type="info" showIcon
        message="发布版本不可变：台账创建时固定引用当时的版本，之后修改草稿或发布新版本均不影响历史台账。"
      />
      <EditorIframePane
        iframeRef={iframeRef}
        ready={channel.ready}
        loadFailed={channel.loadFailed}
        retry={channel.retry}
        reloadToken={channel.reloadToken}
        testId="native-editor-iframe"
        errorText="原生台账编辑器静态资源未就绪（可能未构建或部署缺失）。请确认 spug_web/public/native-ledger 存在构建产物（npm run build），或联系管理员检查部署。"/>
    </div>
  );
}

export default observer(NativeTemplateEditorHost);

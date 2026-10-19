/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 编辑器 iframe 面板（模板编辑宿主与台账详情宿主共用）。
 *
 * - 未就绪显示加载遮罩；iframe 加载失败（静态包缺失/12 秒未就绪）显示
 *   明确错误与重试入口（retry 触发宿主 reloadToken 递增 → iframe 重挂载）；
 * - key 绑定 reloadToken，宿主 retry 即整体重载编辑器。
 */
import React from 'react';
import {Button, Spin} from 'antd';

export default function EditorIframePane({
  iframeRef,
  ready,
  loadFailed,
  retry,
  reloadToken,
  height = 'calc(100vh - 240px)',
  minHeight = 480,
  testId = 'native-editor-iframe',
  errorText = '编辑器加载失败（静态资源未就绪），请重试或联系管理员检查部署。',
}) {
  if (loadFailed) {
    return (
      <div style={{color: '#f5222d', padding: 24, textAlign: 'center'}}>
        {errorText}
        <div style={{marginTop: 12}}>
          <Button type="primary" data-testid="native-editor-retry"
                  onClick={retry}>重新加载</Button>
        </div>
      </div>
    );
  }
  return (
    <div style={{position: 'relative', height, minHeight}}>
      <iframe
        key={reloadToken}
        ref={iframeRef}
        data-testid={testId}
        title="原生台账编辑器"
        src={editorSrc()}
        style={{display: 'block', width: '100%', height: '100%',
                border: '1px solid #f0f0f0', background: '#fff'}}/>
      {!ready && (
        <div style={{position: 'absolute', inset: 0, display: 'flex',
          alignItems: 'center', justifyContent: 'center',
          background: 'rgba(255,255,255,.7)'}}>
          <Spin tip="正在加载原生台账编辑器…"/>
        </div>
      )}
    </div>
  );
}

function editorSrc() {
  return process.env.REACT_APP_NATIVE_LEDGER_URL
    || `${process.env.PUBLIC_URL || ''}/native-ledger/index.html`;
}

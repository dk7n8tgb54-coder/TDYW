/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * ONLYOFFICE Docs 编辑器承载组件（制度管理草稿工作台）。
 *
 * 实现要点：
 * - DocsAPI.DocEditor 会把占位 div 整个替换为 iframe；React 17 卸载时
 *   若占位节点已被移除会抛 NotFoundError。因此占位 div 用 ref 宿主
 *   命令式创建/清理，不进入 React 的 DOM 管理范围。
 * - api.js 全局只加载一次（script 单例 + ready promise）。
 * - config 由后端 editor-config 端点签发并已含 JWT token；本组件不
 *   修改 config（document.key 与会话绑定，重新取配置会使旧编辑器
 *   实例的回调失效）。
 */
import React from 'react';
import { Alert, Button, Spin } from 'antd';
import { ReloadOutlined } from '@ant-design/icons';

let apiScriptPromise = null;

function loadDocsApi(editorApiUrl) {
  if (window.DocsAPI) return Promise.resolve();
  if (apiScriptPromise) return apiScriptPromise;
  apiScriptPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = editorApiUrl;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      apiScriptPromise = null;
      script.remove();
      reject(new Error('api_script_failed'));
    };
    document.body.appendChild(script);
  });
  return apiScriptPromise;
}

class OnlyOfficeEditor extends React.Component {
  state = {phase: 'loading', error: ''};

  componentDidMount() {
    this.placeholderId = `oo-editor-${this.props.editorConfig.document_key}`;
    this.bootstrap();
  }

  componentWillUnmount() {
    this.destroyEditor();
  }

  bootstrap = () => {
    this.setState({phase: 'loading', error: ''});
    loadDocsApi(this.props.editorConfig.editor_api_url)
      .then(() => this.initEditor())
      .catch(() => this.setState({
        phase: 'error',
        error: '编辑器脚本加载失败（ONLYOFFICE 文档服务不可达），可改用下方本机编辑降级路径',
      }));
  };

  initEditor = () => {
    const host = this.hostRef;
    if (!host || !window.DocsAPI) return;
    this.destroyEditor();
    host.innerHTML = '';
    const placeholder = document.createElement('div');
    placeholder.id = this.placeholderId;
    host.appendChild(placeholder);
    try {
    this.editor = new window.DocsAPI.DocEditor(this.placeholderId, {
      ...this.props.editorConfig.config,
      token: this.props.editorConfig.token,
      events: {
        onDocumentReady: () => this.setState({phase: 'ready'}),
        onError: () => this.setState({
          phase: 'error',
          error: '编辑器加载文档出错，请刷新编辑配置或使用本机编辑降级路径',
        }),
        // 文档修改状态变化：data=true 有未保存修改，false=DS 已保存到
        // 自身缓存。仅把 true 上报（store 侧闩锁，false 不清除）——DS 的
        // "所有更改已保存"不代表制度草稿落盘，不得据此显示业务已保存。
        onDocumentStateChange: event => {
          if (this.props.onDirtyChange) {
            this.props.onDirtyChange(!!(event && event.data));
          }
        },
      },
    });
    } catch (e) {
      this.setState({phase: 'error', error: `编辑器初始化失败：${e}`});
    }
  };

  destroyEditor = () => {
    try {
      if (this.editor && typeof this.editor.destroyEditor === 'function') {
        this.editor.destroyEditor();
      }
    } catch (e) {
      /* 编辑器实例可能已自行销毁 */
    }
    this.editor = null;
    if (this.hostRef) this.hostRef.innerHTML = '';
  };

  handleRetry = () => {
    this.destroyEditor();
    this.bootstrap();
  };

  render() {
    const {phase, error} = this.state;
    return (
      <div>
        {phase === 'loading' && (
          <div style={{padding: 60, textAlign: 'center'}}>
            <Spin tip="正在加载在线编辑器…"/>
          </div>
        )}
        {phase === 'error' && (
          <Alert type="error" showIcon style={{marginBottom: 12}}
            message="在线编辑器不可用"
            description={error}
            action={
              <Button size="small" icon={<ReloadOutlined/>}
                onClick={this.handleRetry}>重试</Button>
            }/>
        )}
        <div ref={el => { this.hostRef = el; }}
          style={{height: '72vh', border: '1px solid #f0f0f0'}}/>
      </div>
    );
  }
}

export default OnlyOfficeEditor;

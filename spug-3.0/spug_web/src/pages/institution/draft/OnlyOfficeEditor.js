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
 * - height prop（2026-10-30）：宿主容器高度由工作台按放大状态下发
 *   （常规 72vh / 放大 100%）。height 仅参与 render 的容器样式，不在
 *   生命周期中触发 initEditor——放大/还原切换只改变容器尺寸，DS 的
 *   iframe（100%×100%）随宿主自动重排，编辑器实例不销毁重建。
 * - 加载失败上报（2026-10-31）：api.js 加载失败、编辑器初始化异常与
 *   文档加载 onError 经 onUnavailable 上报工作台（store.editorLoadFailed），
 *   工作台据此提供显式「切换到本机编辑」入口；onDocumentReady 经 onReady
 *   上报以清除失败标记（重试成功后回到常规在线分支）。
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
      .catch(() => {
        this._reportUnavailable();
        this.setState({
          phase: 'error',
          error: '编辑器脚本加载失败（ONLYOFFICE 文档服务不可达），'
            + '可切换为本机编辑（下载草稿 → 本机 Word/WPS 编辑 → 上传保存）',
        });
      });
  };

  /** 加载失败上报工作台（本机编辑入口的依据之一，幂等） */
  _reportUnavailable = () => {
    if (this.props.onUnavailable) this.props.onUnavailable();
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
        onDocumentReady: () => {
          if (this.props.onReady) this.props.onReady();
          this.setState({phase: 'ready'});
        },
        onError: () => {
          this._reportUnavailable();
          this.setState({
            phase: 'error',
            error: '编辑器加载文档出错，可重试加载或切换为本机编辑'
              + '（下载草稿 → 本机 Word/WPS 编辑 → 上传保存）',
          });
        },
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
      this._reportUnavailable();
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
    // 高度仅在 render 生效（不触发 initEditor）；flex column + flex:1
    // 让 loading/error 提示与编辑器宿主共享同一容器，不产生额外溢出
    const height = this.props.height || '72vh';
    return (
      <div style={{height, display: 'flex', flexDirection: 'column'}}>
        {phase === 'loading' && (
          <div style={{padding: 60, textAlign: 'center', flexShrink: 0}}>
            <Spin tip="正在加载在线编辑器…"/>
          </div>
        )}
        {phase === 'error' && (
          <Alert type="error" showIcon style={{marginBottom: 12, flexShrink: 0}}
            message="在线编辑器不可用"
            description={error}
            action={
              <Button size="small" icon={<ReloadOutlined/>}
                onClick={this.handleRetry}>重试</Button>
            }/>
        )}
        <div ref={el => { this.hostRef = el; }}
          style={{flex: 1, minHeight: 0, border: '1px solid #f0f0f0'}}/>
      </div>
    );
  }
}

export default OnlyOfficeEditor;

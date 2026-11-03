/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 草稿工作台编辑区（2026-10-30 自 index.js 抽出，并加入放大/还原入口；
 * 2026-10-31 加入编辑方式切换与本机编辑面板）。
 *
 * 分支：无会话提示 / 编辑配置加载中 / 在线编辑器 / 本机编辑面板。
 * - 编辑方式切换（Segmented「在线编辑 | 本机编辑」）只在在线编辑配置
 *   可用时渲染（onlineAvailable；切换链路在 store.switchEditMode：确认
 *   落盘 → 轮换 document key → 清配置缓存，会话保留）。服务未配置或
 *   配置加载失败的文件不渲染切换控件、直接呈现本机面板——本机入口
 *   不依赖任何失败上报的可靠性。
 * - 编辑器脚本/文档加载失败（OnlyOfficeEditor 上报 store.editorLoadFailed）
 *   时在编辑器上方呈现显式「切换到本机编辑」入口；即使上报不可靠，
 *   顶部 Segmented 也始终可用。
 * - 本机面板：步骤说明 + 基线修订号状态 + 下载草稿入口 + 两个本机上传
 *   入口。日常「上传保存（需先下载草稿）」必须携带下载草稿时记录的基线
 *   修订号（store.localBaselines），并在文案中明确告知系统不校验所选文件
 *   是否基于已下载的草稿修改；次级危险操作「用本机文件替换当前草稿」不
 *   要求先下载，点击先由工作台弹确认（目标制度文件名/当前草稿修订号 rN/
 *   整份替换影响），确认后才打开文件选择，取消不上传。
 * - 放大/还原按钮带图标与 Tooltip，位于编辑器正上方；切换放大只改容器
 *   样式与 OnlyOfficeEditor 的 height prop（72vh ↔ 100%），不改 key、
 *   不重新拉编辑配置——编辑器实例不销毁重建。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Alert, Button, Segmented, Spin, Tooltip } from 'antd';
import { ZoomInOutlined, ZoomOutOutlined } from '@ant-design/icons';
import ManualAuthButton from '../ManualAuthButton';
import OnlyOfficeEditor from './OnlyOfficeEditor';
import store from './store';

const MODE_OPTIONS = [
  {label: '在线编辑', value: 'online'},
  {label: '本机编辑', value: 'local'},
];

const EditorArea = observer(({file, hasSession, expanded, onToggleExpanded,
  onSwitchMode, onDownloadDraft, onPickUploadFile, onPickReplaceFile}) => {
  const fileId = file.id;
  if (!hasSession) {
    return (
      <Alert type="warning" showIcon style={{marginBottom: 12}}
        message="该文件尚未开启编辑会话，开启后才能在线编辑或上传保存。"/>
    );
  }
  if (store.editorLoadingId === fileId) {
    return <div style={{padding: 40, textAlign: 'center'}}><Spin tip="正在获取编辑配置…"/></div>;
  }
  const config = store.editorConfigs[fileId];
  const onlineUsable = !!(config && config.editor_available);
  const mode = store.effectiveEditMode(fileId);
  // 方式切换控件：仅在线编辑真实可用时提供（配置缓存清除后的本机面板
  // 以 onlineAvailable 能力标记为准，切回入口不消失）
  const modeSwitch = (onlineUsable || store.onlineAvailable[fileId]) && (
    <Segmented value={mode} options={MODE_OPTIONS}
      onChange={v => onSwitchMode && onSwitchMode(v)}/>
  );
  if (mode === 'online' && onlineUsable) {
    return (
      <div style={expanded ? {height: '100%', display: 'flex',
        flexDirection: 'column', minHeight: 0} : undefined}>
        <div style={{display: 'flex', justifyContent: 'space-between',
          alignItems: 'center', marginBottom: 4, flexShrink: 0}}>
          {modeSwitch}
          <Tooltip title={expanded
            ? '还原编辑区（按 Esc 也可还原）'
            : '放大编辑区：编辑器占满当前视口，文件清单与元数据自动收起'}>
            <Button size="small"
              icon={expanded ? <ZoomOutOutlined/> : <ZoomInOutlined/>}
              onClick={onToggleExpanded}>
              {expanded ? '还原' : '放大'}
            </Button>
          </Tooltip>
        </div>
        {store.editorLoadFailed[fileId] && (
          <Alert type="warning" showIcon style={{marginBottom: 8, flexShrink: 0}}
            message="在线编辑器加载失败"
            description="可切换为本机编辑：下载草稿 → 本机 Word/WPS 编辑 → 上传保存；也可在编辑器内重试加载。"
            action={<Button size="small"
              onClick={() => onSwitchMode && onSwitchMode('local')}>
              切换到本机编辑
            </Button>}/>
        )}
        <div style={expanded ? {flex: 1, minHeight: 0} : undefined}>
          {/* key 含 document_key：切换文件或重开会话（配置轮换）时
              强制销毁重建编辑器实例 */}
          <OnlyOfficeEditor key={`${fileId}:${config.document_key || fileId}`}
            editorConfig={config}
            height={expanded ? '100%' : '72vh'}
            onDirtyChange={dirty => store.setEditorDirty(fileId, dirty)}
            onUnavailable={() => store.markEditorLoadFailed(fileId)}
            onReady={() => {
              store.clearEditorLoadFailed(fileId);
              // 新编辑器实例尚无未保存修改：实时脏态复位，避免上一实例
              // 残留的脏态让确认链沉降复核误判在途
              store.markEditorReady(fileId);
            }}/>
        </div>
        <div style={expanded ? {display: 'none'}
          : {marginTop: 8, color: '#999', fontSize: 12}}>
          在编辑器内保存（Ctrl+S / 自动保存）经文档服务回调落盘；
          「保存并结束编辑」与切换文件/返回详情都会请求文档服务立即保存，
          并在服务端确认落盘后才继续。编辑器的"所有更改已保存"不代表已写入制度草稿，
          以上方保存状态为准。也可随时切换为「本机编辑」（下载草稿 → 本机
          Word/WPS 编辑 → 上传保存）。
        </div>
      </div>
    );
  }
  // 本机编辑面板：用户主动切换或服务未配置/配置加载失败时的编辑方式。
  // 两个上传入口语义严格区分（2026-10-31 二轮拆分）：
  // 1) 日常「上传保存（需先下载草稿）」：必须携带下载草稿时记录的基线
  //    修订号（服务端草稿已推进时后端拒绝覆盖并要求重新下载）；系统只
  //    校验服务端修订号未被推进，不校验所选文件内容是否基于下载草稿。
  // 2) 次级危险操作「用本机文件替换当前草稿」：不要求先下载，点击先由
  //    工作台弹确认（目标文件名/当前草稿修订号/整份替换影响），确认后
  //    才打开文件选择，取消不上传。
  const baseline = store.localBaselines[fileId];
  const lead = onlineUsable ? '' : (
    store.editorErrors[fileId] ||
    (store.onlineAvailable[fileId] ? '已切换为本机编辑。' : '在线编辑服务未配置。'));
  return (
    <Alert type="info" showIcon style={{marginBottom: 12}} message={
      <div>
        {lead && <div>{lead}</div>}
        <div>
          当前工作方式：<b>下载草稿</b> → 本机 Word/WPS 编辑 → <b>上传保存</b>，
          全程受编辑会话与修订序号保护；同一时间每个文件仅一个可写会话。
        </div>
        <div style={{marginTop: 4, color: '#666'}}>
          {baseline != null
            ? `本机编辑基线：r${baseline}（上传保存以此校验服务端草稿未被推进；`
              + '若已被推进将拒绝覆盖，需重新下载最新草稿）。'
            : '尚未下载草稿：请先下载草稿（记录基线修订号），本机编辑后上传保存。'}
        </div>
        <div style={{marginTop: 4, color: '#666'}}>
          系统不会校验所选文件是否基于已下载的草稿修改，请只在同一份草稿的本机修改后上传。
        </div>
        <div style={{marginTop: 4, color: '#999'}}>
          次级危险操作「用本机文件替换当前草稿」不要求先下载：会整份替换该文件当前草稿（不是增量修改），上传成功只更新草稿、不发布，历史发布版本不受影响；请确认所选本机文件就是该草稿的最新版本。
        </div>
      </div>
    } action={
      <div style={{marginTop: 8, display: 'flex', gap: 8, flexWrap: 'wrap',
        alignItems: 'center'}}>
        {modeSwitch}
        <ManualAuthButton manual={store.manual} auth="institution.manual.download"
          size="small"
          disabled={!file.draft} onClick={onDownloadDraft}>
          下载草稿
        </ManualAuthButton>
        <Tooltip title="日常本机编辑后的保存入口：需先下载草稿记录基线修订号">
          <span style={{display: 'inline-block'}}>
            <ManualAuthButton manual={store.manual} auth="institution.manual.draft_edit"
              type="primary"
              size="small" loading={store.saving} disabled={!file.draft}
              onClick={onPickUploadFile}>
              上传保存（需先下载草稿）
            </ManualAuthButton>
          </span>
        </Tooltip>
        <Tooltip title="次级危险操作：会整份替换当前草稿（非增量修改），只更新草稿、不发布，历史发布版本不受影响">
          <span style={{display: 'inline-block'}}>
            <ManualAuthButton manual={store.manual} auth="institution.manual.draft_edit"
              danger
              size="small" loading={store.saving} disabled={!file.draft}
              onClick={onPickReplaceFile}>
              用本机文件替换当前草稿
            </ManualAuthButton>
          </span>
        </Tooltip>
      </div>
    }/>
  );
});

export default EditorArea;

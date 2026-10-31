/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 独立的"制度草稿保存状态"展示（2026-10-30 自工作台 index.js 抽出，
 * 状态条与放大态精简顶栏共用，语义与文案不变）：
 * 只有服务端确认回调落盘后才显示"已保存到制度草稿：rN、时间"。
 * ONLYOFFICE 编辑器自身的"所有更改已保存"只代表文档服务缓存，绝不据此
 * 显示业务已保存：
 * - 确认进行中 → 正在请求服务端保存；
 * - 在线编辑 + 有未确认修改（editorDirty 闩锁）→ 明确警示；
 * - 在线编辑 + 确认成功（saveConfirmed）→ 已保存到制度草稿：rN、时间；
 * - 在线编辑无确认记录 → 编辑中，内容尚未经服务端确认落盘；
 * - 非在线编辑（无会话/降级路径）→ 服务端草稿数据本身就是落盘结果。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Tag, Tooltip } from 'antd';
import { formatDateTime } from '../utils';
import store from './store';

const SaveStatusTag = observer(({file, hasSession}) => {
  const draft = file.draft || {};
  const config = store.editorConfigs[file.id];
  const onlineEditing = hasSession && !!(config && config.editor_available);
  if (store.finishingFileId === file.id) {
    return (
      <span style={{fontSize: 12, color: '#1890ff'}}>
        正在请求服务端保存当前文件…
      </span>
    );
  }
  if (onlineEditing) {
    if (store.editorDirty[file.id]) {
      return (
        <Tooltip title="ONLYOFFICE 的「所有更改已保存」仅代表文档服务缓存，不代表已写入制度草稿；「保存并结束编辑」或切换文件/返回详情时会请求服务端保存并确认落盘。">
          <Tag color="orange" style={{marginRight: 0}}>
            有未确认落盘的修改
          </Tag>
        </Tooltip>
      );
    }
    if (store.saveConfirmed[file.id]) {
      const confirmed = store.saveConfirmed[file.id];
      const revision = confirmed.revision != null
        ? confirmed.revision : draft.revision;
      return (
        <span style={{fontSize: 12, color: '#389e0d'}}>
          已保存到制度草稿：r{revision}
          {confirmed.at ? ` · ${formatDateTime(confirmed.at)}` : ''}
        </span>
      );
    }
    return (
      <span style={{fontSize: 12, color: '#d48806'}}>
        编辑中：内容尚未经服务端确认落盘
      </span>
    );
  }
  if (file.draft) {
    return (
      <span style={{fontSize: 12, color: '#389e0d'}}>
        已保存到制度草稿：r{draft.revision} · {formatDateTime(draft.last_saved_at)}
        {draft.last_saved_by_name ? `（${draft.last_saved_by_name}）` : ''}
      </span>
    );
  }
  return null;
});

export default SaveStatusTag;

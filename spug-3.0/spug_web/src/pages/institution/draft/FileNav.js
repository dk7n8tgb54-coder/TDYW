/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 草稿工作台左侧文件导航（多文件制度，2026-10-30 交互改造）。
 * - 每行展示：序号+名称（超长省略，title 全名）、负责人/未分配、
 *   修订号/无草稿、编辑占用（我的会话/他人会话中/空闲）、提交编制状态
 *   （未提交/已提交/提交已失效，服务端 submission.state 只映射不推断）。
 * - 点击整行切换选中文件（切换保护由工作台 onSelect 处理）。
 * - 行内 flexWrap + 名称 ellipsis：窄屏折叠为整行时文字与 Tag 不重叠。
 * - 「新增文件」入口在导航底部；隐藏 file input 由工作台持有（input
 *   不得嵌套在 Button/label 内，统一 ref 程序触发）。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Card, Tag, Tooltip } from 'antd';
import ManualAuthButton from '../ManualAuthButton';
import store from './store';

// 提交编制状态文案（与详情页文件清单页签同一口径）
export const SUBMISSION_META = {
  none: {label: '未提交', color: 'default'},
  submitted: {label: '已提交', color: 'green'},
  stale: {label: '提交已失效', color: 'orange'},
};

/** 提交编制状态 Tag（导航与右侧状态条共用；submission 缺失时返回 null） */
export function submissionTagFor(submission) {
  if (!submission) return null;
  const meta = SUBMISSION_META[submission.state] || SUBMISSION_META.none;
  return <Tag color={meta.color} style={{marginRight: 0}}>{meta.label}</Tag>;
}

/** 文件行内的编辑占用 Tag：我的会话 / 他人会话中 / 空闲 */
export function sessionTagFor(file) {
  if (store.sessionKeyOf(file.id)) {
    return <Tag color="green" style={{marginRight: 0}}>我的会话</Tag>;
  }
  const active = file.active_session;
  if (!active) return <Tag style={{marginRight: 0}}>空闲</Tag>;
  return active.is_mine
    ? <Tooltip title="会话由本账号其他页签持有，可在本页重新开启后编辑">
        <Tag color="orange" style={{marginRight: 0}}>我的会话</Tag>
      </Tooltip>
    : <Tooltip title={`${active.user_name} 正在编辑该文件`}>
        <Tag color="orange" style={{marginRight: 0}}>他人会话中</Tag>
      </Tooltip>;
}

@observer
class FileNav extends React.Component {
  renderItem(file, index) {
    const selected = file.id === store.selectedFileId;
    const assignment = file.assignment || {};
    return (
      <div key={file.id} onClick={() => this.props.onSelect(file.id)}
        style={{
          padding: '8px 10px', marginBottom: 6, borderRadius: 4,
          border: selected ? '1px solid #1890ff' : '1px solid #f0f0f0',
          background: selected ? '#e6f7ff' : undefined, cursor: 'pointer',
        }}>
        <div style={{display: 'flex', alignItems: 'center', gap: 6, minWidth: 0}}>
          <span style={{color: '#999', flexShrink: 0}}>{index + 1}.</span>
          <span title={file.name} style={{
            flex: 1, minWidth: 0, overflow: 'hidden',
            textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            fontWeight: selected ? 600 : 400}}>
            {file.name}
          </span>
        </div>
        <div style={{display: 'flex', flexWrap: 'wrap', gap: 4,
          rowGap: 2, marginTop: 4, alignItems: 'center'}}>
          {assignment.owner_id
            ? <Tag color="purple" style={{marginRight: 0}}>
                {assignment.owner_name || '负责人'}
              </Tag>
            : <Tag style={{marginRight: 0}}>未分配</Tag>}
          {file.draft
            ? <Tag color="blue" style={{marginRight: 0}}>r{file.draft.revision}</Tag>
            : <Tag style={{marginRight: 0}}>无草稿</Tag>}
          {sessionTagFor(file)}
          {submissionTagFor(file.submission)}
        </div>
      </div>
    );
  }

  render() {
    // 新增制度文件业务门=手册所有者或制度管理员（2026-10-31 授权模型；
    // 页面权限码 upload 原样，后端独立校验）
    const manual = store.manual || {};
    const canAddFile = !!manual.is_owner || !!manual.is_admin;
    return (
      <Card size="small" title={`待发布文件（共 ${store.files.length} 份）`}
        bodyStyle={{padding: '8px'}}>
        {store.files.map((file, index) => this.renderItem(file, index))}
        {canAddFile && (
          <div style={{padding: '8px 4px 0'}}>
            <ManualAuthButton manual={manual} auth="institution.manual.upload"
              size="small" block
              loading={this.props.adding} onClick={this.props.onPickAddFile}>
              新增文件（.doc/.docx）
            </ManualAuthButton>
          </div>
        )}
      </Card>
    );
  }
}

export default FileNav;

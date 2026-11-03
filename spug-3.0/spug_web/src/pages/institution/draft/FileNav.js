/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 草稿工作台左侧文件导航（多文件制度，2026-10-30 交互改造；
 * 2026-11-03 固定快照交接口径统一）。
 * - 每行展示：序号+名称（超长省略，title 全名）、有效负责人/未分配
 *   （owner_assigned=false 时后缀「（默认）」表示回退手册所有者）、
 *   修订号（内部修订序号，次要灰字，不再用醒目蓝色 Tag）、编辑占用
 *   （我的会话/他人会话中/空闲）、编制状态 Tag（与详情页文件清单
 *   「编制状态」同一口径，共用 pages/institution/compilationStatusShared
 *   的 buildCompilationState，只映射服务端数据不推断）、冻结 Tag
 *   （已提交待发布核对：内容冻结、不能编辑/改结构/重复提交）。
 * - 点击整行切换选中文件（切换保护由工作台 onSelect 处理）。
 * - 行内 flexWrap + 名称 ellipsis：窄屏折叠为整行时文字与 Tag 不重叠。
 * - 「新增文件」入口在导航底部；隐藏 file input 由工作台持有（input
 *   不得嵌套在 Button/label 内，统一 ref 程序触发）。
 */

/** 编制状态元数据（2026-11-03 固定快照交接新文案；优先使用
 *  compilationTagFor，整行文件对象才能推导冻结/编辑中/无需提交）。 */
export const SUBMISSION_META = {
  none: {label: '无需提交', color: 'default'},
  pending: {label: '待发布人核对', color: 'green'},
  withdrawn: {label: '已撤回（可重新提交）', color: 'orange'},
  returned: {label: '已退回', color: 'red'},
  published: {label: '已随发布处理', color: 'default'},
  submitted: {label: '待发布人核对', color: 'green'},
  stale: {label: '提交已失效（需重新提交）', color: 'orange'},
};
import React from 'react';
import { observer } from 'mobx-react';
import { Card, Tag, Tooltip } from 'antd';
import ManualAuthButton from '../ManualAuthButton';
import { buildCompilationState } from '../compilationStatusShared';
import {
  effectiveOwnerIdOf, effectiveOwnerNameOf, isFrozenSubmission,
  ownerIsDefaultAssignment,
} from '../submissionShared';
import store from './store';

/**
 * 编制状态元数据（编制中/待提交/已提交/需重新提交/本人发布无需提交/
 * 无需提交）：整行文件对象 + relation=null（草稿工作台没有 draft-status）
 * 交给共享 helper 推导；本页已持有的本地会话补进 active_session，避免
 * "刚开启会话但清单未刷新"时仍显示待提交。
 */
export function compilationMetaFor(file, options) {
  if (!file) return null;
  const opts = options || {};
  const active = file.active_session || (store.sessionKeyOf(file.id)
    ? {is_mine: true, user_name: '你（本账号）'} : null);
  return buildCompilationState(Object.assign({}, file, {active_session: active}),
    null, {canPublish: !!opts.canPublish});
}

/** 编制状态 Tag（导航行 / 右侧状态条 / 放大态顶栏共用）。
 *  无草稿文件由调用方单独渲染「无草稿」Tag，这里跳过 helper 的「—」占位
 *  避免同一行出现两个空态标签；其余情况永不为 null。 */
export function compilationTagFor(file, options) {
  if (!file || !file.draft) return null;
  const meta = compilationMetaFor(file, options);
  if (!meta) return null;
  const tag = <Tag color={meta.color} style={{marginRight: 0}}>{meta.label}</Tag>;
  return meta.tip ? <Tooltip title={meta.tip}>{tag}</Tooltip> : tag;
}

// 兼容导出（仅少数拿不到整行 file 的场景）：提交记录状态退化映射，
// 不得据此判断「待提交/编制中/冻结」（那需要 revision_open/会话/关系数据）。
/** 提交记录状态 Tag（退化映射；优先使用 compilationTagFor） */
export function submissionTagFor(submission) {
  const status = submission && (submission.legacy_submitted ? 'legacy'
    : (submission.status || submission.state));
  const meta = SUBMISSION_META[status] || SUBMISSION_META.none;
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
  renderItem(file, index, canPublish) {
    const selected = file.id === store.selectedFileId;
    const ownerId = effectiveOwnerIdOf(file);
    const ownerName = effectiveOwnerNameOf(file);
    const ownerDefault = ownerIsDefaultAssignment(file);
    const frozen = isFrozenSubmission(file);
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
          {frozen && (
            <Tooltip title="已提交待发布核对：内容已冻结，不能编辑/改结构/重复提交">
              <Tag color="blue" style={{marginRight: 0}}>已冻结</Tag>
            </Tooltip>
          )}
        </div>
        <div style={{display: 'flex', flexWrap: 'wrap', gap: 4,
          rowGap: 2, marginTop: 4, alignItems: 'center'}}>
          {ownerId != null && ownerId !== ''
            ? <Tooltip title={ownerDefault
              ? '该文件未单独指派负责人，有效负责人默认为手册所有者'
              : '该文件的有效负责人（负责人独占编辑）'}>
                <Tag color="purple" style={{marginRight: 0}}>
                  {ownerName || '负责人'}{ownerDefault ? '（默认）' : ''}
                </Tag>
              </Tooltip>
            : <Tag style={{marginRight: 0}}>未分配</Tag>}
          {file.draft
            ? <span title={`草稿内部修订号 r${file.draft.revision}（每次保存/重建 +1）`}
                style={{marginRight: 0, color: '#999', fontSize: 12}}>
                r{file.draft.revision}
              </span>
            : <Tag style={{marginRight: 0}}>无草稿</Tag>}
          {sessionTagFor(file)}
          {compilationTagFor(file, {canPublish})}
        </div>
      </div>
    );
  }

  render() {
    // 新增制度文件业务门=手册所有者或制度管理员（2026-10-31 授权模型；
    // 页面权限码 upload 原样，后端独立校验）
    const manual = store.manual || {};
    const canAddFile = !!manual.is_owner || !!manual.is_admin;
    // 编制状态里的"本人发布无需提交"需要发布权口径（与详情页同一算法）
    const canPublish = !!manual.is_owner || (manual.my_roles || []).includes('publish');
    return (
      <Card size="small" title={`待发布文件（共 ${store.files.length} 份）`}
        bodyStyle={{padding: '8px'}}>
        {store.files.map((file, index) => this.renderItem(file, index, canPublish))}
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

/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 整套草稿状态摘要（详情页头部，工作区可见者专属）：
 * 以服务端 draft-status 计算结果展示制度当前状态——
 * - 已生效，无未发布修改（发布成功、修订轮已结束、无结构变化）；
 * - 修订进行中（revision_open 显式状态；暂无待发布变化也如实呈现）；
 * - 存在待发布变化（修改/新增/移除/改名/排序）；
 * - 缺草稿 / 无生效版本等待首次发布 / 暂不能确认（编辑中、文件缺失）。
 * 修订进行中与待发布变化分开表达："工作副本仍存在"绝不写成"有未发布
 * 草稿"。加载失败显式报错可重试，绝不以"无变化"或"可发布"冒充；
 * 仅查看权限的账号不渲染也不请求（后端仍独立校验）。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Alert, Button, Spin, Tag, Tooltip } from 'antd';
import { canViewWorkspace } from '../utils';
import {
  buildDraftChangeSummaryText, DRAFT_RELATION_COLORS, DRAFT_RELATION_LABELS,
} from './draftStatusShared';
import store from './store';

@observer
class DraftStatusSummary extends React.Component {
  render() {
    const manual = store.manual || {};
    if (!canViewWorkspace(manual)) return null;
    if (store.draftStatusError) {
      return (
        <Alert type="error" showIcon style={{marginTop: 8}}
          message={store.draftStatusError}
          description="无法确认草稿与生效版本的关系；在重新加载成功前，请勿据此判断是否存在待发布变化。"
          action={<Button size="small" type="primary"
            onClick={() => store.fetchDraftStatus(store.id)}>重试</Button>}/>
      );
    }
    if (!store.draftStatus) {
      return store.isFetchingDraftStatus ? (
        <div style={{marginTop: 8}}>
          <Spin size="small"/>
          <span style={{marginLeft: 8, color: '#999'}}>正在加载草稿状态…</span>
        </div>
      ) : null;
    }
    const s = store.draftStatus.summary || {};
    const refresh = (
      <Button size="small" style={{marginLeft: 8}}
        onClick={() => store.fetchDraftStatus(store.id)}>刷新</Button>
    );
    // 无待发布文件：只提示入口，不谈一致/变化
    if (!s.total_files) {
      return (
        <Alert type="info" showIcon style={{marginTop: 8}} message={
          <span>
            该制度还没有待发布文件。请在文件清单页签使用「新增待发布文件」
            上传，上传文件作为待发布文件的当前草稿。{refresh}
          </span>}/>
      );
    }
    // 编辑占用（含未完成同步/保存回调）或草稿文件缺失等无法确认的份数
    const unconfirmedText = s.unconfirmed
      ? `${s.unconfirmed} 份暂不能确认（编辑中或草稿文件缺失）` : '';
    // 修订进行中（显式状态，与内容变化分开表达）
    const revisingText = s.revising
      ? `${s.revising} 份文件修订进行中` : '';
    if (!s.has_current_version) {
      return (
        <Alert type="warning" showIcon style={{marginTop: 8}} message={
          <span>
            尚无生效版本，等待首次发布：当前待发布 {s.total_files} 份文件。
            {revisingText && ` ${revisingText}；`}
            {unconfirmedText && ` ${unconfirmedText}；`}
            完成编辑后请在「版本与发布」填写变更说明并发布。{refresh}
          </span>}/>
      );
    }
    const changeText = buildDraftChangeSummaryText(s);
    if (changeText || revisingText) {
      const parts = [changeText, revisingText, unconfirmedText]
        .filter(Boolean).join('；');
      return (
        <Alert type="warning" showIcon style={{marginTop: 8}} message={
          <span>
            {changeText
              ? `当前草稿与生效版本（v${s.current_version_no}）存在待发布变化：${parts}。`
              : `${parts}（暂无待发布变化）。`}
            变化状态由服务端按快照哈希与清单比对计算。{refresh}
          </span>}/>
      );
    }
    if (!s.determinable) {
      return (
        <Alert type="warning" showIcon style={{marginTop: 8}} message={
          <span>
            {unconfirmedText}，无法确认是否存在待发布变化，
            请稍后刷新或退出编辑后再查看。{refresh}
          </span>}/>
      );
    }
    return (
      <Alert type="success" showIcon style={{marginTop: 8}} message={
        <span>
          已生效（v{s.current_version_no}，共 {s.total_files} 份文件），
          无未发布修改。{refresh}
        </span>}/>
    );
  }
}

/**
 * 逐份文件"草稿 vs 生效版本"关系标签（保留给需要原文关系语义的场景）。
 * item 为 null（状态未加载/加载失败）时显示占位破折号，
 * 绝不显示"一致/无变化"语义。
 */
export function DraftRelationTag({item}) {
  if (!item) return <span style={{color: '#999'}}>—</span>;
  const label = DRAFT_RELATION_LABELS[item.status] || item.status;
  const color = DRAFT_RELATION_COLORS[item.status] || 'default';
  if (item.status === 'unconfirmed') {
    const session = item.session || {};
    const who = session.user_name && !session.is_mine
      ? `${session.user_name} 正在编辑` : '';
    const tip = [item.unconfirmed_message, who].filter(Boolean).join('；');
    return (
      <Tooltip title={tip || '该文件状态暂不能确认'}>
        <Tag color={color}>{label}</Tag>
      </Tooltip>
    );
  }
  return <Tag color={color}>{label}</Tag>;
}

export default DraftStatusSummary;

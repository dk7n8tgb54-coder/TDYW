/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 发布新版本入口（详情页头部整套待发布状态旁）。发布角色与编制角色
 * 可以分离——发布者无需进入草稿工作台或开启编辑会话，从详情待发布
 * 状态与核对入口即可发布：
 * - 点击先请求 publish-preview 分组预检（服务端按草稿哈希与生效版快照
 *   比对：变化/未修改/新增/移除/受阻），预检失败不开确认窗、不产生
 *   成功语义；
 * - 确认窗口重点展示实际变化文件（新增/修改/移除/受阻），未修改文件
 *   以数量汇总、可展开核对完整清单；逐行展示 文件负责人 与 提交编制
 *   状态（交接核对信息，不改变发布校验）；
 * - 受阻文件提供可执行处理入口（我的编辑会话→草稿工作台结束会话；
 *   缺草稿/草稿缺失→编制角色进工作台恢复），存在受阻文件时禁用确认
 *   按钮——不让用户点击一个必然失败的确认；
 * - 无内容/结构变化时（首发除外）服务端拒绝重复发布：预检 has_changes
 *   为假时同样禁用确认并说明；发布入口按整套状态弱化（非主按钮）。
 * - 预检不是放行凭证：发布权威校验仍在后端 publish_whole_set 行锁内
 *   重新全量复核，前端禁用只是交互引导。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Modal, message, Alert, Tag, Tooltip } from 'antd';
import { AuthButton } from 'components';
import { history } from 'libs';
import { http } from 'libs';
import { formatSize } from '../utils';
import store from './store';

// 发布确认窗口的分组（与后端 publish-preview 分组一一对应）
const PLAN_GROUPS = [
  {key: 'added', title: '新增文件', color: 'blue'},
  {key: 'changed', title: '本次内容变化', color: 'orange'},
  {key: 'removed', title: '被移除（不再进入新版本）', color: 'red'},
  {key: 'blocked', title: '受阻文件（处理后方可发布）', color: 'red'},
];

/**
 * 未修改文件：数量汇总 + 可展开核对完整清单。
 * 必须是自包含组件——Modal.confirm 的 content 是打开时的快照，外层
 * 组件的 setState 不会重渲染确认窗内容；展开/收起状态由本组件自持。
 */
class UnchangedGroup extends React.Component {
  state = {expanded: false};

  render() {
    const rows = this.props.rows || [];
    if (!rows.length) return null;
    return (
      <div style={{marginBottom: 8}}>
        <Tag color="green">未修改（将继续纳入新版本）（{rows.length}）</Tag>
        <a style={{marginLeft: 8}} onClick={() => this.setState(
          s => ({expanded: !s.expanded}))}>
          {this.state.expanded ? '收起' : `展开核对完整清单（${rows.length}）`}
        </a>
        {this.state.expanded && rows.map(row => (
          <div key={row.file_id}
            style={{display: 'flex', alignItems: 'center', padding: '1px 0 1px 8px'}}>
            <span title={row.name}
              style={{flex: 1, minWidth: 0, overflow: 'hidden',
                textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginRight: 12}}>
              {row.name}
            </span>
            <span style={{flexShrink: 0, color: '#888', marginRight: 8}}>
              {this.props.renderDetail(row)}
            </span>
          </div>
        ))}
      </div>
    );
  }
}

@observer
class PublishButton extends React.Component {
  handlePublish = () => {
    // 发布前实际请求最新分组预检；预检失败拦截器已提示，不打开确认窗
    store.fetchPublishPreview(store.id).then(() => this.showPublishConfirm())
      .catch(() => {});
  };

  planRowDetail = (row) => {
    // 交接信息：负责人与提交编制状态（removed 分组由生效快照行构造，
    // 无文件条目，不带这两个字段）；提交状态只作核对展示，不影响发布
    const parts = [];
    if (row.reason) {
      const session = row.session;
      const sessionText = session
        ? `（${session.is_mine ? '我的编辑会话进行中' : `${session.user_name} 编辑中`}）`
        : '';
      parts.push(`${row.message}${sessionText}`);
    } else {
      parts.push(`草稿 r${row.draft_revision} · ${formatSize(row.draft_size)}`);
    }
    if (row.owner_name !== undefined) {
      parts.push(row.owner_name ? `负责人 ${row.owner_name}` : '负责人 未分配');
    }
    if (row.submission) {
      if (row.submission.state === 'submitted') parts.push('已提交');
      else if (row.submission.state === 'stale') parts.push('提交已失效');
      else parts.push('未提交');
    }
    return parts.join(' · ');
  };

  /** 受阻文件的可执行处理入口：无权限/他人会话给出明确说明 */
  renderBlockedAction = (row) => {
    const manual = store.manual || {};
    const canEdit = (manual.my_roles || []).includes('edit');
    const deepLink = `/institution/manuals/${store.id}/draft?file=${row.file_id}`;
    if (row.reason === 'session_busy') {
      if (row.session && row.session.is_mine) {
        return (
          <a onClick={() => history.push(deepLink)}>去结束我的编辑会话</a>
        );
      }
      return <span style={{color: '#999'}}>需该账号保存并退出会话</span>;
    }
    if (row.reason === 'no_draft') {
      return canEdit
        ? <a onClick={() => history.push(deepLink)}>去恢复草稿</a>
        : <span style={{color: '#999'}}>需持有编制角色的账号建立草稿</span>;
    }
    if (row.reason === 'draft_missing') {
      return canEdit
        ? <a onClick={() => history.push(deepLink)}>去重新编辑该文件</a>
        : <span style={{color: '#999'}}>需持有编制角色的账号处理</span>;
    }
    return null;
  };

  renderPlanGroup = (rows, group) => {
    if (!rows || !rows.length) return null;
    return (
      <div key={group.key} style={{marginBottom: 8}}>
        <Tag color={group.color}>{group.title}（{rows.length}）</Tag>
        {rows.map(row => (
          <div key={row.file_id}
            style={{display: 'flex', alignItems: 'center', padding: '1px 0 1px 8px'}}>
            <span title={row.name}
              style={{flex: 1, minWidth: 0, overflow: 'hidden',
                textOverflow: 'ellipsis', whiteSpace: 'nowrap', marginRight: 12}}>
              {row.name}
            </span>
            <span style={{flexShrink: 0, color: '#888', marginRight: 8}}>
              {this.planRowDetail(row)}
            </span>
            {group.key === 'blocked' && (
              <span style={{flexShrink: 0}}>{this.renderBlockedAction(row)}</span>
            )}
          </div>
        ))}
      </div>
    );
  };

  /** 未修改文件：数量汇总 + 可展开核对完整清单（自包含组件，见上） */
  renderUnchangedGroup(rows) {
    return <UnchangedGroup rows={rows} renderDetail={row => this.planRowDetail(row)}/>;
  }

  showPublishConfirm = () => {
    const plan = store.publishPreview || {};
    const blocked = plan.blocked || [];
    const hasFiles = PLAN_GROUPS.some(g => (plan[g.key] || []).length > 0) ||
      (plan.unchanged || []).length > 0;
    const noChanges = plan.first_publish === false && plan.has_changes === false;
    let note = '';
    Modal.confirm({
      width: 720,
      title: '发布新版本',
      content: (
        <div>
          <p style={{marginBottom: 4}}>本次将把全部未移除文件发布为新的制度版本，
            生成完整、不可变的文件清单。</p>
          {plan.current_version_no != null && (
            <p style={{marginBottom: 8, color: '#888'}}>
              当前生效版本 v{plan.current_version_no}，发布后将产生新版本号。
            </p>
          )}
          {noChanges && (
            <Alert type="info" showIcon style={{marginBottom: 8}}
              message="当前没有内容或结构变化，无需重复发布"/>
          )}
          {!hasFiles && !noChanges && (
            <p style={{color: '#f5222d'}}>未获取到待发布文件清单，无法发布</p>
          )}
          {PLAN_GROUPS.map(g => this.renderPlanGroup(plan[g.key], g))}
          {this.renderUnchangedGroup(plan.unchanged)}
          {(plan.renamed > 0) && (
            <p style={{color: '#fa8c16'}}>有 {plan.renamed} 份文件已改名（内容未变）。</p>
          )}
          {plan.reordered && (
            <p style={{color: '#fa8c16'}}>文件顺序已调整。</p>
          )}
          {blocked.length > 0 && (
            <Alert type="warning" showIcon style={{marginBottom: 8}}
              message={`存在 ${blocked.length} 份受阻文件，请先按各行的处理入口解决后再发布（发布时服务端仍会重新校验）`}/>
          )}
          <textarea id="institution-change-note" rows={3} style={{width: '100%'}}
            placeholder="请填写变更说明（必填）"
            onChange={e => note = e.target.value}/>
        </div>
      ),
      okText: '确认发布',
      // 受阻或无实际变化时禁用确认：不让用户点击一个必然被服务端拒绝的按钮
      okButtonProps: {
        disabled: blocked.length > 0 || !hasFiles || noChanges,
      },
      onOk: () => {
        if (!note.trim()) {
          message.warning('请填写变更说明');
          return Promise.reject();
        }
        // 失败：拦截器提示一次，promise reject 保持弹窗，不显示成功、
        // 不清空现有数据（服务端权威校验为准）
        return http.post(`/api/institution/manuals/${store.id}/publish/`,
          {change_note: note.trim()})
          .then(() => {
            message.success('发布成功');
            store.refreshAfterLifecycle(store.id);
          });
      },
    });
  };

  render() {
    const manual = store.manual || {};
    const canPublish = (manual.my_roles || []).includes('publish');
    if (!canPublish || manual.status !== 'active') return null;
    // 整套状态弱化发布入口：已生效且无待发布变化时不再以主按钮突出
    // （预检/发布端都会拒绝无变化的重复发布；发布者仍可点开核对）
    const summary = store.draftStatus && store.draftStatus.summary;
    const noPending = !!(summary && summary.has_current_version &&
      !summary.has_pending_changes);
    const button = (
      <AuthButton auth="institution.manual.publish"
        type={noPending ? 'default' : 'primary'} size="small"
        loading={store.isFetchingPublishPreview} onClick={this.handlePublish}>
        发布新版本
      </AuthButton>
    );
    if (!noPending) return button;
    return (
      <Tooltip title="当前没有待发布变化；修改文件内容或调整文件清单后可发布新版本">
        <span>{button}</span>
      </Tooltip>
    );
  }
}

export default PublishButton;

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
 *   以数量汇总、可展开核对完整清单；逐行展示 有效负责人、提交记录状态与
 *   **逐份发布来源**（服务端 publish_source：当前草稿 / 已提交快照 /
 *   当前生效快照），供发布人核对固定快照；
 * - **固定快照交接规则（2026-11-03）**：新增/内容变化的文件，发布人即该
 *   文件有效负责人时直接使用当前草稿（publish_source=draft）；否则必须有
 *   有效提交待发布核对，发布时使用**独立不可变快照**（publish_source=
 *   submission）；未变化文件沿用当前生效快照（publish_source=
 *   current_version）。未分配负责人 / 无有效提交 / 提交已失效 /
 *   缺草稿 / 编辑会话占用均阻断发布，受阻分组逐份显示服务端 message +
 *   有效负责人 + 提交状态，并按原因给出可执行处理入口或明确等待说明；
 * - 存在受阻文件时禁用确认——不让用户点击一个必然失败的确认；
 * - 无内容/结构变化时（首发除外）服务端拒绝重复发布：预检 has_changes
 *   为假时同样禁用确认并说明；发布入口按整套状态弱化（非主按钮）。
 * - 预检不是放行凭证：发布权威校验仍在后端 publish_whole_set 行锁内
 *   重新全量复核（有效负责人/快照有效性/草稿修订号），前端禁用只是交互引导。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Modal, message, Alert, Tag, Tooltip, Button } from 'antd';
import { AuthButton } from 'components';
import { history } from 'libs';
import { http } from 'libs';
import { formatSize, formatDateTime } from '../utils';
import {
  submissionIsStale, submissionStatusOf, SUBMISSION_STATUS,
} from '../submissionShared';
import store from './store';
import institutionBadge from '../../../layout/InstitutionBadgeStore';

// 发布确认窗口的分组（与后端 publish-preview 分组一一对应）
const PLAN_GROUPS = [
  {key: 'added', title: '新增文件', color: 'blue'},
  {key: 'changed', title: '本次内容变化', color: 'orange'},
  {key: 'removed', title: '被移除（不再进入新版本）', color: 'red'},
  {key: 'blocked', title: '受阻文件（处理后方可发布）', color: 'red'},
];

/**
 * 逐份发布来源文案（2026-11-03 固定快照交接；服务端 publish_source 决定，
 * **前端不臆测**：publish_source 缺失/null 时不输出任何来源文案）：
 * - draft：将使用当前草稿（发布人就是该文件有效负责人，内容变化时直接纳入）；
 * - submission：将使用已提交快照（提交人 X，提交时间 Y）——发布人核对并
 *   发布的就是这份固定不可变快照；
 * - current_version：将沿用当前生效快照（内容未变化）。
 */
function publishSourceText(row) {
  const source = row.publish_source;
  if (source === 'draft') return '将使用当前草稿';
  if (source === 'current_version') return '将沿用当前生效快照（内容未变化）';
  if (source === 'submission') {
    const submission = row.submission || row.submission_snapshot || {};
    const by = submission.submitted_by_name || '-';
    const at = formatDateTime(submission.submitted_at);
    return `将使用已提交快照（提交人 ${by}，提交时间 ${at}）`;
  }
  return '';
}

/** 提交记录状态文案（服务端快照状态只映射不推断；2026-11-03 固定快照交接） */
function submissionStateText(submission) {
  if (!submission) return '';
  if (submission.legacy_submitted) return '旧版提交记录（不可用于发布）';
  if (submissionIsStale({submission})) return '提交已失效';
  const status = submissionStatusOf(submission);
  if (status === SUBMISSION_STATUS.PENDING) return '待发布人核对';
  if (status === SUBMISSION_STATUS.WITHDRAWN) return '已撤回';
  if (status === SUBMISSION_STATUS.RETURNED) {
    return submission.return_reason
      ? `已退回（原因：${submission.return_reason}）` : '已退回';
  }
  if (status === SUBMISSION_STATUS.PUBLISHED) return '已随发布处理';
  return '尚未提交待发布核对';
}

/** 受阻原因计数 -> 可读汇总（服务端 blocker_summary；无该字段时回退通用文案） */
const BLOCKER_LABELS = {
  unassigned: '未分配负责人',
  submission_pending: '待负责人提交待发布核对',
  submission_stale: '提交已失效',
  no_draft: '缺草稿',
  draft_missing: '草稿缺失',
  session_busy: '编辑会话占用',
};

function blockerSummaryText(summary) {
  if (!summary || typeof summary !== 'object') return '';
  return Object.keys(summary)
    .filter(key => summary[key])
    .map(key => `${BLOCKER_LABELS[key] || key} ${summary[key]} 份`)
    .join('、');
}

/** 未修改文件：数量汇总 + 可展开核对完整清单。
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

  /**
   * 逐行核对信息（2026-11-03 固定快照交接）：
   * - 受阻行：服务端 row.message（unassigned/submission_pending/
   *   submission_stale 与既有 no_draft/draft_missing/session_busy 均由后端
   *   给出可读文案）+ 编辑会话归属 + 有效负责人 + 提交记录状态；
   * - 变化/新增行：草稿修订号与大小 + 有效负责人 + **逐份发布来源**
   *   （服务端 publish_source：draft=将使用当前草稿 / submission=将使用已
   *   提交快照（提交人 X，提交时间 Y）/ current_version=将沿用当前生效快照）
   *   + 交接要求（publisher_is_owner → 发布人即该文件有效负责人，无需提交；
   *   submission_required → 显示提交记录状态，未有效提交时提示需先提交）；
   * - 未修改行：将沿用当前生效快照（内容未变化），无需提交；
   * - publish_source 缺失/null 时**不臆测来源**（不输出任何来源文案）；
   * - 旧后端（无 publish_source/submission_required 字段）保持旧展示。
   */
  planRowDetail = (row, opts) => {
    const options = opts || {};
    const parts = [];
    const blocked = !!row.reason;
    if (blocked) {
      const session = row.session;
      const sessionText = session
        ? `（${session.is_mine ? '我的编辑会话进行中' : `${session.user_name} 编辑中`}）`
        : '';
      parts.push(`${row.message}${sessionText}`);
    } else if (options.removed) {
      // 被移除行由生效快照构造，无草稿信息；移除文件不要求交接提交
      parts.push(row.from_version_no != null
        ? `移出当前生效版本 v${row.from_version_no}`
        : '移出当前生效版本');
    } else {
      parts.push(`草稿 r${row.draft_revision} · ${formatSize(row.draft_size)}`);
    }
    // 负责人展示（valid owner：effective_owner_name 优先；owner_assigned=false
    // 表示回退手册所有者默认，必须注明，绝不与"未分配"混淆）
    const ownerName = row.effective_owner_name !== undefined
      ? row.effective_owner_name : row.owner_name;
    if (ownerName !== undefined) {
      if (!ownerName) {
        parts.push('负责人 未分配');
      } else {
        parts.push(`负责人 ${ownerName}` +
          (row.owner_assigned === false ? '（手册所有者，默认）' : ''));
      }
    }
    // 提交记录状态展示口径：
    // - 新后端：受阻行与 submission_required=true 的变化/新增行展示（未变化
    //   行即使带 submission 也不显示，避免"未提交"误导）；
    // - 旧后端（无 submission_required 字段）：按旧版行为，只要行带
    //   submission 就映射展示（字段缺失不代表未提交），保持向后兼容。
    const hasRequirementFlag = row.submission_required === true ||
      row.submission_required === false;
    const showSubmission = blocked ||
      (hasRequirementFlag ? row.submission_required === true : !!row.submission);
    if (row.submission && showSubmission) {
      const text = submissionStateText(row.submission);
      if (text) parts.push(text);
    }
    if (!blocked) {
      // 逐份发布来源（服务端权威；publish_source=null 时不臆测）
      const sourceText = publishSourceText(row);
      if (options.unchanged) {
        // 未修改文件：沿用当前生效快照，不需要交接提交
        parts.push(sourceText || '未变化，无需提交');
      } else if (sourceText) {
        parts.push(sourceText);
      }
      if (row.publisher_is_owner === true) {
        parts.push(row.publish_source === 'draft'
          ? '发布人即该文件有效负责人，无需提交'
          : '发布人即该文件负责人，无需提交');
      } else if (row.submission_required === true) {
        // 来源已是"已提交快照"时无需再提示；否则要求先提交待发布核对
        const text = submissionStateText(row.submission);
        if (row.publish_source !== 'submission' &&
          (!text || text === '尚未提交待发布核对' ||
            text === '已撤回' || text === '已退回' || text === '提交已失效')) {
          parts.push('需有效提交待发布核对后方可发布');
        }
      }
    }
    return parts.join(' · ');
  };

  /** 受阻文件的可执行处理入口（2026-11-03 固定快照交接）：
   *  - unassigned：所有者/管理员给出"去「修订草稿」视图指定负责人"指引，
   *    其他账号说明需所有者/管理员处理；
   *  - submission_pending/submission_stale：明确"等待有效负责人「X」
   *    提交/重新提交待发布核对"（当前点击发布的账号若就是该文件有效负责人，
   *    后端不会要求提交，因此这里不需要链接，也不引入单/多人模式开关）；
   *  - 既有 session_busy/no_draft/draft_missing 入口保持原样。 */
  renderBlockedAction = (row) => {
    const manual = store.manual || {};
    const canEdit = (manual.my_roles || []).includes('edit');
    const deepLink = `/institution/manuals/${store.id}/draft?file=${row.file_id}`;
    const ownerName = row.effective_owner_name !== undefined
      ? row.effective_owner_name : row.owner_name;
    if (row.reason === 'unassigned') {
      if (manual.is_owner || manual.is_admin) {
        return (
          <span style={{color: '#fa8c16'}}>
            请在「修订草稿」视图为该文件指定负责人
          </span>
        );
      }
      return <span style={{color: '#999'}}>需手册所有者/管理员指定负责人</span>;
    }
    if (row.reason === 'submission_pending') {
      return (
        <span style={{color: '#999'}}>
          {ownerName ? `等待有效负责人「${ownerName}」提交待发布核对`
            : '等待文件有效负责人提交待发布核对'}
        </span>
      );
    }
    if (row.reason === 'submission_stale') {
      return (
        <span style={{color: '#999'}}>
          {ownerName ? `等待有效负责人「${ownerName}」重新提交待发布核对`
            : '等待文件有效负责人重新提交待发布核对'}
        </span>
      );
    }
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
        : <span style={{color: '#999'}}>需该文件负责人（持编制资格）建立草稿</span>;
    }
    if (row.reason === 'draft_missing') {
      return canEdit
        ? <a onClick={() => history.push(deepLink)}>去重新编辑该文件</a>
        : <span style={{color: '#999'}}>需该文件负责人（持编制资格）处理</span>;
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
              {this.planRowDetail(row, {blocked: group.key === 'blocked',
                removed: group.key === 'removed'})}
            </span>
            {group.key === 'blocked' && (
              <span style={{flexShrink: 0}}>{this.renderBlockedAction(row)}</span>
            )}
          </div>
        ))}
      </div>
    );
  };

  /** 未修改文件：数量汇总 + 可展开核对完整清单（自包含组件，见上）。
   *  未修改行按交接规则"未变化，无需提交"展示（不会出现未提交误导）。 */
  renderUnchangedGroup(rows) {
    return <UnchangedGroup rows={rows}
      renderDetail={row => this.planRowDetail(row, {unchanged: true})}/>;
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
            生成完整、不可变的新版本快照（完整文件清单）。</p>
          <p style={{marginBottom: 8, color: '#888'}}>
            发布后保留当前草稿作为后续修订的工作副本（可继续编辑后再发布）；
            历史发布版本是各自独立、不可变的快照，不会被本次或后续发布覆盖。
          </p>
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
              message={`存在 ${blocked.length} 份受阻文件（${blockerSummaryText(plan.blocker_summary) ||
                '未分配负责人/待负责人提交待发布核对/提交已失效/草稿缺失/编辑会话占用'}），请先按各行的处理入口解决后再发布（发布时服务端仍会重新校验）`}/>
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
            // 后端真实成功后立即刷新菜单红点（发布后待核对提交清零；
            // fetch 静默失败，不影响本流程）
            institutionBadge.fetch();
          });
      },
    });
  };

  render() {
    const manual = store.manual || {};
    const isOwner = !!manual.is_owner;
    // 发布资格：持发布授权（页面码 + 逐本授权）；例外：手册所有者对象级
    // 豁免（规则：所有者不需要再获得角色权限或逐本授权；后端 manual_auth
    // 与 can_publish 同口径）
    const canPublish = (manual.my_roles || []).includes('publish') || isOwner;
    if (!canPublish || manual.status !== 'active') return null;
    // 整套状态弱化发布入口：已生效且无待发布变化时不再以主按钮突出
    // （预检/发布端都会拒绝无变化的重复发布；发布者仍可点开核对）
    const summary = store.draftStatus && store.draftStatus.summary;
    const noPending = !!(summary && summary.has_current_version &&
      !summary.has_pending_changes);
    const button = isOwner ? (
      // 所有者对象级豁免：不要求 publish 页面权限码
      <Button type={noPending ? 'default' : 'primary'} size="small"
        loading={store.isFetchingPublishPreview} onClick={this.handlePublish}>
        发布新版本
      </Button>
    ) : (
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

/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 编制状态共享文案（2026-11-03 提交待发布核对·固定快照改造）：
 * 「编制状态」是详情页文件清单「修订草稿」视图 与 草稿工作台
 * （FileNav 文件导航 / ExpandedBar 顶栏 / 右侧状态条）的唯一渲染依据，
 * 把 服务端下发的文件行（草稿 / 修订进行中 / 编辑占用 / 提交快照）合成
 * 一个可读状态，供两处共用，避免各自维护一套映射。
 *
 * 状态语义（2026-11-03 新规则，最重要）：
 * - 「待发布人核对」：该文件存在**有效提交固定快照**（submission.status=
 *   pending 且未失效、frozen=true）。快照不可变、内容已冻结，负责人本人
 *   不能再重复提交，只能「撤回提交」；发布人预览/下载/最终发布读同一份
 *   快照。
 * - 「可直接纳入整套发布」：当前账号就是该文件**有效负责人**且具备发布
 *   权，仍有待发布变化——整套发布时直接使用当前草稿（发布中固定并复核），
 *   不需要提交待发布核对（提交只是交给其他发布人的可选动作）。
 * - 「待提交待发布核对」：当前账号是有效负责人、有待发布变化但无发布权：
 *   提交会创建固定快照并冻结内容，等待发布人核对。
 * - 「待负责人提交待发布核对」：当前账号非该文件有效负责人（如发布人），
 *   还有待发布变化且没有有效快照：必须等负责人提交后才能发布该文件。
 * - 「已撤回（可重新提交）」/「已退回」（Tooltip 含退回原因）：旧快照
 *   作废、内容解冻，可修改后按新规则重新提交。
 * - 「提交已失效（需重新提交）」：提交后草稿又被保存/重建，快照不再与
 *   草稿对应，必须重新提交生成新快照。
 * - 「旧版提交记录」：只有旧流程（无副本）的提交记录
 *   （submission.legacy_submitted=true）——旧提交记录不可用于发布，需按
 *   新规则重新提交待发布核对。
 * - 「编制中」：文件仍有待发布变化且有活跃编辑会话（状态优先于等待/提交
 *   类标签）；「无需提交」：已生效且无待发布变化，整套发布沿用当前生效
 *   快照，**绝不显示"未提交"**。
 *
 * 语义边界：状态只映射服务端下发的数据，前端不推断有效性（见
 * ./submissionShared.js）；草稿工作台没有 draft-status 接口，relation 传
 * null，只能凭 file.revision_open（显式持久状态）判断是否还有待发布变化。
 *
 * 返回值恒为对象（永不为 null，无草稿给占位「—」），调用方可直接渲染；
 * color 为 antd Tag 的 color 字符串，tip 为纯文本（不含 React 节点）。
 */
import {
  effectiveOwnerNameOf, isFrozenSubmission, ownerIsDefaultAssignment,
  submissionIsStale, submissionOf, submissionStatusOf, SUBMISSION_STATUS,
} from './submissionShared';
import { formatDateTime } from './utils';

// 待发布内容变化（draft-status 逐份关系）里算"有未发布变化"的取值
const CONTENT_CHANGED_STATUSES = ['modified', 'added', 'awaiting_first_publish'];

// 无草稿文件的统一占位（不可提交；绝不冒充"未提交"）
const NO_DRAFT_STATE = {
  label: '—',
  color: 'default',
  tip: '该文件还没有可编辑草稿，无法提交待发布核对',
};

/** 状态标签常量（测试与调用方可直接引用，避免散落硬编码字符串） */
export const COMPILATION_LABEL = {
  AWAITING_REVIEW: '待发布人核对',
  DIRECT_PUBLISH: '可直接纳入整套发布',
  OWNER_SUBMIT: '待提交待发布核对',
  WAITING_OWNER_SUBMIT: '待负责人提交待发布核对',
  EDITING: '编制中',
  LEGACY: '旧版提交记录',
  WITHDRAWN: '已撤回（可重新提交）',
  RETURNED: '已退回',
  STALE: '提交已失效（需重新提交）',
  NO_NEED: '无需提交',
};

/** 旧版提交记录的统一提示（唯一实现，详情/工作台/发布确认窗共用） */
export const LEGACY_SUBMISSION_TIP =
  '旧提交记录不可用于发布，需按新规则重新提交待发布核对';

/** 有效负责人显示名（空则 '-'，不伪造） */
function ownerDisplayName(file) {
  const name = effectiveOwnerNameOf(file);
  if (!name) return '未分配负责人';
  return ownerIsDefaultAssignment(file) ? `${name}（手册所有者，默认）` : name;
}

/** 提交人/提交时间说明（缺失用 '-' 占位，绝不编造） */
function submitMetaText(submission) {
  const who = (submission && submission.submitted_by_name) || '-';
  const at = formatDateTime(submission && submission.submitted_at);
  return `提交人 ${who}，提交时间 ${at}`;
}

/** 修订号文案（缺失时返回 null，由调用方跳过该段） */
function revisionText(prefix, revision) {
  return revision === null || revision === undefined ? null : `${prefix}${revision}`;
}

/** 有效负责人提示（默认负责人注明"手册所有者默认"，与负责人列同口径） */
function ownerHint(file) {
  const name = effectiveOwnerNameOf(file) || '未分配';
  return ownerIsDefaultAssignment(file)
    ? `有效负责人「${name}」（手册所有者，默认）`
    : `有效负责人「${name}」`;
}

/**
 * 逐份文件的编制状态（详情页文件清单「编制状态」列 与 草稿工作台
 * 状态 Tag 的唯一渲染依据）。
 *
 * @param {object} file /files/ 清单行原样：draft、revision_open、
 *   active_session、assignment{is_mine,is_effective_owner,owner_id,
 *   effective_owner_id,owner_assigned}、submission{status,state,frozen,
 *   legacy_submitted,snapshot,submitted_at,submitted_by_name,
 *   submission_revision,draft_revision,return_reason}（缺失=安全降级）。
 * @param {object|null} relation draft-status 逐份关系
 *   {status, session, renamed,...}；草稿工作台没有该接口，传 null。
 * @param {object} options {canPublish:boolean}——调用方按同一口径计算
 *   （手册所有者 或 my_roles 含 publish）；缺省视为无发布权。
 * @returns {{label:string, color:string, tip:string}} 永不为 null。
 */
export function buildCompilationState(file, relation, options) {
  if (!file) return {...NO_DRAFT_STATE};
  const opts = options || {};
  const draft = file.draft;
  if (!draft) return {...NO_DRAFT_STATE};

  const submission = submissionOf(file) || {};
  const assignment = file.assignment || {};
  const isMine = !!assignment.is_mine;
  const isEffectiveOwner = assignment.is_effective_owner !== undefined &&
    assignment.is_effective_owner !== null
    ? !!assignment.is_effective_owner : isMine;
  const canPublish = !!opts.canPublish;
  const status = submissionStatusOf(submission);
  const stale = submissionIsStale(file);
  const frozen = isFrozenSubmission(file);
  const legacy = !!submission.legacy_submitted;

  const contentChanged = !!(relation &&
    CONTENT_CHANGED_STATUSES.includes(relation.status));
  // unconfirmed（草稿文件缺失/编辑会话占用等）不能当作“无待发布变化”：
  // 否则会把“草稿未就绪”误标成「无需提交」，与摘要「暂不能确认」冲突。
  const unconfirmed = !!(relation && relation.status === 'unconfirmed');
  const pendingRound = contentChanged || !!file.revision_open || unconfirmed;

  // 1) 有效提交固定快照（待发布人核对）：快照不可变、内容已冻结，不能重复提交
  if (status === SUBMISSION_STATUS.PENDING && !stale) {
    return {
      label: COMPILATION_LABEL.AWAITING_REVIEW,
      color: 'green',
      tip: `已创建固定不可变快照（${submitMetaText(submission)}）并冻结该文件内容：` +
        '本轮不能开始/继续编辑、改名、调整顺序、移除或改派分工；' +
        '发布人「预览待核对快照」核对后，整套发布将使用该快照内容；' +
        '提交有效期间负责人不能重复提交，可「撤回提交」后再修改。',
    };
  }

  // 2) 有活跃编辑会话=编制中：真实状态优先于等待/提交类标签
  //    （文件正在被编辑时不能给出"无需提交"的误导提示；会话结束后才按
  //     发布权/提交状态映射后续标签）
  if (pendingRound && file.active_session) {
    const session = file.active_session;
    const who = session.is_mine ? '你（本账号）'
      : (session.user_name || '其他账号');
    return {
      label: COMPILATION_LABEL.EDITING,
      color: 'orange',
      tip: `${who}正在编辑该文件；请先「保存并结束编辑」，再提交待发布核对`,
    };
  }

  // 3) 旧版提交记录（2026-11-02 及以前的提交只记修订号、无副本）：
  //    旧记录不可用于发布，必须按新规则重新提交待发布核对
  if (legacy && pendingRound && status === SUBMISSION_STATUS.NONE && !frozen) {
    return {
      label: COMPILATION_LABEL.LEGACY,
      color: 'orange',
      tip: LEGACY_SUBMISSION_TIP,
    };
  }

  // 4) 已撤回：旧快照作废、内容解冻，可修改后重新提交
  if (status === SUBMISSION_STATUS.WITHDRAWN) {
    const who = submission.withdrawn_by_name || '-';
    return {
      label: COMPILATION_LABEL.WITHDRAWN,
      color: 'default',
      tip: `提交已于 ${formatDateTime(submission.withdrawn_at)} 由「${who}」撤回：` +
        '旧快照已作废、内容已解冻；可按新规则修改后重新提交待发布核对',
    };
  }

  // 5) 已退回（原因必填）：Tooltip 必须包含退回原因
  if (status === SUBMISSION_STATUS.RETURNED) {
    const reason = submission.return_reason || '-';
    const who = submission.returned_by_name || '-';
    return {
      label: COMPILATION_LABEL.RETURNED,
      color: 'red',
      tip: `发布人「${who}」于 ${formatDateTime(submission.returned_at)} 退回，` +
        `原因：${reason}；旧快照已作废、内容已解冻，修改后可重新提交待发布核对`,
    };
  }

  // 6) 提交已失效且仍处于待发布轮次：负责人需重新提交（生成新的固定快照）
  if (stale && pendingRound) {
    const staleTips = [];
    const submittedRevision = revisionText('原提交修订号 r',
      submission.submission_revision);
    const currentRevision = revisionText('当前草稿 r', draft.revision);
    if (submittedRevision && currentRevision) {
      staleTips.push(`提交已失效：${submittedRevision}，` +
        `但草稿已更新至 ${currentRevision}`);
    } else {
      staleTips.push('提交已失效：草稿在提交后又被保存/重建');
    }
    staleTips.push('旧快照不再与草稿对应，不能用于发布');
    staleTips.push('请负责人重新提交待发布核对');
    return {
      label: COMPILATION_LABEL.STALE,
      color: 'orange',
      tip: staleTips.join('；'),
    };
  }

  // 7) 有效负责人本人且具备发布权：整套发布直接使用当前草稿，无需提交
  if (pendingRound && isEffectiveOwner && canPublish) {
    return {
      label: COMPILATION_LABEL.DIRECT_PUBLISH,
      color: 'blue',
      tip: '你是该文件' + ownerHint(file) + '且具备发布权：本次内容变化将在整套' +
        '发布时直接使用当前草稿（发布中固定并复核）；提交待发布核对只是交给' +
        '其他发布人核对固定快照的可选动作，不是本人发布的前置步骤',
    };
  }

  // 8) 有效负责人本人有待发布变化但无发布权：需提交固定快照交给发布人核对
  if (pendingRound && isEffectiveOwner) {
    return {
      label: COMPILATION_LABEL.OWNER_SUBMIT,
      color: 'gold',
      tip: unconfirmed && !file.revision_open
        ? '草稿状态暂不能确认（草稿缺失或仍有未完成的编辑同步），请先恢复/确认草稿后再提交待发布核对'
        : '你是该文件' + ownerHint(file) + '：提交待发布核对会创建固定不可变' +
          '快照并冻结内容，等待发布人核对；发布人核对后整套发布将使用该快照',
    };
  }

  // 9) 非有效负责人（发布人视角）仍有待发布变化：必须等负责人提交固定快照
  if (pendingRound) {
    return {
      label: COMPILATION_LABEL.WAITING_OWNER_SUBMIT,
      color: 'gold',
      tip: unconfirmed && !file.revision_open
        ? '草稿状态暂不能确认（草稿缺失或仍有未完成的编辑同步），暂不能要求负责人提交待发布核对'
        : `等待文件有效负责人（${ownerHint(file)}）提交待发布核对：` +
          '提交会创建固定不可变快照并冻结内容，发布人核对快照后整套发布即可使用该快照',
    };
  }

  // 10) 已生效/无待发布变化：不要求该文件提交（绝不显示"未提交"）
  return {
    label: COMPILATION_LABEL.NO_NEED,
    color: 'default',
    tip: '该文件已生效且本次无待发布变化；整套发布将沿用当前生效快照，无需提交',
  };
}

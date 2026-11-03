/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 提交待发布核对固定快照的共享读取口径（2026-11-03）行为测试：
 * - compilationStatusShared.buildCompilationState 的标签/优先级/Tooltip
 *   （待发布人核对/可直接纳入整套发布/待提交待发布核对/待负责人提交待发布核对/
 *   已撤回/已退回（原因）/提交已失效/旧版提交记录/编制中/无需提交/无草稿）；
 * - submissionShared 的有效负责人、默认负责人、冻结/快照字段、撤回/退回门控、
 *   待核对快照预览标题（唯一实现）。
 * 均为真实执行纯函数（不读源码字符串）。
 */
import {
  buildCompilationState, COMPILATION_LABEL, LEGACY_SUBMISSION_TIP,
} from '../compilationStatusShared';
import {
  buildSubmissionPreviewTitle, canReturnSubmission, canWithdrawSubmission,
  effectiveOwnerIdOf, effectiveOwnerNameOf, hasPublishRight,
  isEffectiveOwnerOf, isFrozenSubmission, ownerIsDefaultAssignment,
  submissionIsStale, submissionOf, submissionSnapshotFileName,
  submissionStatusOf, SUBMISSION_STATUS,
} from '../submissionShared';

const DRAFT = {revision: 5, file_name: '甲.docx',
  last_saved_at: '2026-03-01T10:00:00'};

function makeFile(over) {
  return {
    id: 1, name: '甲.docx', revision_open: true, active_session: null,
    draft: DRAFT,
    assignment: {owner_id: 9, owner_name: '我', note: '',
      is_mine: true, is_effective_owner: true, effective_owner_id: 9,
      effective_owner_name: '我', owner_assigned: true},
    ...over,
  };
}

const PENDING = {
  status: SUBMISSION_STATUS.PENDING, frozen: true,
  submitted_by_name: '张三', submitted_at: '2026-03-05T09:00:00',
  submission_revision: 5, draft_revision: 5,
  snapshot: {file_name: '甲_提交快照.docx'},
  can_withdraw: true, can_return: false,
};

describe('buildCompilationState（固定快照交接状态映射）', () => {
  it('有效快照 → 待发布人核对（优先级高于编辑中/无需提交），Tooltip 含冻结与提交人时间', () => {
    const state = buildCompilationState(makeFile({
      submission: PENDING,
      active_session: {is_mine: true, user_name: '我'},
      revision_open: false,
    }), {status: 'changed'}, {canPublish: true});
    expect(state.label).toBe(COMPILATION_LABEL.AWAITING_REVIEW);
    expect(state.tip).toContain('固定不可变快照');
    expect(state.tip).toContain('提交人 张三');
    expect(state.tip).toContain('提交时间 2026-03-05 09:00:00');
    expect(state.tip).toContain('冻结');
  });

  it('提交失效（草稿修订号已推进）→ 提交已失效，提示需重新提交', () => {
    const state = buildCompilationState(makeFile({
      draft: {...DRAFT, revision: 7},
      submission: {...PENDING, state: 'stale', frozen: false,
        submission_revision: 5},
    }), {status: 'changed'}, {canPublish: true});
    expect(state.label).toBe(COMPILATION_LABEL.STALE);
    expect(state.tip).toContain('原提交修订号 r5');
    expect(state.tip).toContain('当前草稿 r7');
    expect(state.tip).toContain('重新提交');
  });

  it('已撤回 → 已撤回（可重新提交），Tooltip 含撤回时间与撤回人', () => {
    const state = buildCompilationState(makeFile({
      submission: {status: SUBMISSION_STATUS.WITHDRAWN, frozen: false,
        withdrawn_by_name: '我', withdrawn_at: '2026-03-06T10:00:00'},
    }), {status: 'changed'}, {canPublish: true});
    expect(state.label).toBe(COMPILATION_LABEL.WITHDRAWN);
    expect(state.tip).toContain('2026-03-06 10:00:00');
    expect(state.tip).toContain('撤回');
    expect(state.tip).toContain('内容已解冻');
  });

  it('已退回 → 已退回，Tooltip 必须包含退回原因', () => {
    const state = buildCompilationState(makeFile({
      submission: {status: SUBMISSION_STATUS.RETURNED, frozen: false,
        returned_by_name: '王五', returned_at: '2026-03-06T11:00:00',
        return_reason: '缺少审批依据'},
    }), {status: 'changed'}, {canPublish: true});
    expect(state.label).toBe(COMPILATION_LABEL.RETURNED);
    expect(state.tip).toContain('缺少审批依据');
    expect(state.tip).toContain('王五');
  });

  it('旧版提交记录 → 旧版提交记录 + 旧记录不可用于发布的统一提示', () => {
    const state = buildCompilationState(makeFile({
      submission: {status: 'none', legacy_submitted: true, frozen: false},
    }), {status: 'changed'}, {canPublish: true});
    expect(state.label).toBe(COMPILATION_LABEL.LEGACY);
    expect(state.tip).toBe(LEGACY_SUBMISSION_TIP);
  });

  it('有效负责人兼发布权且有待发布变化 → 可直接纳入整套发布', () => {
    const state = buildCompilationState(makeFile(), {status: 'changed'},
      {canPublish: true});
    expect(state.label).toBe(COMPILATION_LABEL.DIRECT_PUBLISH);
    expect(state.tip).toContain('直接使用当前草稿');
    expect(state.tip).toContain('可选动作');
  });

  it('有效负责人无发布权 → 待提交待发布核对', () => {
    const state = buildCompilationState(makeFile(), {status: 'changed'},
      {canPublish: false});
    expect(state.label).toBe(COMPILATION_LABEL.OWNER_SUBMIT);
    expect(state.tip).toContain('固定不可变');
  });

  it('非有效负责人（发布人视角）有待发布变化 → 待负责人提交待发布核对', () => {
    const state = buildCompilationState(makeFile({
      assignment: {owner_id: 5, owner_name: '李四', note: '',
        is_mine: false, is_effective_owner: false, effective_owner_id: 5,
        effective_owner_name: '李四', owner_assigned: true},
    }), {status: 'changed'}, {canPublish: true});
    expect(state.label).toBe(COMPILATION_LABEL.WAITING_OWNER_SUBMIT);
    expect(state.tip).toContain('李四');
  });

  it('默认负责人（owner_assigned=false）：Tooltip 注明「手册所有者，默认」', () => {
    const state = buildCompilationState(makeFile({
      assignment: {owner_id: null, owner_name: '', note: '', is_mine: false,
        is_effective_owner: false, effective_owner_id: 3,
        effective_owner_name: '王五', owner_assigned: false},
    }), {status: 'changed'}, {canPublish: true});
    expect(state.label).toBe(COMPILATION_LABEL.WAITING_OWNER_SUBMIT);
    expect(state.tip).toContain('王五');
    expect(state.tip).toContain('（手册所有者，默认）');
  });

  it('有活跃编辑会话优先于提交/等待类标签（编制中）', () => {
    const state = buildCompilationState(makeFile({
      submission: {status: 'none', legacy_submitted: false},
      active_session: {is_mine: false, user_name: '李四'},
    }), {status: 'changed'}, {canPublish: true});
    expect(state.label).toBe(COMPILATION_LABEL.EDITING);
    expect(state.tip).toContain('李四');
  });

  it('已生效且无待发布变化 → 无需提交（绝不显示"未提交"）', () => {
    const state = buildCompilationState(makeFile({revision_open: false,
      submission: null}), {status: 'unchanged'}, {canPublish: true});
    expect(state.label).toBe(COMPILATION_LABEL.NO_NEED);
    expect(state.tip).toContain('沿用当前生效快照');
    expect(state.tip).not.toContain('未提交');
  });

  it('无草稿文件 → 占位「—」，不冒充"未提交"', () => {
    const state = buildCompilationState(makeFile({draft: null}), null,
      {canPublish: true});
    expect(state.label).toBe('—');
    expect(state.tip).toContain('没有可编辑草稿');
  });
});

describe('submissionShared（有效负责人/快照字段/门控）', () => {
  it('有效负责人：effective_owner_id 优先，owner_assigned=false 表示手册所有者默认', () => {
    const file = makeFile({
      assignment: {owner_id: null, owner_name: '', note: '', is_mine: false,
        is_effective_owner: false, effective_owner_id: 3,
        effective_owner_name: '王五', owner_assigned: false},
    });
    expect(effectiveOwnerIdOf(file)).toBe(3);
    expect(effectiveOwnerNameOf(file)).toBe('王五');
    expect(ownerIsDefaultAssignment(file)).toBe(true);
    expect(isEffectiveOwnerOf(file)).toBe(false);
    // 旧 payload（无 is_effective_owner）回退 is_mine
    expect(isEffectiveOwnerOf(makeFile({
      assignment: {owner_id: 9, owner_name: '我', is_mine: true},
    }))).toBe(true);
    // 只有 effective_owner_id 为空才是未分配
    expect(effectiveOwnerIdOf(makeFile({
      assignment: {owner_id: null, owner_name: '', effective_owner_id: null},
    }))).toBeNull();
  });

  it('冻结与快照字段：frozen/旧 payload status 降级/失效判定', () => {
    const pending = makeFile({submission: PENDING});
    expect(isFrozenSubmission(pending)).toBe(true);
    expect(submissionStatusOf(submissionOf(pending)))
      .toBe(SUBMISSION_STATUS.PENDING);
    expect(submissionIsStale(pending)).toBe(false);
    // 旧 payload：state='stale' 仍映射 pending，由 stale 判据裁决
    const stale = makeFile({draft: {...DRAFT, revision: 6},
      submission: {state: 'stale', submitted_revision: 5,
        submission_revision: 5}});
    expect(submissionStatusOf(submissionOf(stale)))
      .toBe(SUBMISSION_STATUS.PENDING);
    expect(submissionIsStale(stale)).toBe(true);
    // 旧 payload 的 submitted 也映射为 pending（有效快照）
    expect(submissionStatusOf({state: 'submitted'}))
      .toBe(SUBMISSION_STATUS.PENDING);
    expect(submissionStatusOf(null)).toBe(SUBMISSION_STATUS.NONE);
  });

  it('撤回门控：服务端 can_withdraw 优先，缺省按 pending+未失效+有效负责人', () => {
    const file = makeFile({submission: {...PENDING, can_withdraw: undefined}});
    expect(canWithdrawSubmission(file)).toBe(true);
    expect(canWithdrawSubmission(makeFile({
      submission: {...PENDING, can_withdraw: false}}))).toBe(false);
    // 失效快照不可撤回（需重新提交）
    expect(canWithdrawSubmission(makeFile({
      draft: {...DRAFT, revision: 7}, submission: {...PENDING,
        can_withdraw: undefined}}))).toBe(false);
    // 非有效负责人不可撤回
    expect(canWithdrawSubmission(makeFile({
      assignment: {owner_id: 5, owner_name: '李四', is_mine: false,
        is_effective_owner: false, effective_owner_id: 5},
      submission: {...PENDING, can_withdraw: undefined}}))).toBe(false);
  });

  it('退回门控：服务端 can_return 优先，缺省=持发布权且非有效负责人', () => {
    const publisher = {is_owner: false, my_roles: ['publish']};
    const notOwnerFile = makeFile({
      assignment: {owner_id: 5, owner_name: '李四', note: '', is_mine: false,
        is_effective_owner: false, effective_owner_id: 5},
      submission: {...PENDING, can_return: undefined},
    });
    expect(hasPublishRight(publisher)).toBe(true);
    expect(canReturnSubmission(notOwnerFile, publisher)).toBe(true);
    // 无发布权不能退回
    expect(canReturnSubmission(notOwnerFile,
      {is_owner: false, my_roles: ['edit']})).toBe(false);
    // 有效负责人本人不能退回自己的提交（应撤回）
    expect(canReturnSubmission(makeFile({
      submission: {...PENDING, can_return: undefined}},
      {is_owner: false, my_roles: ['publish']}))).toBe(false);
    expect(canReturnSubmission(makeFile({
      submission: {...PENDING, can_return: true}}), null)).toBe(true);
  });

  it('待核对快照文件名/预览标题：快照文件名优先，标题唯一格式含提交人与时间', () => {
    const file = makeFile({submission: PENDING});
    expect(submissionSnapshotFileName(file)).toBe('甲_提交快照.docx');
    expect(buildSubmissionPreviewTitle(file)).toBe(
      '预览待核对快照：甲_提交快照.docx（提交人 张三，提交时间 2026-03-05 09:00:00）');
    // 接口响应优先于快照落库字段
    expect(buildSubmissionPreviewTitle(file, {
      file_name: '接口快照.docx', submitted_by_name: '李四',
      submitted_at: '2026-03-06T10:00:00',
    })).toBe('预览待核对快照：接口快照.docx（提交人 李四，提交时间 2026-03-06 10:00:00）');
    // 无快照数据时退到草稿文件名，绝不编造提交人/时间
    const noSnapshot = makeFile({submission: {status: 'pending'}});
    expect(submissionSnapshotFileName(noSnapshot)).toBe('甲.docx');
    expect(buildSubmissionPreviewTitle(noSnapshot)).toContain('提交人 -');
  });
});

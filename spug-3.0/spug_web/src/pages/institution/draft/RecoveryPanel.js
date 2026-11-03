/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 无草稿文件的恢复面板（2026-11-02 简化为两态；恢复途径由后端权威决定，
 * 前端不猜恢复来源）：
 * - draft_recovery.source === 'current_version'（当前生效版本含该文件快照）：
 *   提示当前版本 vN 可恢复，按钮「从当前生效版本恢复草稿」；成功后提示
 *   「草稿已恢复（修订号 rN，来源版本 vN）」。
 * - source === 'none'（或字段缺失；没有可恢复的发布快照）：仅警示重新上传
 *   制度文件建立草稿（已有历史版本时先在「版本与发布」中回退重建草稿），
 *   **不显示任何恢复/重建按钮**，绝不回退到历史副本（相关能力已整体删除）。
 * - 恢复请求：POST draft/create 空体（后端按根的权威规则决定能否恢复）；
 *   失败不弹成功（拦截器已提示，不重复弹错）。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Alert, message } from 'antd';
import ManualAuthButton from '../ManualAuthButton';
import store from './store';

const RecoveryPanel = observer(({file}) => {
  /** 从当前生效版本快照恢复草稿（空体请求，后端负责校验） */
  const recoverDraft = () => {
    store.recoverDraft(file.id)
      .then(data => {
        const draft = data || {};
        const revision = draft.revision != null ? draft.revision : '';
        const versionNo = draft.base_version_no != null
          ? draft.base_version_no : (file.draft_recovery || {}).version_no;
        message.success(
          `草稿已恢复（修订号 r${revision}，来源版本 v${versionNo}）`);
      })
      .catch(() => {});
  };

  const hint = file.draft_recovery || {};
  if (hint.source === 'current_version') {
    return (
      <Alert type="warning" showIcon style={{marginTop: 12}} message={
        <div>
          <div style={{marginBottom: 8}}>
            该文件还没有草稿。当前生效版本为 v{hint.version_no}，
            可从该版本的完整文件快照恢复草稿。
          </div>
          <ManualAuthButton manual={store.manual} auth="institution.manual.draft_edit"
            type="primary" size="small"
            onClick={recoverDraft}>
            从当前生效版本恢复草稿
          </ManualAuthButton>
        </div>}/>
    );
  }
  // source==='none' 或缺失：没有可恢复的发布快照——只提示重新上传，
  // 不渲染任何恢复/重建按钮（历史来源/高级恢复/更换来源入口已删除）
  return (
    <Alert type="warning" showIcon style={{marginTop: 12}}
      message={
        <div>
          该文件没有可恢复的发布快照。请重新上传制度文件建立草稿
          （已有历史版本时，可先在「版本与发布」中回退重建草稿）。
        </div>
      }/>
  );
});

export default RecoveryPanel;

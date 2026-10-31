/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug/spug
 * Released under the AGPL-3.0 License.
 *
 * 无草稿文件的恢复面板（2026-10-31 自工作台 index.js 抽出，行为与文案
 * 不变；恢复优先级由后端权威决定，前端不猜恢复来源）：
 * - 途径以 files 清单行下发的 draft_recovery 渲染（source=current_version
 *   显示「从当前生效版本恢复草稿」；requires_confirm 只能走高级恢复；
 *   其余显示「从初始原稿创建草稿」）；
 * - 默认恢复 POST draft/create（空体）；高级恢复明确确认后携带
 *   {original_id, confirm: true} 与本次访问已验证密码（丢弃现有草稿且
 *   配置了编辑密码时后端要求校验）；
 * - 成功提示带新修订号与来源（base_version_no）；失败不弹成功
 *   （拦截器已提示，不重复弹错）。
 */
import React from 'react';
import { observer } from 'mobx-react';
import { Alert, Button, message, Modal } from 'antd';
import ManualAuthButton from '../ManualAuthButton';
import store from './store';

const RecoveryPanel = observer(({file}) => {
  /** 默认恢复：后端按优先级从当前生效版本快照或初始原稿建立草稿 */
  const recoverDraft = () => {
    store.recoverDraft(file.id)
      .then(data => {
        const revision = data && data.revision != null ? data.revision : '';
        const source = data && data.base_version_no != null
          ? `来源版本 v${data.base_version_no}`
          : '来源：初始原稿';
        message.success(`草稿已恢复（修订号 r${revision}，${source}）`);
      })
      .catch(() => {});
  };

  /** 高级恢复：明确「从原始上传文件重建草稿」，高风险确认后执行 */
  const showAdvancedRecovery = () => {
    store.fetchFileOriginals(file.id).then(originals => {
      const latest = originals && originals[0];
      if (!latest) {
        message.warning('该文件没有可用的原始上传文件，请先在详情页上传原稿');
        return;
      }
      Modal.confirm({
        title: '从原始上传文件重建草稿（高级恢复）',
        content: (
          <div>
            <p>
              将以原始上传文件「{latest.file_name}」的副本重建该文件草稿，
              不可撤销。
            </p>
            <p style={{color: '#f5222d'}}>
              该制度已发布过版本，此操作以原始文件（而非当前生效版本）为编辑基线，
              仅在当前生效版本不含该文件或管理员明确要求从原始文件重新开始时使用。
            </p>
          </div>
        ),
        okText: '确认重建',
        onOk: () => store.rebuildDraftFromOriginal(
            file.id, latest.id, store.verifiedPassword || undefined)
          .then(data => {
            const revision = data && data.revision != null ? data.revision : '';
            message.success(`草稿已按原始上传文件重建（修订号 r${revision}）`);
          }),
      });
    }).catch(() => {});
  };

  const hint = file.draft_recovery || {source: 'original'};
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
  if (hint.requires_confirm) {
    return (
      <Alert type="warning" showIcon style={{marginTop: 12}} message={
        <div>
          <div style={{marginBottom: 8}}>
            该文件还没有草稿，且{hint.note || '当前生效版本不包含该文件'}；
            不能自动从原始上传文件补建，如确认需要请执行高级恢复操作。
          </div>
          <Button danger size="small" onClick={showAdvancedRecovery}>
            从原始上传文件重建草稿（高级恢复）
          </Button>
        </div>}/>
    );
  }
  return (
    <Alert type="warning" showIcon style={{marginTop: 12}} message={
      <div>
        <div style={{marginBottom: 8}}>
          该文件还没有草稿，可从初始原稿创建草稿。
        </div>
        <ManualAuthButton manual={store.manual} auth="institution.manual.draft_edit"
          type="primary" size="small"
          onClick={recoverDraft}>
          从初始原稿创建草稿
        </ManualAuthButton>
      </div>}/>
  );
});

export default RecoveryPanel;

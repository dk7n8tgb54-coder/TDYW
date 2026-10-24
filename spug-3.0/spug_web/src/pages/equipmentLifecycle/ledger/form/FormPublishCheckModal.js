/**
 * Copyright (c) OpenSpug Organization. https://github.com/openspug
 * Released under the AGPL-3.0 License.
 *
 * 数字表单模板发布检查弹窗（2026-10-23 P2，设计方案 5.3）。
 *
 * - 集中展示 publish-check 返回的阻断错误（errors，红）与非阻断提醒
 *   （warnings，黄）；有错误时发布按钮禁用，仅警告时须勾选"已知悉"才能
 *   继续发布——发布判定以后端行锁内重新校验为准，本弹窗只是提示；
 * - 每项可点击定位：携带 anchor（与编辑器 selection 同构）上抛 onLocate，
 *   编辑器关闭弹窗并选中对应分组/字段/矩阵行列后滚动定位；anchor 为空
 *   （协议版本/字段总数等整体项）的条目不可点击；
 * - issues 由父级条件渲染（每次打开重新挂载），勾选态不跨次残留。
 */
import React, {useState} from 'react';
import {Alert, Button, Checkbox, Modal, Tag} from 'antd';

function IssueItem({item, kind, onLocate}) {
  const clickable = !!(item.anchor && item.anchor.groupId);
  return (
    <div style={{display: 'flex', alignItems: 'flex-start', gap: 8,
                 padding: '6px 0', borderBottom: '1px solid #f0f0f0'}}
         data-testid={`publish-check-item-${item.code}`}>
      <Tag color={kind === 'error' ? 'red' : 'orange'}>
        {kind === 'error' ? '阻断' : '提醒'}
      </Tag>
      {clickable ? (
        <a style={{flex: 1}} onClick={() => onLocate(item.anchor)}
           data-testid={`publish-check-locate-${item.code}`}>{item.message}</a>
      ) : (
        <span style={{flex: 1}}>{item.message}</span>
      )}
    </div>
  );
}

export default function FormPublishCheckModal({visible, issues, publishing,
                                               onClose, onPublish, onLocate}) {
  const [acknowledged, setAcknowledged] = useState(false);
  if (!issues) {
    return null;
  }
  const errors = issues.errors || [];
  const warnings = issues.warnings || [];
  const hasErrors = errors.length > 0;
  const canPublish = !hasErrors && (warnings.length === 0 || acknowledged);
  return (
    <Modal title="发布检查" visible={visible} width={640} onCancel={onClose}
           footer={[
             <Button key="close" onClick={onClose}>
               {hasErrors ? '返回修改' : '取消'}
             </Button>,
             <Button key="publish" type="primary" disabled={!canPublish}
                     loading={publishing} data-testid="publish-check-confirm"
                     onClick={onPublish}>
               发布版本
             </Button>,
           ]}>
      {hasErrors ? (
        <Alert type="error" showIcon style={{marginBottom: 12}}
               message={`发现 ${errors.length} 项阻断问题，需修复后才能发布`}/>
      ) : warnings.length ? (
        <Alert type="warning" showIcon style={{marginBottom: 12}}
               message={`结构校验通过，有 ${warnings.length} 项提醒（不影响发布）`}/>
      ) : (
        <Alert type="success" showIcon style={{marginBottom: 12}}
               message="结构校验通过，无阻断问题与提醒"/>
      )}
      <div data-testid="publish-check-errors">
        {errors.map((item, index) => (
          <IssueItem key={`error-${index}`} item={item}
                     kind="error" onLocate={onLocate}/>
        ))}
      </div>
      <div data-testid="publish-check-warnings">
        {warnings.map((item, index) => (
          <IssueItem key={`warning-${index}`} item={item}
                     kind="warning" onLocate={onLocate}/>
        ))}
      </div>
      {!hasErrors && warnings.length > 0 && (
        <div style={{marginTop: 12}}>
          <Checkbox checked={acknowledged}
                    data-testid="publish-check-acknowledge"
                    onChange={e => setAcknowledged(e.target.checked)}>
            我已知悉上述提醒，仍要发布
          </Checkbox>
        </div>
      )}
    </Modal>
  );
}

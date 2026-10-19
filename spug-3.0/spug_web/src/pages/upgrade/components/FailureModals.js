/**
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 升级失败处理弹窗（阶段失败闭环，2026-10 改造）：
 * - FailureCreateModal：标记阶段失败（失败原因必填，后端创建失败单）；
 * - FailureHandleModal：处理失败——展示失败信息，选择重做范围（部分步骤/整个阶段）
 *   或更正失败记录（误标场景，填写原因追加更正事件，原失败事件保留）。
 *
 * 均为受控 Modal：提交走真实动作函数，成功后才由父组件关闭。
 */
import React, {useState, useEffect} from 'react';
import {Modal, Input, Checkbox, Tag, Alert, Typography, Button} from 'antd';
import {STEP_STATUS_TEXT} from '../shared';
import {markPhaseFailure, startFailureRedo, correctFailure} from '../workbenchActions';

const {TextArea} = Input;

/** 标记阶段失败：原因必填（失败阶段/时间/操作人/原因由后端记录） */
export function FailureCreateModal({visible, recordId, phase, onCancel, onDone}) {
  const [reason, setReason] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (visible) setReason('');
  }, [visible, phase]);

  function handleOk() {
    if (!reason.trim()) return;
    setSubmitting(true);
    markPhaseFailure(recordId, phase, reason.trim())
      .then(() => {
        if (onDone) onDone();
      })
      .finally(() => setSubmitting(false));
  }

  return (
    <Modal title={`标记【${phase}】失败`} visible={visible} onCancel={onCancel}
      okText="标记失败" okButtonProps={{danger: true, disabled: !reason.trim(), loading: submitting}}
      onOk={handleOk} width={520}>
      <Alert type="warning" showIcon style={{marginBottom: 12}}
        message="标记失败后该阶段进入「处理失败」流程：保留当前步骤现场，需选择重做范围后才能继续执行该阶段。" />
      <div style={{marginBottom: 8}}>失败阶段：<strong>{phase}</strong></div>
      <div style={{marginBottom: 4}}>失败原因（必填）：</div>
      <TextArea rows={3} value={reason} maxLength={500}
        placeholder="请描述失败现象、影响与初步判断（保存后可在处理失败中查看）"
        onChange={e => setReason(e.target.value)} />
    </Modal>
  );
}

/** 重做范围步骤勾选列表（带状态标签） */
function FailureStepPicker({steps, selectedIds, onToggle}) {
  if (steps.length === 0) return <div>该阶段暂无步骤。</div>;
  return (
    <React.Fragment>
      {steps.map(s => (
        <div key={s.id} style={{padding: '4px 0'}}>
          <Checkbox checked={selectedIds.includes(s.id)} onChange={() => onToggle(s.id)}>
            {s.title}
            <Tag style={{marginLeft: 8}}
              color={s.status === 'pending' ? 'default'
                : (s.status === 'completed' ? 'success' : 'warning')}>
              {STEP_STATUS_TEXT[s.status] || s.status}
            </Tag>
          </Checkbox>
        </div>
      ))}
    </React.Fragment>
  );
}

/** 更正失败原因区块（误标场景；追加事件保留原失败记录） */
function CorrectReasonSection({value, onChange, onSubmit, submitting}) {
  return (
    <div style={{marginTop: 8}}>
      <TextArea rows={2} value={value} maxLength={500}
        placeholder="请填写更正原因（误标说明）；更正会以追加事件保留原失败记录"
        onChange={e => onChange(e.target.value)} />
      <Button type="primary" size="small" style={{marginTop: 8}}
        disabled={!value.trim() || submitting}
        onClick={onSubmit}>确认更正</Button>
    </div>
  );
}

/** 处理失败：选择重做范围 / 更正失败记录 */
export function FailureHandleModal({visible, recordId, failure, steps, onCancel, onDone}) {
  const [selectedIds, setSelectedIds] = useState([]);
  const [correcting, setCorrecting] = useState(false);
  const [correctReason, setCorrectReason] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const failureId = failure ? failure.id : null;
  useEffect(() => {
    if (visible) {
      setSelectedIds([]);
      setCorrecting(false);
      setCorrectReason('');
    }
  }, [visible, failureId]);

  if (!failure) return null;
  const isPending = failure.status === 'pending';
  const isRedoing = failure.status === 'redoing';

  function toggleStep(id) {
    setSelectedIds(prev => prev.includes(id)
      ? prev.filter(x => x !== id) : [...prev, id]);
  }

  function submitRedo(allSteps) {
    if (!allSteps && selectedIds.length === 0) return;
    setSubmitting(true);
    startFailureRedo(recordId, failure.id, {
      stepIds: allSteps ? steps.map(s => s.id) : selectedIds,
      allSteps,
    })
      .then(() => {
        if (onDone) onDone();
      })
      .finally(() => setSubmitting(false));
  }

  function submitCorrect() {
    if (!correctReason.trim()) return;
    setSubmitting(true);
    correctFailure(recordId, failure.id, correctReason.trim())
      .then(() => {
        if (onDone) onDone();
      })
      .finally(() => setSubmitting(false));
  }

  return (
    <Modal title={`处理失败【${failure.phase}】`} visible={visible}
      footer={null} onCancel={onCancel} width={640}>
      <FailureInfoHeader failure={failure} isPending={isPending} isRedoing={isRedoing} />
      {isPending && (
        <div style={{marginBottom: 12}}>
          <div style={{marginBottom: 6}}>
            选择需要重新执行的步骤（已选 {selectedIds.length} 个）：
          </div>
          <FailureStepPicker steps={steps} selectedIds={selectedIds} onToggle={toggleStep}/>
          <div style={{marginTop: 12, display: 'flex', gap: 8}}>
            <Button disabled={submitting} onClick={() => submitRedo(true)}>重做整个阶段</Button>
            <Button type="primary" disabled={submitting || selectedIds.length === 0}
              onClick={() => submitRedo(false)}>
              开始重做（已选 {selectedIds.length} 个）
            </Button>
            <span style={{flex: 1}} />
            <Button type="text" disabled={submitting}
              onClick={() => setCorrecting(v => !v)}>更正失败记录</Button>
          </div>
          {correcting && (
            <CorrectReasonSection value={correctReason} onChange={setCorrectReason}
              onSubmit={submitCorrect} submitting={submitting}/>
          )}
        </div>
      )}
      {isRedoing && (
        <div>
          <div style={{display: 'flex', gap: 8}}>
            <span style={{flex: 1}} />
            <Button type="text" onClick={() => setCorrecting(v => !v)}>更正失败记录</Button>
          </div>
          {correcting && (
            <CorrectReasonSection value={correctReason} onChange={setCorrectReason}
              onSubmit={submitCorrect} submitting={submitting}/>
          )}
        </div>
      )}
    </Modal>
  );
}

/** 失败单信息头（阶段/状态/原因/标记人/重做进度/待处理提示） */
function FailureInfoHeader({failure, isPending, isRedoing}) {
  return (
    <div style={{marginBottom: 12}}>
      <div><strong>失败阶段：</strong>{failure.phase}
        <Tag style={{marginLeft: 8}} color={isPending ? 'error' : 'warning'}>
          {failure.status_display}
        </Tag>
      </div>
      <div><strong>失败原因：</strong>
        <Typography.Paragraph style={{whiteSpace: 'pre-wrap', marginBottom: 0}}
          ellipsis={{rows: 4, expandable: true, symbol: '展开'}}>
          {failure.reason || '（旧记录未保存失败原因）'}
        </Typography.Paragraph>
      </div>
      <div><strong>标记人 / 时间：</strong>{failure.failed_by_name || '-'} / {failure.failed_at || '-'}</div>
      {isRedoing && (
        <div>
          <strong>重做范围：</strong>选择 {failure.redo_selected_count} 个步骤，
          实际重置 {failure.redo_reset_count} 个
          （{failure.redo_by_name || '-'} / {failure.redo_at || '-'}）。
          完成重做步骤后该阶段重新记录完成，失败自动结案。
        </div>
      )}
      {isPending && (
        <Alert type="info" showIcon style={{marginTop: 8}}
          message="失败待处理期间该阶段禁止普通完成/跳过，请先选择重做范围；前面已完成的阶段保持完成。" />
      )}
    </div>
  );
}

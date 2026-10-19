/**
 * Copyright (c) <spug.dev@gmail.com>
 * Released under the AGPL-3.0 License.
 */
/**
 * 从某阶段重新执行弹窗（原"回退到某阶段"的明确化，2026-10 改造）：
 * - 预览来自后端 redo-preview 接口（真实步骤数据，与执行同口径，不信任前端计算）；
 * - 后续已完成阶段须显式选择：同时重新执行 / 保留并确认有效（理由必填）；
 * - 展示覆盖范围内的失败待处理阶段（将随重新执行解除阻塞）；
 * - 明确"仅重置工作清单，不代表软件/配置/数据库已实际回滚"。
 */
import React, {useState, useEffect} from 'react';
import {Modal, Input, Radio, Alert, Tag, Spin} from 'antd';
import {http} from 'libs';
import {executeRedoFrom} from '../workbenchActions';

const {TextArea} = Input;

export function RedoFromModal({visible, recordId, phase, onCancel, onDone}) {
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [laterAction, setLaterAction] = useState('redo');
  const [laterReason, setLaterReason] = useState('');
  const [note, setNote] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (visible && phase) {
      setLoading(true);
      setPreview(null);
      http.get(
        `/api/upgrade/records/${recordId}/redo-preview/?target_phase=${encodeURIComponent(phase)}`)
        .then(data => {
          setPreview(data || null);
          const later = ((data && data.later_completed_phases) || []);
          setLaterAction(later.length > 0 ? 'redo' : 'redo');
        })
        .catch(() => setPreview(null))
        .finally(() => setLoading(false));
    } else {
      setPreview(null);
      setLaterReason('');
      setNote('');
      setLaterAction('redo');
    }
  }, [visible, phase, recordId]);

  const laterCompleted = (preview && preview.later_completed_phases) || [];
  const pendingFailures = (preview && preview.pending_failures) || [];

  function handleOk() {
    setSubmitting(true);
    executeRedoFrom(recordId, {
      targetPhase: phase,
      laterAction,
      laterReason,
      note,
    })
      .then(() => {
        if (onDone) onDone();
      })
      .finally(() => setSubmitting(false));
  }

  return (
    <Modal title={`从「${phase}」重新执行`} visible={visible} onCancel={onCancel}
      okText="确认重新执行"
      okButtonProps={{
        danger: true,
        disabled: loading || !preview
          || (laterCompleted.length > 0 && laterAction === 'keep' && !laterReason.trim()),
        loading: submitting,
      }}
      onOk={handleOk} width={640}>
      <Alert type="warning" showIcon style={{marginBottom: 12}}
        message="本操作只重置工作清单（把步骤改回待执行），不代表软件、配置或数据库已经实际回滚。" />

      <Spin spinning={loading}>
        {preview && (
          <div>
            <div style={{marginBottom: 6}}>
              目标阶段及后续阶段重新执行，前面阶段保持原状。
              共 <strong>{preview.selected_count}</strong> 个已执行步骤将重置为待执行：
            </div>
            <div style={{marginBottom: 10}}>
              {(preview.phases || []).map(p => (
                <div key={p.name} style={{padding: '2px 0'}}>
                  <Tag>{p.name}</Tag>
                  共 {p.total} 步：{p.to_reset} 个已完成/已跳过将重置，
                  {p.pending} 个待执行保持不变
                </div>
              ))}
            </div>

            {pendingFailures.length > 0 && (
              <Alert type="info" showIcon style={{marginBottom: 10}}
                message={`范围内包含失败待处理阶段（${pendingFailures.map(f => `【${f.phase}】`).join('、')}），重新执行将一并解除其失败阻塞。`} />
            )}

            {laterCompleted.length > 0 && (
              <div style={{marginBottom: 10}}>
                <div style={{marginBottom: 6}}>
                  后续已完成阶段（<strong>{laterCompleted.join('、')}</strong>）如何处理？
                </div>
                <Radio.Group value={laterAction}
                  onChange={e => setLaterAction(e.target.value)}>
                  <Radio value="redo">同时重新执行后续阶段（其已完成结果一并重置）</Radio>
                  <Radio value="keep">保留后续结果，确认其继续有效</Radio>
                </Radio.Group>
                {laterAction === 'keep' && (
                  <div style={{marginTop: 8}}>
                    <TextArea rows={2} maxLength={500} value={laterReason}
                      placeholder="请填写保留后续结果继续有效的理由（必填，将写入事件历史）"
                      onChange={e => setLaterReason(e.target.value)} />
                  </div>
                )}
              </div>
            )}

            <div style={{marginBottom: 4}}>补充说明（选填）：</div>
            <TextArea rows={2} maxLength={500} value={note}
              placeholder="记录本次重新执行的原因或背景"
              onChange={e => setNote(e.target.value)} />
          </div>
        )}
        {!preview && !loading && (
          <div style={{color: '#999'}}>影响范围加载失败，请关闭后重试。</div>
        )}
      </Spin>
    </Modal>
  );
}

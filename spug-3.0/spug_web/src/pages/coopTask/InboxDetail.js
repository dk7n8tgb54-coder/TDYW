/**
 * 交付详情（交付科室视角）
 * 逐材料上传附件（AttachmentManager）并提交，退回后可重新修改提交
 */
import React, {useState, useEffect, useCallback, useRef} from 'react';
import {Modal, Descriptions, Tag, Space, Button, Card, notification, Alert} from 'antd';
import {PaperClipOutlined} from '@ant-design/icons';
import {http, hasPermission, X_TOKEN} from 'libs';
import AttachmentManager from 'components/AttachmentManager';
import {TASK_STATUS_MAP, DELIVERY_STATUS_MAP} from './utils';
import coopTaskBadge from '@/layout/CoopTaskBadgeStore';

function renderStatus(map, status) {
  const t = map[status] || {color: 'default', text: status};
  return <Tag color={t.color}>{t.text}</Tag>;
}

export default function InboxDetail(props) {
  const {assignmentId, onClose, onChanged} = props;
  const [loading, setLoading] = useState(false);
  const [task, setTask] = useState(null);
  // 各交付明细当前附件数（由 AttachmentManager onCountChange 回填），用于提交按钮可用性
  const [attachmentCounts, setAttachmentCounts] = useState({});
  // 提交防重复：请求完成前禁止对同一明细再次触发提交
  const [submittingIds, setSubmittingIds] = useState({});
  const submittingRef = useRef({});
  // 卸载与请求时序防护：卸载后不再回写状态；assignmentId 切换后旧请求响应不得覆盖新数据
  const mountedRef = useRef(true);
  const fetchSeqRef = useRef(0);
  useEffect(() => () => { mountedRef.current = false; }, []);
  const canSubmit = hasPermission('coop.task.submit');
  const editable = task && task.status === 'in_progress';

  const fetchData = useCallback(() => {
    const seq = ++fetchSeqRef.current;
    setLoading(true);
    http.get(`/api/coop-task/inbox/${assignmentId}/`)
      .then(data => {
        if (mountedRef.current && seq === fetchSeqRef.current) setTask(data);
      })
      .catch(() => { /* 错误已由 http 拦截器统一提示 */ })
      .finally(() => {
        if (mountedRef.current && seq === fetchSeqRef.current) setLoading(false);
      });
  }, [assignmentId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const doSubmit = (delivery) => {
    if (submittingRef.current[delivery.id]) return;
    const nextSubmitting = {...submittingRef.current, [delivery.id]: true};
    submittingRef.current = nextSubmitting;
    setSubmittingIds(nextSubmitting);
    http.post(`/api/coop-task/deliveries/${delivery.id}/submit/`)
      .then(() => {
        if (!mountedRef.current) return;
        notification.success({message: `「${delivery.item_name}」已提交，等待发起方验收`});
        fetchData();
        onChanged();
        coopTaskBadge.fetch();
      })
      .catch(() => { /* 错误已由 http 拦截器统一提示 */ })
      .finally(() => {
        const rest = {...submittingRef.current};
        delete rest[delivery.id];
        submittingRef.current = rest;
        if (mountedRef.current) setSubmittingIds(rest);
      });
  };

  const onCountChange = (deliveryId) => (count) => {
    if (mountedRef.current) setAttachmentCounts(prev => ({...prev, [deliveryId]: count}));
  };

  return (
    <Modal
      title="交付详情"
      visible
      width={860}
      footer={<Button onClick={onClose}>关闭</Button>}
      onCancel={onClose}
    >
      <div style={{maxHeight: '68vh', overflow: 'auto'}}>
        {task && (
          <>
            <Descriptions size="small" column={2} bordered>
              <Descriptions.Item label="任务标题" span={2}>{task.title}</Descriptions.Item>
              <Descriptions.Item label="任务说明" span={2}>{task.description || '-'}</Descriptions.Item>
              <Descriptions.Item label="截止时间">
                <Space size={4}>
                  {task.deadline}
                  {task.is_overdue && <Tag color="red">已逾期</Tag>}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="任务状态">
                {renderStatus(TASK_STATUS_MAP, task.status)}
              </Descriptions.Item>
              <Descriptions.Item label="发起人">
                {task.created_by_name}（{task.created_at}）
              </Descriptions.Item>
              <Descriptions.Item label="催办">
                {task.urge_count > 0 ? `被催办 ${task.urge_count} 次` : '无'}
              </Descriptions.Item>
            </Descriptions>

            {task.urge_count > 0 && (
              <Alert
                style={{marginTop: 12}}
                type="warning"
                showIcon
                message="发起方已催办，请尽快按材料要求上传并提交。"
              />
            )}

            {editable && (
              <Alert
                style={{marginTop: 12}}
                type="info"
                showIcon
                message="附件提交前仅本科室可见，请按材料要求上传后逐份点击「提交」，发起方验收通过即完成。"
              />
            )}

            {(task.items || []).map(item => {
              const canOperate = editable && item.status !== 'accepted';
              const hasFiles = (attachmentCounts[item.id] || item.attachment_count || 0) > 0;
              return (
                <Card
                  key={item.id}
                  size="small"
                  style={{marginTop: 12}}
                  title={
                    <Space size={8}>
                      <b>{item.item_name}</b>
                      {renderStatus(DELIVERY_STATUS_MAP, item.status)}
                      {item.item_remark && (
                        <span style={{color: '#999', fontWeight: 'normal'}}>{item.item_remark}</span>
                      )}
                    </Space>
                  }
                  extra={
                    canSubmit && editable && (
                      <Button
                        size="small"
                        type="primary"
                        disabled={item.status === 'submitted' || !hasFiles
                          || !!submittingIds[item.id]}
                        onClick={() => doSubmit(item)}>
                        {item.status === 'rejected' ? '重新提交' : '提交'}
                      </Button>
                    )
                  }
                >
                  {(item.templates || []).length > 0 && (
                    <div style={{marginBottom: 8}}>
                      {item.templates.map(t => (
                        <a key={t.id} style={{marginRight: 16}}
                          href={`/api/coop-task/attachments/${t.id}/download/?x-token=${X_TOKEN}`}>
                          <PaperClipOutlined /> 模板：{t.file_name}
                        </a>
                      ))}
                    </div>
                  )}
                  {item.status === 'rejected' && item.reject_reason && (
                    <Alert
                      style={{marginBottom: 8}}
                      type="error"
                      showIcon
                      message={`被退回：${item.reject_reason}`}
                    />
                  )}
                  <AttachmentManager
                    module="coop_task"
                    recordId={item.id}
                    readOnly={!canOperate || !canSubmit}
                    uploadPerm="coop.task.submit"
                    deletePerm="coop.task.submit"
                    maxFileSize={50}
                    multiple
                    maxFilesPerBatch={20}
                    accept=".pdf,.jpg,.jpeg,.png,.gif,.bmp,.webp,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.zip,.rar,.7z"
                    listUrl={`/api/coop-task/deliveries/${item.id}/attachments/`}
                    uploadUrl={`/api/coop-task/deliveries/${item.id}/attachments/`}
                    deleteUrl="/api/coop-task/attachments/"
                    downloadUrlPrefix="/api/coop-task/attachments/"
                    previewUrlPrefix="/api/coop-task/attachments/"
                    onCountChange={onCountChange(item.id)}
                  />
                </Card>
              );
            })}
          </>
        )}
      </div>
    </Modal>
  );
}

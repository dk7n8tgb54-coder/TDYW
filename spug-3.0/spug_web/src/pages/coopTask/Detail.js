/**
 * 协作任务详情（发起方视角）
 * 任务信息 + 各科室进度（催办）+ 材料×科室交付矩阵（验收/退回/附件查看）
 */
import React, {useState, useEffect, useCallback, useRef} from 'react';
import {Modal, Descriptions, Tag, Space, Table, Button, Popconfirm, Modal as AntModal, Input, notification} from 'antd';
import {PaperClipOutlined} from '@ant-design/icons';
import {http, hasPermission, X_TOKEN} from 'libs';
import AttachmentManager from 'components/AttachmentManager';
import TemplateManageModal from './TemplateManageModal';
import {TASK_STATUS_MAP, ASSIGNMENT_STATUS_MAP, DELIVERY_STATUS_MAP} from './utils';

function renderStatus(map, status) {
  const t = map[status] || {color: 'default', text: status};
  return <Tag color={t.color}>{t.text}</Tag>;
}

// 分派对象展示名：按账号分发的任务显示账号人名，旧任务回落到科室名
function targetLabel(assignment) {
  if (!assignment) return '';
  return (assignment.contact_user_id && assignment.contact_user_name)
    || assignment.target_tenant_name || '';
}

function RejectModal({rejecting, rejectReason, onReasonChange, onCancel, onReject}) {
  return (
    <AntModal
      title="退回该材料"
      visible={!!rejecting}
      confirmLoading={false}
      onCancel={onCancel}
      onOk={onReject}
    >
      <p>
        材料：<b>{rejecting && rejecting.item_name}</b>
        （{rejecting && rejecting._assignment && targetLabel(rejecting._assignment)}）
      </p>
      <Input.TextArea
        rows={3}
        maxLength={500}
        value={rejectReason}
        placeholder="请填写退回原因，交付科室可据此重新修改提交"
        onChange={onReasonChange}
      />
    </AntModal>
  );
}

export default function TaskDetail(props) {
  const {taskId, onClose, onChanged, autoOpenTemplate} = props;
  const [loading, setLoading] = useState(false);
  const [task, setTask] = useState(null);
  const [rejecting, setRejecting] = useState(null); // 待退回的交付明细
  const [rejectReason, setRejectReason] = useState('');
  const [templateItem, setTemplateItem] = useState(null); // 正在管理模板的材料
  const autoOpenedRef = useRef(false); // 引导弹窗只自动打开一次
  // 卸载与请求时序防护：卸载后不再回写状态；taskId 切换后旧请求响应不得覆盖新数据
  const mountedRef = useRef(true);
  const fetchSeqRef = useRef(0);
  useEffect(() => () => { mountedRef.current = false; }, []);

  const fetchData = useCallback(() => {
    const seq = ++fetchSeqRef.current;
    setLoading(true);
    http.get(`/api/coop-task/tasks/${taskId}/`)
      .then(data => {
        if (!mountedRef.current || seq !== fetchSeqRef.current) return;
        setTask(data);
        // 新建任务后的引导：自动打开第一个材料的模板上传
        if (autoOpenTemplate && !autoOpenedRef.current && data.status === 'in_progress'
            && hasPermission('coop.task.edit') && data.items && data.items.length) {
          autoOpenedRef.current = true;
          setTemplateItem(data.items[0]);
        }
      })
      .catch(() => { /* 错误已由 http 拦截器统一提示 */ })
      .finally(() => {
        if (mountedRef.current && seq === fetchSeqRef.current) setLoading(false);
      });
  }, [taskId, autoOpenTemplate]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const doUrge = (assignment) => {
    http.post(`/api/coop-task/tasks/${taskId}/urge/`, {assignment_id: assignment.id})
      .then(() => {
        if (!mountedRef.current) return;
        notification.success({message: `已催办 ${targetLabel(assignment)}`});
        fetchData();
      })
      .catch(() => { /* 错误已由 http 拦截器统一提示 */ });
  };

  const doAccept = (delivery) => {
    http.post(`/api/coop-task/deliveries/${delivery.id}/accept/`)
      .then(() => {
        if (!mountedRef.current) return;
        notification.success({message: '已验收通过'});
        fetchData();
        onChanged();
      })
      .catch(() => { /* 错误已由 http 拦截器统一提示 */ });
  };

  const doReject = () => {
    const reason = rejectReason.trim();
    if (!reason) {
      notification.warning({message: '请填写退回原因'});
      return;
    }
    http.post(`/api/coop-task/deliveries/${rejecting.id}/reject/`, {reason})
      .then(() => {
        if (!mountedRef.current) return;
        notification.success({message: '已退回'});
        setRejecting(null);
        setRejectReason('');
        fetchData();
        onChanged();
      })
      .catch(() => { /* 错误已由 http 拦截器统一提示 */ });
  };

  const closeTemplateModal = () => {
    setTemplateItem(null);
    fetchData(); // 模板可能变更，刷新材料清单中的下载链接
  };

  const matrixRows = [];
  if (task) {
    for (const assignment of task.assignments || []) {
      for (const delivery of assignment.deliveries || []) {
        matrixRows.push({...delivery, _assignment: assignment});
      }
    }
  }

  const columns = [
    {
      title: '交付对象', key: 'tenant', width: 110,
      render: (_, r) => targetLabel(r._assignment),
    },
    {title: '材料', dataIndex: 'item_name', key: 'item_name', width: 160},
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: s => renderStatus(DELIVERY_STATUS_MAP, s),
    },
    {title: '提交时间', dataIndex: 'submitted_at', key: 'submitted_at', width: 140},
    {title: '提交人', dataIndex: 'submitter_name', key: 'submitter_name', width: 90},
    {
      title: '附件', dataIndex: 'attachment_count', key: 'attachment_count', width: 70,
      render: (v) => `${v || 0} 个`,
    },
    {
      title: '退回原因', dataIndex: 'reject_reason', key: 'reject_reason', ellipsis: true,
      render: v => (v ? <span style={{color: '#ff4d4f'}}>{v}</span> : '-'),
    },
    {
      title: '操作', key: 'action', width: 150,
      render: (_, r) => {
        const canAccept = hasPermission('coop.task.accept') && task && task.status === 'in_progress';
        return (
          <Space>
            {canAccept && r.status === 'submitted' && (
              <Popconfirm title={`确认验收通过「${r.item_name}」？`}
                          onConfirm={() => doAccept(r)}>
                <a>通过</a>
              </Popconfirm>
            )}
            {canAccept && r.status === 'submitted' && (
              <a style={{color: '#ff4d4f'}} onClick={() => setRejecting(r)}>退回</a>
            )}
          </Space>
        );
      },
    },
  ];

  return (
    <Modal
      title="任务详情"
      visible
      width={960}
      footer={<Button onClick={onClose}>关闭</Button>}
      onCancel={onClose}
    >
      <div style={{maxHeight: '68vh', overflow: 'auto'}}>
        {task && (
          <>
            <Descriptions size="small" column={2} bordered>
              <Descriptions.Item label="任务标题" span={2}>{task.title}</Descriptions.Item>
              <Descriptions.Item label="任务说明" span={2}>
                {task.description || '-'}
              </Descriptions.Item>
              <Descriptions.Item label="截止时间">
                <Space size={4}>
                  {task.deadline}
                  {task.is_overdue && <Tag color="red">已逾期</Tag>}
                </Space>
              </Descriptions.Item>
              <Descriptions.Item label="状态">
                {renderStatus(TASK_STATUS_MAP, task.status)}
                {task.completed_at && `（${task.completed_at}）`}
              </Descriptions.Item>
              <Descriptions.Item label="发起人">
                {task.created_by_name}（{task.created_at}）
              </Descriptions.Item>
              <Descriptions.Item label="材料清单" span={2}>
                {(task.items || []).map(x => (
                  <div key={x.id} style={{marginBottom: 2}}>
                    {x.name}
                    {x.remark ? <span style={{color: '#999'}}>（{x.remark}）</span> : null}
                    {(x.templates || []).map(t => (
                      <a key={t.id} style={{marginLeft: 8}}
                        href={`/api/coop-task/attachments/${t.id}/download/?x-token=${X_TOKEN}`}>
                        <PaperClipOutlined /> 模板：{t.file_name}
                      </a>
                    ))}
                    {task.status === 'in_progress' && hasPermission('coop.task.edit') && (
                      <a style={{marginLeft: 8}} onClick={() => setTemplateItem(x)}>管理模板</a>
                    )}
                  </div>
                ))}
              </Descriptions.Item>
            </Descriptions>

            <div style={{margin: '16px 0 8px'}}>
              <b>各科室进度</b>
            </div>
            <Space direction="vertical" style={{width: '100%'}}>
              {(task.assignments || []).map(a => (
                <Space key={a.id} size={12}
                       style={{border: '1px solid #f0f0f0', padding: '6px 12px', borderRadius: 4, width: '100%'}}>
                  <b>{targetLabel(a)}</b>
                  {a.contact_user_id ? (
                    a.target_tenant_name && <span>（{a.target_tenant_name}）</span>
                  ) : (
                    a.contact_user_name && <span>经办人：{a.contact_user_name}</span>
                  )}
                  {renderStatus(ASSIGNMENT_STATUS_MAP, a.aggregate_status)}
                  {a.urge_count > 0 && <span>已催办 {a.urge_count} 次</span>}
                  {task.status === 'in_progress' && a.aggregate_status !== 'accepted'
                    && hasPermission('coop.task.edit') && (
                      <Button size="small" type="link" onClick={() => doUrge(a)}>催办</Button>
                    )}
                </Space>
              ))}
            </Space>

            <div style={{margin: '16px 0 8px'}}>
              <b>交付明细</b>
            </div>
            <Table
              rowKey="id"
              size="small"
              loading={loading}
              columns={columns}
              dataSource={matrixRows}
              pagination={false}
              expandedRowRender={(r) => (
                r.status === 'pending' ? (
                  <div style={{color: '#999', padding: '2px 0'}}>
                    该材料尚未提交，附件将在交付方提交后可见
                  </div>
                ) : (
                  <AttachmentManager
                    module="coop_task"
                    recordId={r.id}
                    readOnly
                    listUrl={`/api/coop-task/deliveries/${r.id}/attachments/`}
                    downloadUrlPrefix="/api/coop-task/attachments/"
                    previewUrlPrefix="/api/coop-task/attachments/"
                  />
                )
              )}
            />
          </>
        )}
      </div>

      <RejectModal
        rejecting={rejecting}
        rejectReason={rejectReason}
        onReasonChange={e => setRejectReason(e.target.value)}
        onCancel={() => setRejecting(null)}
        onReject={doReject}
      />
    </Modal>
  );
}
